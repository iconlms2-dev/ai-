"""키워드 현황 — 채널 배정, 작업 기록, 동기화, 노출 체크"""
import json
import asyncio
import logging
from urllib.parse import quote

import requests as req
from bs4 import BeautifulSoup
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from src.services.sse_helper import sse_dict, SSEResponse

from src.services.config import executor, NOTION_TOKEN, KEYWORD_DB_ID, CONTENT_DB_ID
from src.services.common import error_response
from src.services.notion_client import notion_query_all, extract_prop, notion_headers

logger = logging.getLogger(__name__)

router = APIRouter()


# ── helpers ────────────────────────────────────────────────────────

def _check_exposure_one(keyword, deploy_url):
    """네이버 검색에서 해당 URL 노출 여부 확인"""
    if not deploy_url:
        return {'exposure': '-', 'rank': ''}
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'}
    try:
        r = req.get('https://search.naver.com/search.naver?query=%s&where=nexearch' % quote(keyword), headers=headers, timeout=10)
        html = r.text
        # URL 존재 확인
        if deploy_url in html:
            # 순위 추정: 링크 등장 위치
            soup = BeautifulSoup(html, 'html.parser')
            rank = 0
            for i, a in enumerate(soup.find_all('a', href=True)):
                if deploy_url in a.get('href', ''):
                    rank = i + 1
                    break
            return {'exposure': '노출중', 'rank': str(rank) if rank else '확인됨'}
        return {'exposure': '미노출', 'rank': ''}
    except Exception:
        return {'exposure': '-', 'rank': ''}


# ── endpoints ──────────────────────────────────────────────────────

@router.patch("/assign-channel")
async def assign_channel(body: dict):
    page_id = body.get('page_id', '')
    channels = body.get('channels', [])
    if not page_id:
        return JSONResponse({'ok': False, 'error': 'page_id required'}, 400)
    headers = {
        'Authorization': f'Bearer {NOTION_TOKEN}',
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28',
    }
    props = {'배정 채널': {'multi_select': [{'name': ch} for ch in channels]}}
    try:
        from src.services.notion_client import update_page
        result = update_page(page_id, props)
        return {'ok': result['success']}
    except Exception as e:
        logger.error("assign_channel 실패: %s", e)
        return JSONResponse({'ok': False, 'error': 'Notion API error'}, 500)


@router.patch("/record-work")
async def record_work(body: dict):
    """콘텐츠 작업 기록 (배포 후)"""
    page_id = body.get('page_id', '')
    if not page_id:
        return JSONResponse({'ok': False, 'error': 'page_id required'}, 400)
    headers = {
        'Authorization': f'Bearer {NOTION_TOKEN}',
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28',
    }
    props = {'발행_상태': {'select': {'name': '발행완료'}}}
    if body.get('posted_url'):
        props['발행_URL'] = {'url': body['posted_url']}
    if body.get('deploy_date'):
        props['생성일'] = {'date': {'start': body['deploy_date']}}
    if body.get('work_account'):
        props['작업계정'] = {'rich_text': [{'text': {'content': body['work_account']}}]}
    if body.get('work_cafe'):
        props['작업카페'] = {'rich_text': [{'text': {'content': body['work_cafe']}}]}
    if body.get('agency'):
        props['실행사'] = {'rich_text': [{'text': {'content': body['agency']}}]}
    if body.get('work_cost') is not None and body['work_cost'] != '':
        try:
            props['작업비용'] = {'number': int(body['work_cost'])}
        except Exception:
            pass
    try:
        from src.services.notion_client import update_page
        from src.services.indexnow import submit_url
        result = update_page(page_id, props)
        # 발행 URL이 있으면 IndexNow로 검색엔진에 즉시 알림
        if result['success'] and body.get('posted_url'):
            submit_url(body['posted_url'])
        return {'ok': result['success']}
    except Exception as e:
        logger.error("record_work 실패: %s", e)
        return JSONResponse({'ok': False, 'error': 'Notion API error'}, 500)


@router.get("/sync")
async def status_sync():
    """키워드 현황 데이터 동기화 (키워드 DB + 콘텐츠 DB 조인)"""
    loop = asyncio.get_running_loop()

    # 키워드 DB 조회
    kw_pages = await loop.run_in_executor(executor, notion_query_all, KEYWORD_DB_ID, None)
    # 콘텐츠 DB 조회
    ct_pages = await loop.run_in_executor(executor, notion_query_all, CONTENT_DB_ID, None)

    # 콘텐츠 → 키워드 릴레이션 매핑
    content_by_kw = {}  # kw_page_id → [content_info, ...]
    for page in ct_pages:
        props = page.get('properties', {})
        kw_rels = extract_prop(props, '키워드', 'relation')
        ct_info = {
            'title': extract_prop(props, '제목', 'title'),
            'channel': extract_prop(props, '채널', 'select'),
            'prod_status': extract_prop(props, '생산 상태', 'select'),
            'deploy_status': extract_prop(props, '발행_상태', 'select'),
            'deploy_date': extract_prop(props, '생성일', 'date'),
            'deploy_url': extract_prop(props, '발행_URL', 'url'),
            'body_summary': extract_prop(props, '본문', 'rich_text'),
        }
        for kw_id in kw_rels:
            if kw_id not in content_by_kw:
                content_by_kw[kw_id] = []
            content_by_kw[kw_id].append(ct_info)

    # 키워드 → 최종 행 만들기
    rows = []
    for page in kw_pages:
        pid = page['id']
        props = page.get('properties', {})
        keyword = extract_prop(props, '키워드', 'title')
        if not keyword:
            continue
        channels = extract_prop(props, '배정 채널', 'multi_select')
        search_vol = extract_prop(props, '검색량', 'number')
        competition = extract_prop(props, '경쟁 강도', 'select')
        contact = extract_prop(props, '구매여정_단계', 'select')
        status = extract_prop(props, '상태', 'select')

        contents = content_by_kw.get(pid, [])
        work_status = '생성완료' if contents else '미작업'
        deploy_status = ''
        deploy_date = ''
        deploy_url = ''
        content_title = ''
        body_preview = ''
        if contents:
            ct = contents[0]
            deploy_status = ct.get('deploy_status', '')
            deploy_date = ct.get('deploy_date', '')
            deploy_url = ct.get('deploy_url', '')
            content_title = ct.get('title', '')
            body_preview = ct.get('body_summary', '')[:200]

        rows.append({
            'page_id': pid, 'keyword': keyword,
            'channels': ','.join(channels) if channels else '',
            'search_vol': search_vol, 'competition': competition,
            'contact_point': contact, 'kw_status': status,
            'work_status': work_status, 'deploy_status': deploy_status,
            'deploy_date': deploy_date, 'deploy_url': deploy_url,
            'content_title': content_title, 'body_preview': body_preview,
            'exposure': '-', 'rank': '', 'views': '',
        })

    # 집계
    total = len(rows)
    created = sum(1 for r in rows if r['work_status'] == '생성완료')
    deployed = sum(1 for r in rows if r['deploy_status'] == '발행완료')
    unworked = total - created
    summary = {'total': total, 'created': created, 'deployed': deployed, 'exposed': 0, 'unworked': unworked}

    return {'rows': rows, 'summary': summary}


@router.post("/check-exposure")
async def check_exposure(request: Request):
    """노출 체크 (SSE)"""
    body = await request.json()
    items = body.get('items', [])  # [{keyword, deploy_url}, ...]

    _sse = sse_dict

    async def generate():
      try:
        loop = asyncio.get_running_loop()
        total = len(items)
        results = []
        for i, item in enumerate(items):
            kw = item.get('keyword', '')
            url = item.get('deploy_url', '')
            yield _sse({'type': 'progress', 'msg': '[%d/%d] %s 노출 확인 중...' % (i+1, total, kw), 'cur': i+1, 'total': total})
            result = await loop.run_in_executor(executor, _check_exposure_one, kw, url)
            result['keyword'] = kw
            results.append(result)
            yield _sse({'type': 'result', 'data': result, 'cur': i+1, 'total': total})
            await asyncio.sleep(1.5)
        yield _sse({'type': 'complete', 'total': total, 'results': results})
      except Exception as e:
        print(f"[check_exposure] 에러: {e}")
        yield _sse({'type': 'error', 'message': f'노출 체크 중 오류: {e}'})

    return SSEResponse(generate())
