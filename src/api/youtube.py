"""YouTube API 라우터 — 영상 검색, 댓글 생성, 자동게시(CommentBoost), SMM, IP 변경"""
import os
import re
import json
import time
import asyncio
import threading
from datetime import datetime

import requests as req
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from src.services.config import (
    executor, BASE_DIR, CONTENT_DB_ID, NOTION_TOKEN, GEMINI_API_KEY,
)
from src.services.common import error_response
from src.services.ai_client import call_claude
from src.services.review_service import review_and_save
from src.services.notion_client import notion_headers

router = APIRouter()

# ───────────────────────────── 자동게시 상태 ─────────────────────────────

_yt_autopost_state = {
    "running": False,
    "current_task": None,
    "progress": 0,
    "total": 0,
    "logs": [],
    "results": {"success": 0, "fail": 0, "skip": 0},
}
_yt_autopost_lock = threading.Lock()

# ───────────────────────────── 모듈 임포트 (src/) ─────────────────────────────

try:
    from src.youtube_bot import YouTubeBot
    from src.fingerprint import FingerprintManager
    from src.safety_rules import SafetyRules
    from src.smm_client import SMMClient
    from src.comment_tracker import CommentTracker
    _yt_modules_available = True
except ImportError as _ie:
    print(f"[CommentBoost] 모듈 임포트 실패: {_ie}")
    _yt_modules_available = False

_yt_safety_rules = SafetyRules() if _yt_modules_available else None
_yt_comment_tracker = CommentTracker() if _yt_modules_available else None
_yt_fingerprint_mgr = FingerprintManager() if _yt_modules_available else None
_yt_smm_client = SMMClient() if _yt_modules_available else None

# ───────────────────────────── 계정 관리 헬퍼 ─────────────────────────────

_YT_ACCOUNTS_FILE = os.path.join(BASE_DIR, 'config', 'yt_accounts.json')
os.makedirs(os.path.dirname(_YT_ACCOUNTS_FILE), exist_ok=True)


def _load_yt_accounts():
    if os.path.exists(_YT_ACCOUNTS_FILE):
        try:
            return json.loads(open(_YT_ACCOUNTS_FILE, encoding='utf-8').read())
        except (json.JSONDecodeError, OSError) as e:
            print(f"[yt_accounts] 로드 오류: {e}")
    return []


def _save_yt_accounts(accounts):
    tmp = _YT_ACCOUNTS_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(accounts, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _YT_ACCOUNTS_FILE)


def _yt_add_log(msg, level="info"):
    import datetime as _dt
    with _yt_autopost_lock:
        _yt_autopost_state["logs"].append({
            "time": _dt.datetime.now().strftime("%H:%M:%S"),
            "msg": msg, "level": level,
        })
        if len(_yt_autopost_state["logs"]) > 200:
            _yt_autopost_state["logs"] = _yt_autopost_state["logs"][-100:]


def _yt_update_state(**kwargs):
    """thread-safe 상태 업데이트"""
    with _yt_autopost_lock:
        _yt_autopost_state.update(kwargs)


def _yt_get_state(*keys):
    """thread-safe 상태 읽기"""
    with _yt_autopost_lock:
        if len(keys) == 1:
            return _yt_autopost_state.get(keys[0])
        return {k: _yt_autopost_state.get(k) for k in keys}


# ───────────────────────────── 프롬프트 빌더 ─────────────────────────────

def _build_youtube_summary_prompt(video_title, script, description):
    """1단계: 영상 요약 (temperature 0.3 — 정확하게)"""
    context = script if script else description if description else video_title
    system = """너는 유튜브 영상의 핵심 내용을 요약하는 AI야.
반드시 한국어로 답변하며, 불필요한 내용은 제외해야 해."""
    user = """영상에 대한 정보는 아래 두 가지를 참고해:
1) 영상 제목: %s
2) 영상 소개(스크립트 또는 더보기): %s

위의 두 가지 정보를 함께 분석하여 영상의 주요 내용을 핵심만 500자 내외로 요약해줘!""" % (video_title, context[:3000])
    return system, user


def _build_youtube_comment_prompt(video_title, description, brand_keyword):
    """유튜브 바이럴 댓글 3단 시나리오 생성 (temperature 0.9 — 창의적으로)"""
    system = """너는 유튜브 영상에 달리는 바이럴 댓글을 작성하는 마케팅 전문가다.

주어진 영상 제목과 더보기 내용을 참고하여,
실제 시청자가 남긴 것처럼 보이는 바이럴 댓글 3단 시나리오를 만들어라.

[3단 댓글 시나리오 구조]

1단계 — 밑밥 (공감형 질문):
- 영상 내용에 공감하면서, 나만의 키워드와 관련된 질문을 던지는 댓글
- 진짜 시청자가 궁금해서 남긴 것처럼 자연스럽게

2단계 — 해결사 (자연스러운 키워드 삽입):
- 1단계 댓글에 대한 답변 형태로, 나만의 키워드를 자연스럽게 추천하는 댓글
- 경험 기반으로 "나는 이거 써봤는데~" 식의 톤

3단계 — 쐐기 (구매 행동 유도):
- 2단계를 보고 "나도 해봐야겠다" 식으로 반응하는 댓글
- 구매 의향을 간접적으로 드러내는 톤

[작성 규칙]
- 광고 티 절대 금지
- 브랜드명 직접 언급 금지
- 실제 유튜브 댓글처럼 짧고 자연스러운 구어체
- 각 단계별 댓글 1개씩, 총 3개 출력

[출력 형식]
댓글1 (밑밥):
(내용)

댓글2 (해결사):
(내용)

댓글3 (쐐기):
(내용)"""
    user = """[영상 제목]
%s

[더보기 내용]
%s

[나만의 키워드]
%s""" % (video_title, description, brand_keyword)
    return system, user


# ───────────────────────────── YOUTUBE VIDEO SEARCH ─────────────────────────

@router.post("/search-videos")
async def youtube_search_videos(request: Request):
    """키워드로 YouTube 영상 검색 (yt-dlp)"""
    body = await request.json()
    keyword = body.get('keyword', '').strip()
    count = min(int(body.get('count', 50)), 100)
    if not keyword:
        return JSONResponse({'error': '키워드를 입력하세요'}, 400)

    def _search():
        try:
            import yt_dlp
            ydl_opts = {
                'quiet': True,
                'extract_flat': True,
                'force_generic_extractor': False,
            }
            videos = []
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                result = ydl.extract_info(f'ytsearch{count}:{keyword}', download=False)
                for entry in result.get('entries', []):
                    if not entry:
                        continue
                    vid = {
                        'id': entry.get('id', ''),
                        'title': entry.get('title', ''),
                        'url': entry.get('url', f"https://www.youtube.com/watch?v={entry.get('id','')}"),
                        'channel': entry.get('channel', entry.get('uploader', '')),
                        'duration': entry.get('duration'),
                        'view_count': entry.get('view_count'),
                    }
                    videos.append(vid)
            return {'videos': videos, 'keyword': keyword, 'total': len(videos)}
        except ImportError:
            return {'error': 'yt-dlp가 설치되지 않았습니다. pip install yt-dlp'}
        except Exception as e:
            return {'error': str(e)}

    result = await asyncio.get_running_loop().run_in_executor(executor, _search)
    if 'error' in result:
        return JSONResponse(result, 500)
    return result


@router.post("/fetch-video-details")
async def youtube_fetch_video_details(request: Request):
    """영상 URL 목록에서 제목/설명을 일괄 크롤링"""
    body = await request.json()
    urls = body.get('urls', [])
    if not urls:
        return JSONResponse({'error': 'URL 목록이 비어있습니다'}, 400)

    def _fetch_all():
        results = []
        headers = {'User-Agent': 'Mozilla/5.0', 'Accept-Language': 'ko-KR,ko;q=0.9'}
        for url in urls[:50]:
            vid = {'url': url, 'title': '', 'description': ''}
            try:
                r = req.get(url, headers=headers, timeout=10)
                title_match = re.search(r'<title>(.*?)</title>', r.text)
                if title_match:
                    vid['title'] = title_match.group(1).replace(' - YouTube', '').strip()
                desc_match = re.search(r'"shortDescription":"(.*?)"', r.text)
                if desc_match:
                    vid['description'] = desc_match.group(1).replace('\\n', '\n').strip()[:2000]
            except Exception:
                pass
            results.append(vid)
        return results

    results = await asyncio.get_running_loop().run_in_executor(executor, _fetch_all)
    return {'videos': results}


# ───────────────────────────── YOUTUBE COMMENTS ─────────────────────────────

@router.post("/fetch-info")
async def youtube_fetch_info(request: Request):
    """YouTube URL에서 제목/설명/자막 크롤링"""
    body = await request.json()
    url = body.get('url', '')
    if not url:
        return JSONResponse({'error': 'URL 필요'}, 400)
    result = {'title': '', 'description': '', 'transcript': ''}
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = req.get(url, headers=headers, timeout=10)
        # 제목 추출
        title_match = re.search(r'<title>(.*?)</title>', r.text)
        if title_match:
            result['title'] = title_match.group(1).replace(' - YouTube', '').strip()
        # 설명 추출
        desc_match = re.search(r'"shortDescription":"(.*?)"', r.text)
        if desc_match:
            result['description'] = desc_match.group(1).replace('\\n', '\n').strip()[:2000]
    except Exception:
        pass
    return result


@router.post("/generate")
async def youtube_generate(request: Request):
    """유튜브 댓글 생성 (SSE)"""
    body = await request.json()
    videos = body.get('videos', [])
    product_name = body.get('product_name', '')
    brand_keyword = body.get('brand_keyword', product_name)

    def _sse(obj):
        return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"

    async def generate():
      try:
        loop = asyncio.get_running_loop()
        total = len(videos)
        for i, v in enumerate(videos):
            title = v.get('title', '')
            description = v.get('description', '')
            # 1단계: 영상 요약 (temperature 0.3 — 참고용)
            yield _sse({'type': 'progress', 'msg': '[%d/%d] %s — 영상 요약 중...' % (i+1, total, title[:30]), 'cur': i, 'total': total})
            sum_sys, sum_usr = _build_youtube_summary_prompt(title, v.get('script', ''), description)
            summary = await loop.run_in_executor(executor, call_claude, sum_sys, sum_usr, 0.3, 1024)
            summary = summary.strip()
            # 2단계: 3단 시나리오 댓글 생성 (temperature 0.9 — 창의적으로)
            yield _sse({'type': 'progress', 'msg': '[%d/%d] %s — 댓글 3단 시나리오 생성 중...' % (i+1, total, title[:30]), 'cur': i, 'total': total})
            cmt_sys, cmt_usr = _build_youtube_comment_prompt(title, description, brand_keyword)
            comment = await loop.run_in_executor(executor, call_claude, cmt_sys, cmt_usr, 0.9, 1024)
            comment = comment.strip()
            result = {
                'title': title, 'link': v.get('link', ''),
                'script': v.get('script', ''), 'description': description,
                'summary': summary, 'comment': comment,
                'video_title': title,
            }

            # ── 검수 단계 ──
            yield _sse({'type': 'progress', 'msg': f'[{i+1}/{total}] {title[:30]} — 검수 중...', 'cur': i, 'total': total})
            review_result = await loop.run_in_executor(
                executor, review_and_save, "youtube", result, "",
            )
            for ev in review_result.get("events", []):
                yield _sse(ev)
            result['review_status'] = review_result["status"]
            result['review_passed'] = review_result["passed"]

            yield _sse({'type': 'result', 'data': result, 'cur': i+1, 'total': total})
        yield _sse({'type': 'complete', 'total': total})
      except Exception as e:
        print(f"[youtube_generate] 에러: {e}")
        yield _sse({'type': 'error', 'message': f'유튜브 댓글 생성 중 오류: {e}'})

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/save-notion")
async def youtube_save_notion(request: Request):
    """유튜브 댓글 노션 저장"""
    body = await request.json()
    headers_n = notion_headers()
    props = {
        '제목': {'title': [{'text': {'content': body.get('title', '')}}]},
        '채널': {'select': {'name': '유튜브'}},
        '생산 상태': {'select': {'name': '승인됨' if body.get('review_status') == 'approved' else '초안'}},
        '발행_상태': {'select': {'name': '미발행'}},
    }
    if body.get('comment'):
        props['본문'] = {'rich_text': [{'text': {'content': body['comment'][:2000]}}]}

    payload = {'parent': {'database_id': CONTENT_DB_ID}, 'properties': props}
    children = []
    if body.get('comment'):
        children.append({'object': 'block', 'type': 'paragraph',
            'paragraph': {'rich_text': [{'type': 'text', 'text': {'content': body['comment'][:2000]}}]}})
    if children:
        payload['children'] = children

    try:
        r = req.post('https://api.notion.com/v1/pages', headers=headers_n, json=payload, timeout=15)
        return {'success': r.status_code == 200, 'error': '' if r.status_code == 200 else r.text[:300]}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ──────────────────── YOUTUBE AUTO-POST (CommentBoost 통합) ──────────────────

@router.get("/accounts")
async def yt_get_accounts():
    """YouTube 계정 목록 조회"""
    accounts = _load_yt_accounts()
    result = []
    for acc in accounts:
        label = acc.get("label", acc.get("email", "unknown"))
        status = _yt_safety_rules.get_account_status(label) if _yt_safety_rules else {}
        result.append({**acc, "password": "***", **status})
    return {"accounts": result}


@router.post("/accounts")
async def yt_add_account(request: Request):
    """YouTube 계정 추가"""
    body = await request.json()
    email = body.get("email", "").strip()
    label = body.get("label", email)
    if not email:
        return JSONResponse({"error": "이메일 필요"}, 400)

    accounts = _load_yt_accounts()
    for acc in accounts:
        if acc.get("email") == email:
            return JSONResponse({"error": "이미 등록된 계정"}, 400)

    accounts.append({
        "email": email, "label": label,
        "password": body.get("password", ""),
        "proxy": body.get("proxy", ""),
        "adspower_profile_id": body.get("adspower_profile_id", ""),
        "active": True,
        "status": "활성",  # 활성/휴식/정지/폐기
        "aging_status": body.get("aging_status", "완료"),  # 진행중/완료
        "created_at": datetime.now().strftime("%Y-%m-%d"),
        "last_used_at": None,
        "total_comments": 0,
        "notes": body.get("notes", ""),
    })
    _save_yt_accounts(accounts)
    return {"success": True}


@router.delete("/accounts/{email}")
async def yt_delete_account(email: str):
    """YouTube 계정 삭제"""
    accounts = _load_yt_accounts()
    accounts = [a for a in accounts if a.get("email") != email]
    _save_yt_accounts(accounts)
    return {"success": True}


@router.patch("/accounts/{email}")
async def yt_update_account(email: str, request: Request):
    """YouTube 계정 정보 수정 (상태, 메모, 프록시 등)"""
    body = await request.json()
    accounts = _load_yt_accounts()
    for acc in accounts:
        if acc.get("email") == email:
            for key in ["status", "aging_status", "notes", "proxy", "adspower_profile_id", "active"]:
                if key in body:
                    acc[key] = body[key]
            _save_yt_accounts(accounts)
            return {"success": True}
    return JSONResponse({"error": "계정을 찾을 수 없습니다."}, 404)


@router.post("/test-login")
async def yt_test_login(request: Request):
    """YouTube 계정 로그인 테스트"""
    if not _yt_modules_available:
        return JSONResponse({"error": "playwright 모듈 미설치. pip install playwright && playwright install chromium"}, 500)

    body = await request.json()
    email = body.get("email", "")
    accounts = _load_yt_accounts()
    account = next((a for a in accounts if a.get("email") == email), None)
    if not account:
        return JSONResponse({"error": "계정을 찾을 수 없습니다."}, 404)

    label = account.get("label", email)

    def _test():
        bot = YouTubeBot(account_label=label, fingerprint_manager=_yt_fingerprint_mgr)
        bot.headless = True
        try:
            bot.start_browser(account)
            logged_in = bot.login_youtube(account)
            return {"logged_in": logged_in, "label": label}
        except Exception as e:
            return {"logged_in": False, "error": str(e)}
        finally:
            bot.close()

    result = await asyncio.get_running_loop().run_in_executor(executor, _test)
    return result


@router.post("/manual-login")
async def yt_manual_login(request: Request):
    """YouTube 수동 로그인 (브라우저 열기)"""
    if not _yt_modules_available:
        return JSONResponse({"error": "playwright 모듈 미설치"}, 500)

    body = await request.json()
    email = body.get("email", "")
    accounts = _load_yt_accounts()
    account = next((a for a in accounts if a.get("email") == email), None)
    if not account:
        return JSONResponse({"error": "계정을 찾을 수 없습니다."}, 404)

    label = account.get("label", email)

    def _login():
        bot = YouTubeBot(account_label=label, fingerprint_manager=_yt_fingerprint_mgr)
        bot.headless = False  # 화면 보이기 필수
        try:
            bot.start_browser(account)
            success = bot.manual_login(timeout_sec=120)
            return {"success": success, "label": label}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            bot.close()

    result = await asyncio.get_running_loop().run_in_executor(executor, _login)
    return result


@router.post("/auto-post")
async def yt_auto_post(request: Request):
    """YouTube 댓글 자동 게시 시작"""
    if not _yt_modules_available:
        return JSONResponse({"error": "playwright 모듈 미설치"}, 500)

    if _yt_get_state("running"):
        return JSONResponse({"error": "이미 실행 중입니다."}, 400)

    body = await request.json()
    tasks = body.get("tasks", [])  # [{youtube_url, comment_text, page_id?}, ...]
    headless = body.get("headless", True)

    if not tasks:
        return JSONResponse({"error": "작업 목록이 비어있습니다."}, 400)

    accounts = _load_yt_accounts()
    active_accounts = [a for a in accounts if a.get("active", True)]
    if not active_accounts:
        return JSONResponse({"error": "활성 계정이 없습니다."}, 400)

    def _run():
        with _yt_autopost_lock:
            _yt_autopost_state.update({
                "running": True, "progress": 0, "total": len(tasks),
                "logs": [], "results": {"success": 0, "fail": 0, "skip": 0},
                "current_task": None,
            })

        account_idx = 0
        bot = None
        current_label = ""

        try:
            for i, task in enumerate(tasks):
                if not _yt_get_state("running"):
                    _yt_add_log("사용자에 의해 중지됨", "warning")
                    break

                youtube_url = task.get("youtube_url", "")
                comment_text = task.get("comment_text", "")
                url_short = youtube_url[:50] + "..." if len(youtube_url) > 50 else youtube_url

                _yt_update_state(progress=i, current_task=f"[{i+1}/{len(tasks)}] {url_short}")

                # 계정 라운드로빈
                account = active_accounts[account_idx % len(active_accounts)]
                label = account.get("label", account.get("email", "unknown"))

                # 계정 변경 시 브라우저 재시작
                if label != current_label:
                    if bot:
                        bot.close()
                    current_label = label
                    antidetect = body.get("antidetect_mode", "stealth")
                    bot = YouTubeBot(
                        account_label=label,
                        fingerprint_manager=_yt_fingerprint_mgr,
                        antidetect_mode=antidetect,
                    )
                    bot.headless = headless
                    try:
                        bot.start_browser(account)
                        logged_in = bot.login_youtube(account)
                    except Exception as bot_err:
                        _yt_add_log(f"[{label}] 브라우저 시작 실패: {bot_err}", "error")
                        try:
                            bot.close()
                        except Exception:
                            pass
                        bot = None
                        with _yt_autopost_lock:
                            _yt_autopost_state["results"]["fail"] += 1
                        account_idx += 1
                        continue
                    if not logged_in:
                        _yt_add_log(f"[{label}] 로그인 실패 — 건너뜀", "error")
                        try:
                            bot.close()
                        except Exception:
                            pass
                        bot = None
                        with _yt_autopost_lock:
                            _yt_autopost_state["results"]["fail"] += 1
                        account_idx += 1
                        continue

                # 안전 규칙 검사
                passed, reason = _yt_safety_rules.check_all_rules(
                    current_label, youtube_url, comment_text, skip_interval=False
                )
                if not passed:
                    _yt_add_log(f"[건너뜀] {reason}", "warning")
                    with _yt_autopost_lock:
                        _yt_autopost_state["results"]["skip"] += 1
                    continue

                # 인간형 딜레이
                if i > 0:
                    delay_info = _yt_safety_rules.get_human_delay("comment")
                    _yt_add_log(f"🧑 {delay_info['description']}", "info")
                    time.sleep(delay_info["delay_sec"])

                # 댓글 작성
                _yt_add_log(f"[댓글 작성 중] {url_short}", "info")
                comment_url = bot.post_comment(youtube_url, comment_text)

                if comment_url:
                    _yt_autopost_state["results"]["success"] += 1
                    _yt_safety_rules.record_comment(current_label, youtube_url, comment_text)
                    _yt_add_log(f"[성공] {comment_url}", "success")

                    # 계정 사용 기록 업데이트
                    try:
                        _accs = _load_yt_accounts()
                        for _a in _accs:
                            if _a.get("label") == current_label or _a.get("email") == account.get("email"):
                                _a["last_used_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                                _a["total_comments"] = _a.get("total_comments", 0) + 1
                                break
                        _save_yt_accounts(_accs)
                    except Exception:
                        pass

                    # 트래킹 등록
                    if _yt_comment_tracker:
                        _yt_comment_tracker.register_comment(
                            comment_url=comment_url,
                            video_url=youtube_url,
                            comment_text=comment_text,
                            account_label=current_label,
                        )

                    # SMM 좋아요 주문 대기 등록 (auto_like 모드)
                    if body.get("auto_like") and _yt_smm_client and _yt_smm_client.enabled and comment_url:
                        like_qty = body.get("like_quantity", _yt_smm_client.default_quantity)
                        with _yt_autopost_lock:
                            _yt_autopost_state.setdefault("pending_likes", []).append({
                                "comment_url": comment_url,
                                "quantity": like_qty,
                                "video_title": url_short,
                                "status": "pending_approval",
                            })
                        _yt_add_log(f"👍 좋아요 주문 대기: {like_qty}개 ({url_short})", "info")

                    # Notion 업데이트 (page_id가 있으면)
                    page_id = task.get("page_id")
                    if page_id and NOTION_TOKEN:
                        try:
                            _headers_n = notion_headers()
                            _payload = {"properties": {
                                "댓글 url": {"url": comment_url},
                                "상태": {"select": {"name": "댓글완료"}},
                            }}
                            req.patch(f'https://api.notion.com/v1/pages/{page_id}',
                                     headers=_headers_n, json=_payload, timeout=15)
                        except Exception:
                            pass
                else:
                    with _yt_autopost_lock:
                        _yt_autopost_state["results"]["fail"] += 1
                    _yt_add_log(f"[실패] 댓글 작성 실패", "error")

                with _yt_autopost_lock:
                    _yt_autopost_state["progress"] = i + 1

        except Exception as e:
            _yt_add_log(f"[에러] {str(e)}", "error")
        finally:
            if bot:
                bot.close()
            _yt_update_state(running=False, current_task=None)
            _yt_add_log("자동 게시 완료", "info")

    threading.Thread(target=_run, daemon=True).start()
    return {"success": True, "total": len(tasks)}


@router.get("/auto-post/status")
async def yt_auto_post_status():
    """자동 게시 진행 상태"""
    with _yt_autopost_lock:
        return {
            "running": _yt_autopost_state["running"],
            "progress": _yt_autopost_state["progress"],
            "total": _yt_autopost_state["total"],
            "current_task": _yt_autopost_state["current_task"],
            "results": dict(_yt_autopost_state["results"]),
            "logs": list(_yt_autopost_state["logs"][-50:]),
        }


@router.post("/auto-post/stop")
async def yt_auto_post_stop():
    """자동 게시 중지"""
    _yt_update_state(running=False)
    return {"success": True}


@router.get("/tracking/summary")
async def yt_tracking_summary():
    """댓글 트래킹 요약"""
    if not _yt_comment_tracker:
        return {"total": 0, "active": 0, "hidden": 0, "deleted": 0, "total_likes": 0}
    return _yt_comment_tracker.get_summary()


@router.get("/safety/status")
async def yt_safety_status():
    """안전 규칙 상태 (전체 계정)"""
    if not _yt_safety_rules:
        return {"today_total": 0, "accounts": []}

    accounts = _load_yt_accounts()
    statuses = []
    for acc in accounts:
        label = acc.get("label", acc.get("email", "unknown"))
        statuses.append(_yt_safety_rules.get_account_status(label))

    return {
        "today_total": _yt_safety_rules.get_today_total_success(),
        "accounts": statuses,
    }


@router.post("/safety/allow-video")
async def yt_safety_allow_video(request: Request):
    """동일 영상 차단 수동 해제 (재작업 허용)"""
    if not _yt_safety_rules:
        return JSONResponse({"error": "안전 규칙 모듈 미로드"}, 500)
    body = await request.json()
    url = body.get("youtube_url", "")
    if not url:
        return JSONResponse({"error": "YouTube URL 필요"}, 400)
    ok = _yt_safety_rules.allow_video(url)
    return {"success": ok, "msg": "해당 영상 재작업이 허용되었습니다." if ok else "영상 ID 추출 실패"}


@router.get("/safety/posted-videos")
async def yt_safety_posted_videos():
    """댓글이 작성된 영상 목록"""
    if not _yt_safety_rules:
        return {"videos": []}
    return {"videos": _yt_safety_rules.get_posted_videos()}


# ───────────────────────────── SMM (좋아요 구매) ─────────────────────────────

@router.get("/smm/status")
async def yt_smm_status():
    """SMM 패널 상태 (활성화 여부 + 잔액)"""
    if not _yt_smm_client:
        return {"enabled": False, "error": "SMM 모듈 미로드"}
    if not _yt_smm_client.enabled:
        return {"enabled": False, "balance": None, "msg": "SMM_ENABLED=false"}
    balance = await asyncio.get_running_loop().run_in_executor(executor, _yt_smm_client.get_balance)
    return {"enabled": True, "balance": balance}


@router.get("/smm/services")
async def yt_smm_services():
    """SMM 서비스 목록 조회"""
    if not _yt_smm_client or not _yt_smm_client.enabled:
        return {"services": [], "error": "SMM 비활성화"}
    services = await asyncio.get_running_loop().run_in_executor(executor, _yt_smm_client.get_services)
    # YouTube 관련만 필터
    yt_services = [s for s in services if 'youtube' in str(s.get('name', '')).lower() or 'yt' in str(s.get('name', '')).lower()]
    return {"services": yt_services, "all_count": len(services)}


@router.post("/smm/order")
async def yt_smm_order(request: Request):
    """좋아요 수동 주문 (사용자 승인 후 호출)"""
    if not _yt_smm_client or not _yt_smm_client.enabled:
        return JSONResponse({"error": "SMM 비활성화"}, 400)
    body = await request.json()
    comment_url = body.get("comment_url", "")
    quantity = body.get("quantity", _yt_smm_client.default_quantity)
    service_id = body.get("service_id", None)
    if not comment_url:
        return JSONResponse({"error": "댓글 URL 필요"}, 400)
    result = await asyncio.get_running_loop().run_in_executor(
        executor, lambda: _yt_smm_client.order_likes(comment_url, quantity, service_id)
    )
    return result


@router.get("/smm/pending-likes")
async def yt_smm_pending_likes():
    """승인 대기 중인 좋아요 주문 목록"""
    return {"pending": _yt_autopost_state.get("pending_likes", [])}


@router.post("/smm/approve-likes")
async def yt_smm_approve_likes(request: Request):
    """사용자가 승인한 좋아요 주문 일괄 실행"""
    if not _yt_smm_client or not _yt_smm_client.enabled:
        return JSONResponse({"error": "SMM 비활성화"}, 400)

    pending = _yt_autopost_state.get("pending_likes", [])
    approved = [p for p in pending if p.get("status") == "pending_approval"]
    if not approved:
        return {"success": 0, "msg": "승인 대기 중인 주문 없음"}

    results = []
    for item in approved:
        result = await asyncio.get_running_loop().run_in_executor(
            executor,
            lambda url=item["comment_url"], qty=item["quantity"]: _yt_smm_client.order_likes(url, qty)
        )
        item["status"] = "ordered" if "order" in result else "error"
        item["order_id"] = result.get("order")
        item["error"] = result.get("error")
        results.append(result)

    success = sum(1 for r in results if "order" in r)
    return {"success": success, "total": len(approved), "results": results}


@router.post("/smm/clear-pending")
async def yt_smm_clear_pending():
    """대기 목록 초기화"""
    with _yt_autopost_lock:
        _yt_autopost_state["pending_likes"] = []
    return {"success": True}


@router.post("/smm/check-orders")
async def yt_smm_check_orders(request: Request):
    """주문 상태 확인"""
    if not _yt_smm_client:
        return JSONResponse({"error": "SMM 모듈 미로드"}, 400)
    body = await request.json()
    order_ids = body.get("order_ids", [])
    if not order_ids:
        return {"orders": {}}
    result = await asyncio.get_running_loop().run_in_executor(
        executor, lambda: _yt_smm_client.check_orders(order_ids)
    )
    return {"orders": result}


# ───────────────────────────── IP 변경 (아이폰 테더링) ─────────────────────────────

@router.post("/ip-change")
async def yt_ip_change():
    """Wi-Fi 토글로 아이폰 테더링 IP 변경 (macOS)"""
    import subprocess
    import platform
    if platform.system() != "Darwin":
        return JSONResponse({"error": "macOS에서만 지원"}, 400)

    def _toggle_wifi():
        try:
            # Wi-Fi 끄기
            subprocess.run(["networksetup", "-setairportpower", "en0", "off"], check=True, timeout=10)
            time.sleep(3)
            # Wi-Fi 켜기
            subprocess.run(["networksetup", "-setairportpower", "en0", "on"], check=True, timeout=10)
            time.sleep(5)
            # 새 IP 확인
            result = subprocess.run(["curl", "-s", "https://api.ipify.org"], capture_output=True, text=True, timeout=15)
            new_ip = result.stdout.strip()
            return {"success": True, "new_ip": new_ip}
        except Exception as e:
            return {"success": False, "error": str(e)}

    result = await asyncio.get_running_loop().run_in_executor(executor, _toggle_wifi)
    return result


@router.get("/ip-check")
async def yt_ip_check():
    """현재 공인 IP 확인"""
    import subprocess
    try:
        result = await asyncio.get_running_loop().run_in_executor(
            executor,
            lambda: subprocess.run(["curl", "-s", "https://api.ipify.org"], capture_output=True, text=True, timeout=10)
        )
        return {"ip": result.stdout.strip()}
    except Exception as e:
        return {"ip": None, "error": str(e)}


# ───────────────────────────── 모듈 상태 ─────────────────────────────

@router.get("/autopost/modules-status")
async def yt_modules_status_v2():
    """CommentBoost 모듈 + Stealth 로드 상태"""
    stealth_available = False
    try:
        from src.youtube_bot import has_stealth
        stealth_available = has_stealth()
    except Exception:
        pass
    return {
        "available": _yt_modules_available,
        "stealth": stealth_available,
        "smm_enabled": _yt_smm_client.enabled if _yt_smm_client else False,
    }
