"""일괄 생성 API 라우터"""
import asyncio
import json
from datetime import datetime

import requests as req
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from src.services.config import (
    executor, NOTION_TOKEN, CONTENT_DB_ID, KEYWORD_DB_ID,
)
from src.services.common import error_response
from src.services.ai_client import call_claude

router = APIRouter()


# ═══════════════════════════ HELPERS ═══════════════════════════

def _batch_save_to_notion(channel, keyword, page_id, title, body, account_id=''):
    """일괄 생성 후 자동 Notion 저장 (공통)"""
    headers_n = {'Authorization': 'Bearer %s' % NOTION_TOKEN, 'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'}
    props = {
        '제목': {'title': [{'text': {'content': title}}]},
        '채널': {'select': {'name': channel}},
        '생산 상태': {'select': {'name': '초안'}},
        '발행_상태': {'select': {'name': '미발행'}},
    }
    if body:
        props['본문'] = {'rich_text': [{'text': {'content': body[:2000]}}]}
    if page_id:
        props['키워드'] = {'relation': [{'id': page_id}]}
    if account_id:
        props['작업계정'] = {'select': {'name': account_id}}
    payload = {'parent': {'database_id': CONTENT_DB_ID}, 'properties': props}
    if body:
        children = []
        for para in [p.strip() for p in body.split('\n\n') if p.strip()][:100]:
            for k in range(0, len(para), 2000):
                children.append({'object': 'block', 'type': 'paragraph',
                    'paragraph': {'rich_text': [{'type': 'text', 'text': {'content': para[k:k+2000]}}]}})
        payload['children'] = children[:100]
    try:
        r = req.post('https://api.notion.com/v1/pages', headers=headers_n, json=payload, timeout=15)
        if r.status_code != 200:
            print(f"[batch_save_to_notion] 저장 실패 channel={channel} keyword={keyword}: {r.status_code} {r.text[:200]}")
        return r.status_code == 200
    except Exception as e:
        print(f"[batch_save_to_notion] 저장 에러 channel={channel} keyword={keyword}: {e}")
        return False


# ═══════════════════════════ ENDPOINTS ═══════════════════════════

@router.get("/keywords")
async def batch_keywords():
    """일괄 생성용: 배정완료 + 미사용 키워드 로드"""
    headers = {'Authorization': 'Bearer %s' % NOTION_TOKEN, 'Content-Type': 'application/json', 'Notion-Version': '2022-06-28'}
    payload = {
        'filter': {'and': [
            {'property': '상태', 'select': {'equals': '미사용'}},
            {'property': '배정 채널', 'multi_select': {'is_not_empty': True}},
        ]},
        'page_size': 100,
    }
    try:
        r = req.post('https://api.notion.com/v1/databases/%s/query' % KEYWORD_DB_ID, headers=headers, json=payload, timeout=15)
        if r.status_code != 200:
            return {'keywords': []}
        keywords = []
        for page in r.json().get('results', []):
            props = page.get('properties', {})
            t = props.get('키워드', {}).get('title', [])
            kw = t[0]['text']['content'] if t else ''
            channels = [c['name'] for c in props.get('배정 채널', {}).get('multi_select', [])]
            channel = channels[0] if channels else ''
            stage_sel = props.get('구매여정_단계', {}).get('select')
            stage = stage_sel['name'] if stage_sel else ''
            if kw and channel:
                keywords.append({'keyword': kw, 'channel': channel, 'page_id': page['id'], 'stage': stage})
        return {'keywords': keywords}
    except Exception:
        return {'keywords': []}


@router.post("/generate")
async def batch_generate(request: Request):
    """일괄 생성: 키워드별 배정 채널에 맞게 순차 생성 + 자동 Notion 저장"""
    # 채널별 프롬프트 빌더는 server.py에 남아있음 — 추후 서비스 레이어로 이동 시 임포트 경로 변경
    from server import (
        _prompt_load_overrides,
        _build_blog_title_prompt, _build_blog_body_prompt,
        _build_cafe_title_prompt, _build_cafe_body_prompt, _build_cafe_comments_prompt,
        _build_jisikin_title_prompt, _build_jisikin_body_prompt, _build_jisikin_answers_prompt,
        _build_viral_stage1_prompt, _build_viral_stage2_prompt, _build_viral_stage3_prompt,
        _parse_viral_output, _parse_viral_stage3,
        _call_claude,
    )
    from src.api.naver import _naver_load_accounts, _naver_save_accounts

    body = await request.json()
    items = body.get('keywords', [])
    product = body.get('product', {})
    default_account = body.get('account_id', '')

    def _sse(obj):
        return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"

    async def generate():
      try:
        loop = asyncio.get_running_loop()
        total = len(items)
        for idx, item in enumerate(items, 1):
            if await request.is_disconnected():
                print("[batch_generate] 클라이언트 연결 끊김")
                return
            kw = item.get('keyword', '')
            channel = item.get('channel', '')
            page_id = item.get('page_id', '')
            stage = item.get('stage', '')
            acc_id = item.get('account_id', default_account)

            yield _sse({'type': 'progress', 'msg': f'[{idx}/{total}] {kw} — {channel} 생성 중...', 'cur': idx-1, 'total': total})

            title = ''
            body_text = ''
            extra = {}

            try:
                if channel == '블로그':
                    # STEP 1: 제목
                    overrides = _prompt_load_overrides()
                    t_sys = overrides.get('블로그_제목', None)
                    if t_sys:
                        t_usr = f"상위 노출 키워드: {kw}"
                    else:
                        t_sys, t_usr = _build_blog_title_prompt(kw, product)
                    title_raw = await loop.run_in_executor(executor, _call_claude, t_sys, t_usr)
                    title = title_raw.strip().replace('제목:', '').replace('제목 :', '').strip().split('\n')[0]
                    # STEP 2: 본문
                    b_sys = overrides.get('블로그_본문', None)
                    if b_sys:
                        b_usr = f"[시스템 자동 전달]\n제목: {title}\n\n[사용자 입력]\n상위 노출 키워드: {kw}\n제품명: {product.get('name','')}\n제품 USP (차별 포인트): {product.get('usp','')}\n타겟층: {product.get('target','')}\n주요 성분: {product.get('ingredients','')}\n나만의 키워드: {product.get('brand_keyword','')}\n구매여정 단계: {stage}\n사진 수: 10장\n키워드 반복 수: 5회\n\n위 정보를 기반으로, 제목과 맥락이 맞는 후기형 블로그 본문을 작성해주세요."
                    else:
                        b_sys, b_usr = _build_blog_body_prompt(kw, stage, product, 10, 5, title)
                    body_text = (await loop.run_in_executor(executor, _call_claude, b_sys, b_usr)).strip()

                elif channel in ('카페', '카페SEO'):
                    # STEP 1: 제목
                    sys1, usr1 = _build_cafe_title_prompt(kw, '')
                    title_raw = await loop.run_in_executor(executor, _call_claude, sys1, usr1)
                    title = title_raw.strip().split('\n')[0].strip()
                    # STEP 2: 본문
                    sys2, usr2 = _build_cafe_body_prompt(kw, title, '', {}, product)
                    body_text = (await loop.run_in_executor(executor, _call_claude, sys2, usr2)).strip()
                    # STEP 3: 댓글
                    sys3, usr3 = _build_cafe_comments_prompt(kw, body_text, product.get('brand_keyword', ''), product.get('alternatives', ''))
                    comments = (await loop.run_in_executor(executor, _call_claude, sys3, usr3)).strip()
                    extra = {'comments': comments}

                elif channel == '지식인':
                    # 질문 제목
                    sys1, usr1 = _build_jisikin_title_prompt(kw, product)
                    q_title = await loop.run_in_executor(executor, _call_claude, sys1, usr1)
                    q_title = q_title.strip()
                    # 질문 본문
                    sys2, usr2 = _build_jisikin_body_prompt(kw, product)
                    q_body = await loop.run_in_executor(executor, _call_claude, sys2, usr2)
                    q_body = q_body.strip()
                    # 답변
                    sys3, usr3 = _build_jisikin_answers_prompt(kw, q_title, q_body, product)
                    answers = await loop.run_in_executor(executor, _call_claude, sys3, usr3)
                    title = q_title
                    body_text = f"[질문]\n{q_title}\n\n{q_body}\n\n[답변]\n{answers.strip()}"
                    extra = {'q_title': q_title, 'q_body': q_body, 'answers': answers.strip()}

                elif channel == '카페바이럴':
                    # 3단계: 일상글 → 고민글 → 침투글+댓글
                    target_concern = product.get('target_concern', kw)
                    brand_keyword = product.get('brand_keyword', '')
                    s1_sys, s1_usr = _build_viral_stage1_prompt('', product.get('target', ''), '')
                    raw1 = await loop.run_in_executor(executor, _call_claude, s1_sys, s1_usr)
                    s1 = _parse_viral_output(raw1)
                    s2_sys, s2_usr = _build_viral_stage2_prompt('', target_concern, product.get('product_category', ''))
                    raw2 = await loop.run_in_executor(executor, _call_claude, s2_sys, s2_usr)
                    s2 = _parse_viral_output(raw2)
                    s3_sys, s3_usr = _build_viral_stage3_prompt('', target_concern, brand_keyword, product.get('name', ''), product.get('usp', ''), product.get('ingredients', ''), product.get('product_category', ''))
                    raw3 = await loop.run_in_executor(executor, _call_claude, s3_sys, s3_usr)
                    s3 = _parse_viral_stage3(raw3)
                    title = s3.get('title', '') or s2.get('title', '') or s1.get('title', '')
                    body_text = f"[1단계 일상글]\n{s1.get('title','')}\n{s1.get('body','')}\n\n[2단계 고민글]\n{s2.get('title','')}\n{s2.get('body','')}\n\n[3단계 침투글]\n{s3.get('title','')}\n{s3.get('body','')}\n\n[댓글]\n{chr(10).join(s3.get('comments',[]))}"
                    extra = {'stage1': s1, 'stage2': s2, 'stage3': s3}

                else:
                    yield _sse({'type': 'progress', 'msg': f'[{idx}/{total}] {kw} — 미지원 채널: {channel}', 'cur': idx, 'total': total})
                    continue

                # 자동 Notion 저장
                saved = await loop.run_in_executor(executor, _batch_save_to_notion, channel, kw, page_id, title, body_text, acc_id)

                # 계정 사용 기록 업데이트
                if acc_id:
                    accs = _naver_load_accounts()
                    for a in accs:
                        if a['id'] == acc_id:
                            a['total_posts'] = a.get('total_posts', 0) + 1
                            a['last_used_at'] = datetime.now().isoformat()
                            break
                    _naver_save_accounts(accs)

                result = {
                    'keyword': kw, 'channel': channel, 'title': title,
                    'body_preview': body_text[:200], 'saved': saved,
                    'account_id': acc_id, **extra,
                }
                yield _sse({'type': 'result', 'data': result, 'cur': idx, 'total': total})

            except Exception as e:
                yield _sse({'type': 'result', 'data': {'keyword': kw, 'channel': channel, 'error': str(e), 'saved': False}, 'cur': idx, 'total': total})

        yield _sse({'type': 'complete', 'total': total})
      except Exception as e:
        print(f"[batch_generate] 에러: {e}")
        yield _sse({'type': 'error', 'message': f'일괄 생성 중 오류: {e}'})

    return StreamingResponse(generate(), media_type="text/event-stream")
