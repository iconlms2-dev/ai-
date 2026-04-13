"""성과 수집 및 모니터링"""
import json
import re
import os
import time
import asyncio
from datetime import datetime, timedelta
from urllib.parse import quote

import requests as req
from bs4 import BeautifulSoup
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from src.services.config import (
    executor, BASE_DIR, PERF_DATA_FILE, PERF_SCHEDULE_FILE,
    NOTION_TOKEN, CONTENT_DB_ID, SECTION_MAP,
)
from src.services.common import error_response
from src.services.notion_client import notion_query_all, extract_prop

router = APIRouter()

# ── 모듈 상태 ─────────────────────────────────────────────────────
_perf_schedule = {"enabled": False, "interval_hours": 24}


# ── helpers ────────────────────────────────────────────────────────

def _perf_load():
    if os.path.exists(PERF_DATA_FILE):
        try:
            with open(PERF_DATA_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {"records": [], "last_checked": "", "total_checks": 0}


def _perf_save(data):
    data["records"] = data["records"][-10000:]  # 최근 10000건 유지
    with open(PERF_DATA_FILE, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _check_exposure_enhanced(keyword, deploy_url, channel=''):
    """네이버 검색에서 URL 노출 여부 + 섹션명 + 정확한 순위"""
    if not deploy_url:
        return {'exposure': '-', 'rank': 0, 'section': ''}
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'}
    try:
        r = req.get('https://search.naver.com/search.naver?query=%s&where=nexearch' % quote(keyword), headers=headers, timeout=10)
        html = r.text
        if deploy_url not in html:
            return {'exposure': '미노출', 'rank': 0, 'section': ''}
        soup = BeautifulSoup(html, 'html.parser')
        # 섹션별 순위 파악
        section_name = ''
        rank_in_section = 0
        # SERP API 방식: data-cr-area 속성으로 섹션 식별
        containers = soup.find_all(attrs={'data-cr-area': True})
        for container in containers:
            area_code = container.get('data-cr-area', '')
            if deploy_url in str(container):
                section_name = SECTION_MAP.get(area_code, area_code)
                # 섹션 내 링크 순위
                links = container.find_all('a', href=True)
                for idx, a in enumerate(links):
                    if deploy_url in a.get('href', ''):
                        rank_in_section = idx + 1
                        break
                break
        # fallback: 전체 페이지에서 순위
        if not rank_in_section:
            for i, a in enumerate(soup.find_all('a', href=True)):
                if deploy_url in a.get('href', ''):
                    rank_in_section = i + 1
                    break
        return {'exposure': '노출중', 'rank': rank_in_section, 'section': section_name}
    except Exception as e:
        print(f"[perf] exposure check error: {e}")
        return {'exposure': '-', 'rank': 0, 'section': ''}


def _fetch_blog_stats(deploy_url):
    """네이버 블로그 모바일 페이지에서 조회수/댓글수/공감수 크롤링"""
    result = {'views': 0, 'comments': 0, 'likes': 0}
    if not deploy_url:
        return result
    try:
        m = re.search(r'blog\.naver\.com/([^/?]+)/(\d+)', deploy_url)
        if not m:
            return result
        blog_id, log_no = m.group(1), m.group(2)
        mobile_url = f"https://m.blog.naver.com/{blog_id}/{log_no}"
        headers = {'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1'}
        r = req.get(mobile_url, headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        # 조회수
        view_el = soup.select_one('.u_cnt._count, .view_count .u_cnt, .blog_count, [class*="view"] [class*="count"], .info_count .num')
        if view_el:
            view_text = re.sub(r'[^\d]', '', view_el.get_text())
            if view_text:
                result['views'] = int(view_text)
        # 댓글수
        comment_el = soup.select_one('.comment_count, .btn_comment .u_cnt, [class*="comment"] [class*="count"], .comment_area .num')
        if comment_el:
            comment_text = re.sub(r'[^\d]', '', comment_el.get_text())
            if comment_text:
                result['comments'] = int(comment_text)
        # 공감수
        like_el = soup.select_one('.sympathy_count, .btn_like .u_cnt, [class*="like"] [class*="count"], .sympathy_area .num')
        if like_el:
            like_text = re.sub(r'[^\d]', '', like_el.get_text())
            if like_text:
                result['likes'] = int(like_text)
    except Exception as e:
        print(f"[perf] blog stats error: {e}")
    return result


def _run_performance_collect_sync(items):
    """성과 수집 실행 (동기, 스레드에서 호출)"""
    results = []
    for item in items:
        kw = item.get('keyword', '')
        url = item.get('deploy_url', '')
        channel = item.get('channel', '')
        title = item.get('title', '')
        deploy_date = item.get('deploy_date', '')
        # 노출 체크
        exp = _check_exposure_enhanced(kw, url, channel)
        # 블로그면 반응 데이터도 수집
        stats = {'views': 0, 'comments': 0, 'likes': 0}
        if channel == '블로그' and 'blog.naver.com' in (url or ''):
            stats = _fetch_blog_stats(url)
        record = {
            'checked_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            'keyword': kw,
            'channel': channel,
            'title': title,
            'deploy_url': url,
            'deploy_date': deploy_date,
            'work_account': item.get('work_account', ''),
            'exposure': exp['exposure'],
            'rank': exp['rank'],
            'section': exp['section'],
            'views': stats['views'],
            'comments': stats['comments'],
            'likes': stats['likes'],
        }
        results.append(record)
        time.sleep(1.5)  # 차단 방지
    return results


# ── endpoints ──────────────────────────────────────────────────────

@router.post("/collect")
async def performance_collect(request: Request):
    """성과 수집 실행 (SSE 스트리밍)"""
    body = await request.json()
    mode = body.get('mode', 'all')  # all | selected
    selected_items = body.get('items', [])

    def _sse(obj):
        return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"

    async def generate():
      try:
        loop = asyncio.get_running_loop()
        items = []
        if mode == 'all':
            # 배포완료 콘텐츠 전체 조회
            yield _sse({'type': 'progress', 'msg': '노션에서 배포 콘텐츠 조회 중...', 'cur': 0, 'total': 0})
            filter_obj = {'property': '발행_상태', 'select': {'equals': '발행완료'}}
            pages = await loop.run_in_executor(executor, notion_query_all, CONTENT_DB_ID, filter_obj)
            for page in pages:
                props = page.get('properties', {})
                kw_rels = extract_prop(props, '키워드', 'relation')
                kw_name = ''
                if kw_rels:
                    # 키워드 이름 가져오기
                    try:
                        kw_r = req.get('https://api.notion.com/v1/pages/%s' % kw_rels[0],
                                       headers={'Authorization': 'Bearer %s' % NOTION_TOKEN, 'Notion-Version': '2022-06-28'}, timeout=10)
                        if kw_r.status_code == 200:
                            kw_props = kw_r.json().get('properties', {})
                            kw_name = extract_prop(kw_props, '키워드', 'title')
                    except Exception:
                        pass
                work_acc = extract_prop(props, '작업계정', 'select')
                if not work_acc:
                    work_acc_rt = props.get('작업계정', {}).get('rich_text', [])
                    work_acc = work_acc_rt[0]['text']['content'] if work_acc_rt else ''
                items.append({
                    'keyword': kw_name,
                    'title': extract_prop(props, '제목', 'title'),
                    'channel': extract_prop(props, '채널', 'select'),
                    'deploy_url': extract_prop(props, '발행_URL', 'url'),
                    'deploy_date': extract_prop(props, '생성일', 'date'),
                    'work_account': work_acc,
                })
            items = [it for it in items if it['deploy_url']]
        else:
            items = selected_items

        total = len(items)
        if total == 0:
            yield _sse({'type': 'complete', 'total': 0, 'results': [], 'message': '배포된 콘텐츠가 없습니다.'})
            return

        yield _sse({'type': 'progress', 'msg': f'총 {total}개 콘텐츠 성과 수집 시작', 'cur': 0, 'total': total})

        results = []
        for i, item in enumerate(items):
            kw = item.get('keyword', '')
            url = item.get('deploy_url', '')
            channel = item.get('channel', '')
            yield _sse({'type': 'progress', 'msg': f'[{i+1}/{total}] {kw or item.get("title","")} 수집 중...', 'cur': i+1, 'total': total})

            exp = await loop.run_in_executor(executor, _check_exposure_enhanced, kw, url, channel)
            stats = {'views': 0, 'comments': 0, 'likes': 0}
            if channel == '블로그' and 'blog.naver.com' in (url or ''):
                stats = await loop.run_in_executor(executor, _fetch_blog_stats, url)

            record = {
                'checked_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
                'keyword': kw,
                'channel': channel,
                'title': item.get('title', ''),
                'deploy_url': url,
                'deploy_date': item.get('deploy_date', ''),
                'exposure': exp['exposure'],
                'rank': exp['rank'],
                'section': exp['section'],
                'views': stats['views'],
                'comments': stats['comments'],
                'likes': stats['likes'],
            }
            results.append(record)
            yield _sse({'type': 'result', 'data': record, 'cur': i+1, 'total': total})
            await asyncio.sleep(1.5)

        # 히스토리 저장
        perf_data = _perf_load()
        perf_data['records'].extend(results)
        perf_data['last_checked'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
        perf_data['total_checks'] = perf_data.get('total_checks', 0) + 1
        _perf_save(perf_data)

        yield _sse({'type': 'complete', 'total': total, 'results': results, 'message': f'{total}개 콘텐츠 성과 수집 완료'})
      except Exception as e:
        print(f"[performance] collect error: {e}")
        yield _sse({'type': 'error', 'message': f'성과 수집 중 오류: {e}'})

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/history")
async def performance_history(keyword: str = '', channel: str = '', days: int = 30):
    """성과 히스토리 조회"""
    perf_data = _perf_load()
    records = perf_data.get('records', [])
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%S')
    filtered = [r for r in records if r.get('checked_at', '') >= cutoff]
    if keyword:
        filtered = [r for r in filtered if keyword in r.get('keyword', '')]
    if channel:
        filtered = [r for r in filtered if r.get('channel', '') == channel]
    return {'records': filtered, 'total': len(filtered), 'last_checked': perf_data.get('last_checked', '')}


@router.get("/dashboard-data")
async def performance_dashboard_data(days: int = 30):
    """대시보드 요약 집계"""
    perf_data = _perf_load()
    records = perf_data.get('records', [])
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%S')
    recent = [r for r in records if r.get('checked_at', '') >= cutoff]

    # 최신 체크 기준으로 키워드별 최신 레코드 추출
    latest_by_key = {}
    for r in recent:
        key = (r.get('keyword', ''), r.get('deploy_url', ''))
        if key not in latest_by_key or r.get('checked_at', '') > latest_by_key[key].get('checked_at', ''):
            latest_by_key[key] = r
    latest = list(latest_by_key.values())

    # 요약 카드
    total_content = len(latest)
    exposed = sum(1 for r in latest if r.get('exposure') == '노출중')
    ranks = [r['rank'] for r in latest if r.get('exposure') == '노출중' and r.get('rank', 0) > 0]
    avg_rank = round(sum(ranks) / len(ranks), 1) if ranks else 0
    total_views = sum(r.get('views', 0) for r in latest)

    # 채널별 노출률
    channel_stats = {}
    for r in latest:
        ch = r.get('channel', '기타')
        if ch not in channel_stats:
            channel_stats[ch] = {'total': 0, 'exposed': 0}
        channel_stats[ch]['total'] += 1
        if r.get('exposure') == '노출중':
            channel_stats[ch]['exposed'] += 1
    channel_rates = []
    for ch, st in sorted(channel_stats.items()):
        rate = round(st['exposed'] / st['total'] * 100) if st['total'] > 0 else 0
        channel_rates.append({'channel': ch, 'total': st['total'], 'exposed': st['exposed'], 'rate': rate})

    # 일별 노출 추이 (최근 N일)
    daily_trend = {}
    for r in recent:
        day = r.get('checked_at', '')[:10]
        if day not in daily_trend:
            daily_trend[day] = {'total': 0, 'exposed': 0}
        daily_trend[day]['total'] += 1
        if r.get('exposure') == '노출중':
            daily_trend[day]['exposed'] += 1
    trend = [{'date': d, 'total': v['total'], 'exposed': v['exposed']} for d, v in sorted(daily_trend.items())]

    # 순위 변동 (최신 vs 이전)
    rank_changes = []
    for r in latest:
        key = (r.get('keyword', ''), r.get('deploy_url', ''))
        # 이전 기록 찾기
        prev_records = [p for p in recent if (p.get('keyword', ''), p.get('deploy_url', '')) == key and p.get('checked_at', '') < r.get('checked_at', '')]
        prev_rank = 0
        if prev_records:
            prev_records.sort(key=lambda x: x.get('checked_at', ''), reverse=True)
            prev_rank = prev_records[0].get('rank', 0)
        change = prev_rank - r.get('rank', 0) if prev_rank > 0 and r.get('rank', 0) > 0 else 0
        rank_changes.append({
            'keyword': r.get('keyword', ''),
            'channel': r.get('channel', ''),
            'title': r.get('title', ''),
            'deploy_url': r.get('deploy_url', ''),
            'deploy_date': r.get('deploy_date', ''),
            'current_rank': r.get('rank', 0),
            'prev_rank': prev_rank,
            'change': change,
            'section': r.get('section', ''),
            'exposure': r.get('exposure', ''),
            'views': r.get('views', 0),
            'comments': r.get('comments', 0),
            'likes': r.get('likes', 0),
        })

    # 블로그 반응 TOP (조회수 순)
    blog_stats = [r for r in rank_changes if r.get('channel') == '블로그' and r.get('views', 0) > 0]
    blog_stats.sort(key=lambda x: x.get('views', 0), reverse=True)

    return {
        'summary': {
            'total_content': total_content,
            'exposed': exposed,
            'avg_rank': avg_rank,
            'total_views': total_views,
        },
        'channel_rates': channel_rates,
        'trend': trend,
        'rank_changes': rank_changes,
        'blog_stats': blog_stats[:20],
        'last_checked': perf_data.get('last_checked', ''),
        'total_checks': perf_data.get('total_checks', 0),
    }


# ── 자동 수집 스케줄러 ─────────────────────────────────────────────

async def _perf_auto_collect():
    """자동 성과 수집 (백그라운드)"""
    try:
        filter_obj = {'property': '발행_상태', 'select': {'equals': '발행완료'}}
        loop = asyncio.get_running_loop()
        pages = await loop.run_in_executor(executor, notion_query_all, CONTENT_DB_ID, filter_obj)
        items = []
        for page in pages:
            props = page.get('properties', {})
            kw_rels = extract_prop(props, '키워드', 'relation')
            kw_name = ''
            if kw_rels:
                try:
                    kw_r = req.get('https://api.notion.com/v1/pages/%s' % kw_rels[0],
                                   headers={'Authorization': 'Bearer %s' % NOTION_TOKEN, 'Notion-Version': '2022-06-28'}, timeout=10)
                    if kw_r.status_code == 200:
                        kw_props = kw_r.json().get('properties', {})
                        kw_name = extract_prop(kw_props, '키워드', 'title')
                except Exception:
                    pass
            url = extract_prop(props, '발행_URL', 'url')
            if url:
                items.append({
                    'keyword': kw_name,
                    'title': extract_prop(props, '제목', 'title'),
                    'channel': extract_prop(props, '채널', 'select'),
                    'deploy_url': url,
                    'deploy_date': extract_prop(props, '생성일', 'date'),
                })
        if items:
            loop = asyncio.get_running_loop()
            results = await loop.run_in_executor(executor, _run_performance_collect_sync, items)
            perf_data = _perf_load()
            perf_data['records'].extend(results)
            perf_data['last_checked'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
            perf_data['total_checks'] = perf_data.get('total_checks', 0) + 1
            _perf_save(perf_data)
            print(f"[perf-auto] {len(results)}개 콘텐츠 성과 수집 완료")
    except Exception as e:
        print(f"[perf-auto] error: {e}")


_PERF_JOB_ID = 'perf_auto_collect'


@router.post("/schedule")
async def performance_schedule_set(request: Request):
    """자동 수집 스케줄 설정"""
    global _perf_schedule
    from src.services.scheduler_service import scheduler

    body = await request.json()
    enabled = body.get('enabled', False)
    interval = body.get('interval_hours', 24)
    _perf_schedule = {"enabled": enabled, "interval_hours": interval}
    # 설정 저장
    with open(PERF_SCHEDULE_FILE, 'w') as f:
        json.dump(_perf_schedule, f)
    # APScheduler job 관리
    existing = scheduler.get_job(_PERF_JOB_ID)
    if existing:
        existing.remove()
    if enabled:
        scheduler.add_job(
            _perf_auto_collect, 'interval',
            id=_PERF_JOB_ID, hours=interval,
            replace_existing=True, misfire_grace_time=600,
        )
    return {'success': True, 'schedule': _perf_schedule}


@router.get("/schedule")
async def performance_schedule_get():
    """현재 스케줄 상태 조회"""
    from src.services.scheduler_service import scheduler
    job = scheduler.get_job(_PERF_JOB_ID)
    running = job is not None
    return {'schedule': _perf_schedule, 'running': running}


# ── startup 함수 (앱에서 호출) ─────────────────────────────────────

async def restore_performance_schedule():
    """서버 시작 시 스케줄 복원 — APScheduler interval job 등록."""
    global _perf_schedule
    from src.services.scheduler_service import scheduler

    if os.path.exists(PERF_SCHEDULE_FILE):
        try:
            with open(PERF_SCHEDULE_FILE, 'r') as f:
                _perf_schedule = json.load(f)
            if _perf_schedule.get("enabled", False):
                interval = _perf_schedule.get("interval_hours", 24)
                scheduler.add_job(
                    _perf_auto_collect, 'interval',
                    id=_PERF_JOB_ID, hours=interval,
                    replace_existing=True, misfire_grace_time=600,
                )
                print("[perf] auto-collect schedule restored (APScheduler)")
        except Exception:
            pass
