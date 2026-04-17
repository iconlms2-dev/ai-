"""Threads 레퍼런스 크롤러 — Playwright 기반.

- @username 크롤링: 비로그인도 허용 (공개 프로필)
- 키워드 검색: 로그인 쿠키 필수 (auth_required 즉시 반환)
- 파서: <script type="application/json"> JSON 파싱 우선, DOM fallback
- threads 전용 독립 공유 브라우저/컨텍스트 (cafe_crawler와 분리)

환경변수:
- THREADS_COOKIE_JSON: Instagram 로그인 쿠키 JSON (예: '{"sessionid":"...","ig_did":"..."}')
- THREADS_USER_AGENT: (선택) 쿠키 추출한 브라우저의 UA
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from typing import Optional

import requests as req
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# threads 전용 공유 브라우저 (cafe_crawler와 독립)
_browser_lock = threading.Lock()
_shared_playwright = None
_shared_browser = None
_shared_context = None
_shared_initialized = False

# 로그인 상태 캐시
_login_checked = False
_login_valid = False
_login_lock = threading.Lock()


# ── 응답 타입 ──

@dataclass
class CrawlResponse:
    """크롤링 결과 통일 응답.

    error 의미:
    - auth_required: 쿠키 없음 (키워드 검색에만 사용)
    - auth_blocked: 쿠키 있지만 네이버/인스타가 거부
    - not_found: 존재하지 않는 계정/글
    - network_error: 네트워크 오류
    - None: 성공 (posts 비어있어도 ok=True)
    """
    ok: bool
    error: Optional[str] = None
    posts: list = field(default_factory=list)


# ── 쿠키 로더 ──

def _get_threads_cookies() -> dict:
    """THREADS_COOKIE_JSON 파싱. 빈 dict면 비로그인."""
    raw = os.environ.get("THREADS_COOKIE_JSON", "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return {k: str(v) for k, v in data.items() if v}
    except json.JSONDecodeError as e:
        logger.warning("THREADS_COOKIE_JSON 파싱 실패: %s", e)
    return {}


def _get_user_agent() -> str:
    custom = os.environ.get("THREADS_USER_AGENT", "").strip()
    return custom or _DEFAULT_UA


def has_cookies() -> bool:
    """쿠키 설정 여부 (외부 체크용)"""
    return bool(_get_threads_cookies())


# ── 공유 브라우저 ──

def _get_shared_browser():
    """threads 전용 공유 브라우저. lock 내부에서 호출해야 함."""
    global _shared_playwright, _shared_browser, _shared_context, _shared_initialized

    if _shared_initialized and _shared_browser and _shared_context:
        try:
            _ = _shared_context.pages
            return _shared_browser, _shared_context
        except Exception:
            logger.info("[threads] 공유 브라우저 만료 — 재초기화")
            _shared_initialized = False
            # 기존 좀비 프로세스 먼저 정리 (playwright.stop 누락 방지)
            try:
                if _shared_context:
                    _shared_context.close()
            except Exception:
                pass
            try:
                if _shared_browser:
                    _shared_browser.close()
            except Exception:
                pass
            try:
                if _shared_playwright:
                    _shared_playwright.stop()
            except Exception:
                pass
            _shared_context = None
            _shared_browser = None
            _shared_playwright = None

    from playwright.sync_api import sync_playwright

    _shared_playwright = sync_playwright().start()
    try:
        _shared_browser = _shared_playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-first-run",
            ],
        )
        _shared_context = _shared_browser.new_context(
            user_agent=_get_user_agent(),
            viewport={"width": 1280, "height": 900},
            locale="ko-KR",
            timezone_id="Asia/Seoul",
        )

        # 스텔스 스크립트 주입
        try:
            from src.services.stealth import STEALTH_INIT_SCRIPT
            _shared_context.add_init_script(STEALTH_INIT_SCRIPT)
        except ImportError:
            pass

        # 쿠키 주입 (.threads.net, .instagram.com 두 도메인 모두)
        cookies = _get_threads_cookies()
        if cookies:
            from src.services.cafe_crawler import _cookies_for_playwright
            cookie_list = []
            cookie_list.extend(_cookies_for_playwright(cookies, domain=".threads.net"))
            cookie_list.extend(_cookies_for_playwright(cookies, domain=".instagram.com"))
            _shared_context.add_cookies(cookie_list)
            logger.info("[threads] 쿠키 %d개 × 2도메인 주입", len(cookies))

        _shared_initialized = True
        return _shared_browser, _shared_context
    except Exception:
        try:
            if _shared_playwright:
                _shared_playwright.stop()
        except Exception:
            pass
        _shared_playwright = None
        _shared_browser = None
        _shared_context = None
        raise


def shutdown_browser():
    """서버 종료 시 공유 브라우저 정리"""
    global _shared_playwright, _shared_browser, _shared_context, _shared_initialized
    with _browser_lock:
        try:
            if _shared_context:
                _shared_context.close()
        except Exception:
            pass
        try:
            if _shared_browser:
                _shared_browser.close()
        except Exception:
            pass
        try:
            if _shared_playwright:
                _shared_playwright.stop()
        except Exception:
            pass
        _shared_context = None
        _shared_browser = None
        _shared_playwright = None
        _shared_initialized = False


# ── 파싱 ──

def _normalize_count(s: str) -> int:
    """'1.2K', '500', '10만' 같은 표기를 정수로 변환"""
    if not s:
        return 0
    s = s.strip().replace(",", "")
    try:
        if s.endswith("K") or s.endswith("k"):
            return int(float(s[:-1]) * 1000)
        if s.endswith("M") or s.endswith("m"):
            return int(float(s[:-1]) * 1_000_000)
        if s.endswith("만"):
            return int(float(s[:-1]) * 10_000)
        if s.endswith("천"):
            return int(float(s[:-1]) * 1_000)
        # 순수 숫자만 추출
        m = re.search(r"[\d.]+", s)
        if m:
            return int(float(m.group(0)))
    except (ValueError, TypeError):
        pass
    return 0


def _extract_hashtags(text: str) -> list:
    return re.findall(r"#[\w가-힣]+", text)


def _calc_engagement(likes: int, replies: int, reposts: int) -> int:
    return likes + replies * 3 + reposts * 5


def _parse_post_json(html: str) -> list:
    """<script type="application/json"> 태그에서 Threads 게시글 데이터 추출.

    Threads는 React/Next.js 기반이라 초기 데이터가 JSON으로 임베드됨.
    여러 스크립트 태그를 순회하며 thread_items / containing_thread 패턴 탐색.
    """
    soup = BeautifulSoup(html, "html.parser")
    posts = []

    for script in soup.find_all("script", {"type": "application/json"}):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue

        # 재귀 탐색: thread_items 배열을 찾아서 post 추출
        _walk_json_for_posts(data, posts)

    # 중복 제거 (post id 기준)
    seen = set()
    unique = []
    for p in posts:
        pid = p.get("_post_id")
        if pid and pid not in seen:
            seen.add(pid)
            unique.append(p)
    return unique


def _walk_json_for_posts(obj, out: list, depth: int = 0):
    """JSON 재귀 순회하며 게시글 객체 추출"""
    if depth > 15:
        return
    if isinstance(obj, dict):
        # Threads의 게시글 객체 특징: caption + like_count + code(=URL segment)
        caption = obj.get("caption")
        code = obj.get("code")
        user = obj.get("user") or obj.get("owner") or {}
        if caption and isinstance(caption, dict) and code:
            text = caption.get("text", "") or ""
            if text:
                username = user.get("username", "") if isinstance(user, dict) else ""
                likes = obj.get("like_count", 0) or 0
                replies = (obj.get("text_post_app_info", {}) or {}).get("direct_reply_count", 0) or 0
                reposts = obj.get("repost_count", 0) or 0
                hashtags = _extract_hashtags(text)
                url = f"https://www.threads.net/@{username}/post/{code}" if username else f"https://www.threads.net/post/{code}"
                out.append({
                    "_post_id": code,
                    "text": text[:1500],
                    "likes": int(likes),
                    "replies": int(replies),
                    "reposts": int(reposts),
                    "hashtags": hashtags,
                    "url": url,
                    "username": f"@{username}" if username else "",
                    "engagement_score": _calc_engagement(int(likes), int(replies), int(reposts)),
                })
        # 자식 순회
        for v in obj.values():
            _walk_json_for_posts(v, out, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _walk_json_for_posts(item, out, depth + 1)


def _parse_post_dom(page) -> list:
    """DOM CSS 셀렉터 fallback. JSON 파싱 실패 시."""
    posts = []
    try:
        elements = page.query_selector_all('[data-pressable-container="true"]')
        for el in elements[:30]:
            try:
                text = el.inner_text().strip()
                if not text or len(text) < 10:
                    continue
                # 좋아요/답글 등 숫자 추출 (aria-label 기반)
                likes = replies = reposts = 0
                for btn in el.query_selector_all('[role="button"], [aria-label]'):
                    label = btn.get_attribute("aria-label") or ""
                    if "좋아요" in label or "Like" in label:
                        m = re.search(r"[\d.,KkMm만천]+", label)
                        if m:
                            likes = _normalize_count(m.group(0))
                    elif "답글" in label or "Reply" in label or "Repl" in label:
                        m = re.search(r"[\d.,KkMm만천]+", label)
                        if m:
                            replies = _normalize_count(m.group(0))
                    elif "리포스트" in label or "Repost" in label:
                        m = re.search(r"[\d.,KkMm만천]+", label)
                        if m:
                            reposts = _normalize_count(m.group(0))
                # 텍스트 본문 (수치 줄 제외)
                lines = [l for l in text.split("\n")
                         if l.strip() and not l.strip().startswith("좋아요")
                         and not l.strip().endswith("전")
                         and not re.match(r"^[\d.,KkMm만천\s]+$", l.strip())]
                content = "\n".join(lines)
                if content and len(content) >= 10:
                    hashtags = _extract_hashtags(content)
                    posts.append({
                        "text": content[:1500],
                        "likes": likes,
                        "replies": replies,
                        "reposts": reposts,
                        "hashtags": hashtags,
                        "url": "",
                        "username": "",
                        "engagement_score": _calc_engagement(likes, replies, reposts),
                    })
            except Exception as e:
                logger.debug("[threads] DOM element 파싱 실패: %s", str(e)[:100])
                continue
    except Exception as e:
        logger.warning("[threads] DOM 파싱 실패: %s", e)
    return posts


# ── 로그인 상태 감지 ──

def _is_login_required_page(html: str) -> bool:
    """로그인 강제 리다이렉트 페이지 감지"""
    indicators = [
        "Log in or sign up",
        "로그인하여",
        "로그인 또는 가입",
        "아이디와 비밀번호를 입력",
        '"IG_LoggedOut"',
    ]
    return any(ind in html for ind in indicators)


# ── 공개 API ──

def crawl_username(username: str, limit: int = 10) -> CrawlResponse:
    """@username 최근 게시글 크롤링 (비로그인도 허용).

    Args:
        username: @포함 여부 무관
        limit: 최대 게시글 수

    Returns:
        CrawlResponse. error는 not_found|auth_blocked|network_error|None
    """
    if not username:
        return CrawlResponse(ok=False, error="not_found", posts=[])

    clean = username.lstrip("@").strip()
    if not clean:
        return CrawlResponse(ok=False, error="not_found", posts=[])

    url = f"https://www.threads.net/@{clean}"

    with _browser_lock:
        page = None
        try:
            browser, context = _get_shared_browser()
            page = context.new_page()

            try:
                from playwright_stealth import stealth_sync
                stealth_sync(page)
            except ImportError:
                pass

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
            except Exception as e:
                logger.warning("[threads] goto 실패 (%s): %s", url, str(e)[:150])
                return CrawlResponse(ok=False, error="network_error", posts=[])

            page.wait_for_timeout(2500)

            # 404 / 존재하지 않는 계정
            body_text = page.content()
            if "죄송" in body_text and "페이지" in body_text:
                return CrawlResponse(ok=False, error="not_found", posts=[])
            if "Sorry, this page isn" in body_text:
                return CrawlResponse(ok=False, error="not_found", posts=[])

            # 스크롤로 추가 로드
            for _ in range(3):
                page.evaluate("window.scrollBy(0, 1200)")
                page.wait_for_timeout(1500)

            html = page.content()

            # Tier1: JSON 파싱
            posts = _parse_post_json(html)

            # Tier2: DOM fallback
            if not posts:
                posts = _parse_post_dom(page)

            # 게시글이 없는데 로그인 요구 페이지면 auth_blocked
            if not posts and _is_login_required_page(html):
                return CrawlResponse(ok=False, error="auth_blocked", posts=[])

            # username 보정 (JSON 파서가 못 찾은 경우)
            for p in posts:
                if not p.get("username"):
                    p["username"] = f"@{clean}"

            # engagement 내림차순 정렬 후 limit
            posts.sort(key=lambda p: p.get("engagement_score", 0), reverse=True)
            return CrawlResponse(ok=True, error=None, posts=posts[:limit])

        except Exception as e:
            logger.exception("[threads] crawl_username 예외")
            return CrawlResponse(ok=False, error="network_error", posts=[])
        finally:
            if page:
                try:
                    page.close()
                except Exception:
                    pass


def crawl_keyword(keyword: str, limit: int = 10) -> CrawlResponse:
    """키워드 검색 크롤링. **쿠키 필수**.

    쿠키 없으면 auth_required 즉시 반환 (API 레벨에서도 사전 차단 권장).
    """
    if not keyword or not keyword.strip():
        return CrawlResponse(ok=False, error="not_found", posts=[])

    if not has_cookies():
        return CrawlResponse(ok=False, error="auth_required", posts=[])

    kw = keyword.strip()
    from urllib.parse import quote
    url = f"https://www.threads.net/search?q={quote(kw)}&serp_type=default"

    with _browser_lock:
        page = None
        try:
            browser, context = _get_shared_browser()
            page = context.new_page()

            try:
                from playwright_stealth import stealth_sync
                stealth_sync(page)
            except ImportError:
                pass

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
            except Exception as e:
                logger.warning("[threads] 키워드 검색 goto 실패 (%s): %s", url, str(e)[:150])
                return CrawlResponse(ok=False, error="network_error", posts=[])

            page.wait_for_timeout(3000)

            html = page.content()
            if _is_login_required_page(html):
                return CrawlResponse(ok=False, error="auth_blocked", posts=[])

            # 스크롤 로드
            for _ in range(4):
                page.evaluate("window.scrollBy(0, 1500)")
                page.wait_for_timeout(1500)

            html = page.content()
            posts = _parse_post_json(html)
            if not posts:
                posts = _parse_post_dom(page)

            if not posts and _is_login_required_page(html):
                return CrawlResponse(ok=False, error="auth_blocked", posts=[])

            posts.sort(key=lambda p: p.get("engagement_score", 0), reverse=True)
            return CrawlResponse(ok=True, error=None, posts=posts[:limit])

        except Exception:
            logger.exception("[threads] crawl_keyword 예외")
            return CrawlResponse(ok=False, error="network_error", posts=[])
        finally:
            if page:
                try:
                    page.close()
                except Exception:
                    pass
