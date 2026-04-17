"""네이버 카페 본문 크롤링 — 3-Tier 폴백 시스템 (v3)

Tier 1: 쿠키 인증 requests.Session + 브라우저 헤더 (~0.5초)
Tier 2: 네이버 내부 카페 API JSON (~0.5초)
Tier 3: Playwright + 쿠키 주입 + 스텔스 + 브라우저 풀 재사용 (~3초)

환경변수:
- NAVER_NID_AUT, NAVER_NID_SES (기본 2개 쿠키)
- NAVER_COOKIE_JSON (선택: 전체 쿠키 JSON, 예: '{"NID_AUT":"...","NAC":"..."}')
- NAVER_USER_AGENT (선택: 쿠키 추출한 브라우저의 UA)
"""
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple

import requests as req
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_MOBILE_UA_DEFAULT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
    "Mobile/15E148 Safari/604.1"
)
_DESKTOP_UA_DEFAULT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_TITLE_SELS = [
    ".tit_area .title", "h3.title_text", ".se-title-text",
    ".article_header .title", "#spiTitle",
]
_BODY_SELS = [
    ".se-main-container", ".article_viewer", ".ContentRenderer",
    "#postContent", "#body", ".NLEditor_ct", ".ArticleContentBox",
]
_IMG_RE = re.compile(r"cafeptthumb|postfiles|blogfiles|phinf")
_MIN_BODY_LEN = 100

# Playwright 브라우저 풀 (서버 전역 1개 재사용)
_browser_lock = threading.Lock()
_shared_playwright = None
_shared_browser = None
_shared_context = None
_shared_initialized = False

# club_id 런타임 캐시
_club_id_cache: dict = {}

# 로그인 상태 선검증 캐시
_login_state_checked = False
_login_state_valid = False
_login_check_lock = threading.Lock()


# ── 결과 타입 ──

class CrawlStatus(Enum):
    SUCCESS = "success"
    EMPTY_CONTENT = "empty_content"
    LOGIN_REQUIRED = "login_required"
    AUTH_BLOCKED = "auth_blocked"  # 쿠키 있지만 네이버가 거부 — 제목-only fallback 대상
    BLOCKED = "blocked"
    NOT_FOUND = "not_found"
    NETWORK_ERROR = "network_error"
    PARSE_ERROR = "parse_error"


@dataclass
class CrawlResult:
    status: CrawlStatus
    title: str = ""
    body: str = ""
    photo_count: int = 0
    char_count: int = 0
    tier_used: int = 0
    error_detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == CrawlStatus.SUCCESS

    @property
    def has_title(self) -> bool:
        """제목이라도 가져왔는지 (auth_blocked인 경우에도 True 가능)"""
        return bool(self.title)

    def to_legacy_dict(self) -> dict:
        return {"title": self.title, "body": self.body}

    def to_analysis_dict(self, keyword: str = "") -> Optional[dict]:
        if not self.ok:
            return None
        kw_repeat = self.body.lower().count(keyword.lower()) if keyword else 0
        return {
            "photo_count": max(self.photo_count, 1),
            "keyword_repeat": max(kw_repeat, 1),
            "char_count": self.char_count,
        }


# ── 쿠키 로더 (일반화) ──

def _get_naver_cookies() -> dict:
    """네이버 인증 쿠키 dict 반환. 여러 소스에서 로드:

    1. NAVER_COOKIE_JSON (전체 쿠키 JSON) — 최우선
    2. NAVER_NID_AUT + NAVER_NID_SES (기본 2개) — fallback
    """
    # 1. NAVER_COOKIE_JSON 우선
    cookie_json = os.environ.get("NAVER_COOKIE_JSON", "").strip()
    if cookie_json:
        try:
            cookies = json.loads(cookie_json)
            if isinstance(cookies, dict):
                return {k: str(v) for k, v in cookies.items() if v}
        except json.JSONDecodeError as e:
            logger.warning("NAVER_COOKIE_JSON 파싱 실패: %s", e)

    # 2. NID_AUT + NID_SES fallback
    from src.services.config import NAVER_NID_AUT, NAVER_NID_SES
    if NAVER_NID_AUT and NAVER_NID_SES:
        return {"NID_AUT": NAVER_NID_AUT, "NID_SES": NAVER_NID_SES}
    return {}


def _get_user_agent(mobile: bool = False) -> str:
    """사용자 지정 UA 있으면 사용, 없으면 기본값"""
    custom = os.environ.get("NAVER_USER_AGENT", "").strip()
    if custom:
        return custom
    return _MOBILE_UA_DEFAULT if mobile else _DESKTOP_UA_DEFAULT


# ── 브라우저 헤더 빌더 ──

def _build_browser_headers(mobile: bool = False, referer: str = "https://www.naver.com/") -> dict:
    """브라우저처럼 보이는 헤더 세트"""
    return {
        "User-Agent": _get_user_agent(mobile),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": referer,
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "Connection": "keep-alive",
    }


# ── 로그인 상태 선검증 ──

def verify_login_state(force: bool = False) -> bool:
    """쿠키가 실제로 로그인된 상태인지 검증. 서버 시작 시 1회 + 필요 시 강제 재검증.

    Returns:
        True: 로그인 유효, False: 쿠키 없거나 만료
    """
    global _login_state_checked, _login_state_valid

    with _login_check_lock:
        if _login_state_checked and not force:
            return _login_state_valid

        cookies = _get_naver_cookies()
        if not cookies:
            _login_state_checked = True
            _login_state_valid = False
            return False

        try:
            # 네이버 메인에서 로그인 상태 체크 (경량 엔드포인트)
            r = req.get(
                "https://www.naver.com/",
                headers=_build_browser_headers(),
                cookies=cookies,
                timeout=5,
            )
            # 로그아웃 링크가 있으면 로그인 상태
            is_logged_in = (
                "로그아웃" in r.text
                or "logout" in r.text.lower()
                or "nidLogout" in r.text
            )
            _login_state_valid = is_logged_in
            _login_state_checked = True
            if is_logged_in:
                logger.info("[login_check] ✅ 네이버 로그인 상태 유효")
            else:
                logger.warning("[login_check] ⚠️ 쿠키 있지만 로그인 상태 미감지 — 쿠키 만료 가능")
            return is_logged_in
        except Exception as e:
            logger.warning("[login_check] 검증 실패: %s", e)
            _login_state_checked = True
            _login_state_valid = False
            return False


# ── URL 파싱 ──

def _parse_cafe_url(url: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """URL에서 (cafe_name, article_id, club_id) 추출."""
    cafe_name = None
    article_id = None
    club_id = None

    m = re.search(r"cafe\.naver\.com/([^/?#]+)/(\d+)", url)
    if m:
        cafe_name = m.group(1)
        article_id = m.group(2)

    m_club = re.search(r"clubid=(\d+)", url)
    m_art = re.search(r"articleid=(\d+)", url)
    if m_club:
        club_id = m_club.group(1)
    if m_art and not article_id:
        article_id = m_art.group(1)

    return cafe_name, article_id, club_id


def _resolve_club_id(cafe_name: str) -> Optional[str]:
    """카페 메인에서 club_id 추출 (캐시 우선)"""
    if cafe_name in _club_id_cache:
        return _club_id_cache[cafe_name]

    cookies = _get_naver_cookies()
    try:
        r = req.get(
            f"https://cafe.naver.com/{cafe_name}",
            headers=_build_browser_headers(),
            cookies=cookies if cookies else None,
            timeout=8, allow_redirects=True,
        )
        if r.status_code != 200:
            return None
        m = re.search(r'g_clubId\s*=\s*["\']?(\d+)', r.text)
        if m:
            _club_id_cache[cafe_name] = m.group(1)
            return m.group(1)
        m = re.search(r'clubid=(\d+)', r.text)
        if m:
            _club_id_cache[cafe_name] = m.group(1)
            return m.group(1)
    except Exception:
        pass
    return None


def _extract_from_soup(soup):
    """BeautifulSoup에서 제목, 본문, 사진수, 글자수 추출"""
    title = ""
    for sel in _TITLE_SELS:
        el = soup.select_one(sel)
        if el:
            t = el.get_text(strip=True)
            if t:
                title = t
                break

    body_text = ""
    for sel in _BODY_SELS:
        el = soup.select_one(sel)
        if el:
            body_text = el.get_text("\n", strip=True)
            if len(body_text) >= _MIN_BODY_LEN:
                break
            body_text = ""

    photo_count = len(soup.find_all("img", src=_IMG_RE))
    char_count = len(body_text.replace(" ", "").replace("\n", ""))
    return title, body_text, photo_count, char_count


def _make_result(title, body_text, photo_count, char_count, tier):
    if body_text and len(body_text) >= _MIN_BODY_LEN:
        return CrawlResult(
            status=CrawlStatus.SUCCESS,
            title=title, body=body_text[:5000],
            photo_count=photo_count, char_count=char_count,
            tier_used=tier,
        )
    return None


# ── Tier 1: 쿠키 인증 Session + 브라우저 헤더 ──

def _tier1_cookie_requests(url: str) -> CrawlResult:
    """쿠키 + 브라우저 헤더 Session으로 모바일 페이지 요청 → __NEXT_DATA__ 파싱"""
    mobile_url = url.replace("cafe.naver.com", "m.cafe.naver.com")
    if "m.m.cafe" in mobile_url:
        mobile_url = mobile_url.replace("m.m.cafe", "m.cafe")

    cookies = _get_naver_cookies()
    session = req.Session()
    session.headers.update(_build_browser_headers(mobile=True, referer="https://m.cafe.naver.com/"))
    if cookies:
        session.cookies.update(cookies)

    try:
        r = session.get(mobile_url, timeout=10, allow_redirects=True)
    except req.exceptions.RequestException as e:
        return CrawlResult(status=CrawlStatus.NETWORK_ERROR, tier_used=1,
                           error_detail=str(e)[:200])

    if r.status_code in (401, 403):
        if cookies:
            return CrawlResult(status=CrawlStatus.AUTH_BLOCKED, tier_used=1,
                               error_detail="쿠키 있지만 HTTP 403 — 네이버 거부")
        return CrawlResult(status=CrawlStatus.LOGIN_REQUIRED, tier_used=1)
    if r.status_code == 404:
        return CrawlResult(status=CrawlStatus.NOT_FOUND, tier_used=1)
    if r.status_code != 200:
        return CrawlResult(status=CrawlStatus.BLOCKED, tier_used=1,
                           error_detail=f"HTTP {r.status_code}")

    page_text = r.text

    # 비공개/멤버전용 감지
    if "접근권한" in page_text or "멤버만" in page_text or "가입 후" in page_text:
        if cookies:
            return CrawlResult(status=CrawlStatus.AUTH_BLOCKED, tier_used=1,
                               error_detail="쿠키 있지만 멤버전용 접근 거부")
        return CrawlResult(status=CrawlStatus.LOGIN_REQUIRED, tier_used=1,
                           error_detail="멤버 전용 카페")

    # __NEXT_DATA__ 파싱
    if "__NEXT_DATA__" in page_text:
        m = re.search(r'<script\s+id="__NEXT_DATA__"\s+type="application/json">(.*?)</script>',
                      page_text, re.DOTALL)
        if m:
            try:
                next_data = json.loads(m.group(1))
                props = next_data.get("props", {}).get("pageProps", {})
                article = (props.get("article", {})
                           or props.get("articleDetail", {}).get("article", {})
                           or props.get("data", {}).get("article", {}))
                if article:
                    title = article.get("subject", article.get("title", ""))
                    body_html = article.get("contentHtml", article.get("content", ""))
                    if body_html:
                        soup = BeautifulSoup(body_html, "html.parser")
                        body_text = soup.get_text("\n", strip=True)
                        photo_count = len(soup.find_all("img"))
                        char_count = len(body_text.replace(" ", "").replace("\n", ""))
                        result = _make_result(title, body_text, photo_count, char_count, 1)
                        if result:
                            return result
            except (json.JSONDecodeError, KeyError, TypeError):
                pass

    # CSS 셀렉터 파싱
    soup = BeautifulSoup(page_text, "html.parser")
    title, body_text, photo_count, char_count = _extract_from_soup(soup)
    result = _make_result(title, body_text, photo_count, char_count, 1)
    if result:
        return result

    return CrawlResult(status=CrawlStatus.EMPTY_CONTENT, tier_used=1,
                       error_detail="Tier 1: 모바일 페이지 본문 추출 실패")


# ── Tier 2: 네이버 내부 카페 API ──

def _tier2_cafe_api(url: str) -> CrawlResult:
    """네이버 내부 API로 JSON 조회 (쿠키 필수)"""
    cookies = _get_naver_cookies()
    if not cookies:
        return CrawlResult(status=CrawlStatus.EMPTY_CONTENT, tier_used=2,
                           error_detail="Tier 2: 쿠키 미설정 — 스킵")

    cafe_name, article_id, club_id = _parse_cafe_url(url)
    if not article_id:
        return CrawlResult(status=CrawlStatus.PARSE_ERROR, tier_used=2,
                           error_detail="article_id 추출 실패")
    if not club_id and cafe_name:
        club_id = _resolve_club_id(cafe_name)
    if not club_id:
        return CrawlResult(status=CrawlStatus.PARSE_ERROR, tier_used=2,
                           error_detail="club_id 확인 불가")

    api_url = f"https://apis.naver.com/cafe-web/cafe-articleapi/v2.1/cafes/{club_id}/articles/{article_id}"
    session = req.Session()
    session.headers.update({
        "User-Agent": _get_user_agent(),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        "Referer": f"https://cafe.naver.com/{cafe_name or ''}",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
    })
    session.cookies.update(cookies)

    try:
        r = session.get(api_url, timeout=10)
    except req.exceptions.RequestException as e:
        return CrawlResult(status=CrawlStatus.NETWORK_ERROR, tier_used=2,
                           error_detail=str(e)[:200])

    if r.status_code in (401, 403):
        return CrawlResult(status=CrawlStatus.AUTH_BLOCKED, tier_used=2,
                           error_detail=f"쿠키 있지만 HTTP {r.status_code} — 쿠키 만료 또는 권한 부족")
    if r.status_code == 404:
        return CrawlResult(status=CrawlStatus.NOT_FOUND, tier_used=2)
    if r.status_code != 200:
        return CrawlResult(status=CrawlStatus.BLOCKED, tier_used=2,
                           error_detail=f"HTTP {r.status_code}")

    try:
        data = r.json()
        article = data.get("result", {}).get("article", {})
        if not article:
            return CrawlResult(status=CrawlStatus.EMPTY_CONTENT, tier_used=2,
                               error_detail="API 응답에 article 없음")

        title = article.get("subject", article.get("title", ""))
        content_html = article.get("contentHtml", article.get("content", ""))
        if not content_html:
            return CrawlResult(status=CrawlStatus.EMPTY_CONTENT, tier_used=2,
                               error_detail="contentHtml 없음")

        soup = BeautifulSoup(content_html, "html.parser")
        body_text = soup.get_text("\n", strip=True)
        photo_count = len(soup.find_all("img"))
        char_count = len(body_text.replace(" ", "").replace("\n", ""))

        result = _make_result(title, body_text, photo_count, char_count, 2)
        if result:
            return result

        return CrawlResult(status=CrawlStatus.EMPTY_CONTENT, tier_used=2,
                           error_detail="본문 길이 부족")
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        return CrawlResult(status=CrawlStatus.PARSE_ERROR, tier_used=2,
                           error_detail=f"JSON 파싱 실패: {str(e)[:100]}")


# ── Tier 3: Playwright + 쿠키 주입 + 브라우저 풀 ──

def _cookies_for_playwright(cookies_dict: dict) -> list:
    """Playwright add_cookies 형식으로 변환"""
    result = []
    for name, value in cookies_dict.items():
        # 네이버 쿠키는 .naver.com 도메인
        result.append({
            "name": name,
            "value": str(value),
            "domain": ".naver.com",
            "path": "/",
            "secure": True,
            "httpOnly": name in ("NID_AUT", "NID_SES"),
            "sameSite": "Lax",
        })
    return result


def _get_shared_browser():
    """서버 전역 브라우저 1개 재사용. lock 내부에서 호출해야 함."""
    global _shared_playwright, _shared_browser, _shared_context, _shared_initialized

    if _shared_initialized and _shared_browser and _shared_context:
        try:
            # 브라우저가 살아있는지 핑 (context.pages 호출로 체크)
            _ = _shared_context.pages
            return _shared_browser, _shared_context
        except Exception:
            logger.info("[Tier3] 공유 브라우저 만료 — 재초기화")
            _shared_initialized = False

    if _shared_initialized:
        return _shared_browser, _shared_context

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
            viewport={"width": 1920, "height": 1080},
            locale="ko-KR",
            timezone_id="Asia/Seoul",
        )

        # 스텔스 스크립트 주입
        try:
            from src.services.stealth import STEALTH_INIT_SCRIPT
            _shared_context.add_init_script(STEALTH_INIT_SCRIPT)
        except ImportError:
            pass

        # 쿠키 주입
        cookies = _get_naver_cookies()
        if cookies:
            _shared_context.add_cookies(_cookies_for_playwright(cookies))
            logger.info("[Tier3] 쿠키 %d개 주입", len(cookies))

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


def _tier3_playwright(url: str) -> CrawlResult:
    """Playwright + 쿠키 주입 + 스텔스 + 공유 브라우저"""
    with _browser_lock:
        page = None
        try:
            browser, context = _get_shared_browser()
            page = context.new_page()

            # playwright-stealth 추가 적용
            try:
                from playwright_stealth import stealth_sync
                stealth_sync(page)
            except ImportError:
                pass

            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(2500)

            # iframe 전환 시도
            body_html = ""
            try:
                iframe_el = page.frame("cafe_main")
                if iframe_el:
                    iframe_el.wait_for_load_state("domcontentloaded", timeout=5000)
                    body_html = iframe_el.content()
            except Exception:
                pass

            if not body_html or len(body_html) < 500:
                body_html = page.content()

            soup = BeautifulSoup(body_html, "html.parser")
            title, body_text, photo_count, char_count = _extract_from_soup(soup)
            result = _make_result(title, body_text, photo_count, char_count, 3)
            if result:
                return result

            # 비공개 감지
            full_text = soup.get_text()
            if "접근권한" in full_text or "멤버만" in full_text:
                cookies = _get_naver_cookies()
                status = CrawlStatus.AUTH_BLOCKED if cookies else CrawlStatus.LOGIN_REQUIRED
                return CrawlResult(status=status, tier_used=3,
                                   error_detail="멤버 전용 카페 — 계정 권한 부족",
                                   title=title)

            # 봇 탐지 페이지
            if "JavaScript" in full_text and "enabled" in full_text:
                return CrawlResult(status=CrawlStatus.AUTH_BLOCKED, tier_used=3,
                                   error_detail="봇 탐지 감지 — JavaScript enabled 에러 페이지",
                                   title=title)

            return CrawlResult(status=CrawlStatus.EMPTY_CONTENT, tier_used=3,
                               error_detail="Tier 3: Playwright 본문 추출 실패",
                               title=title)

        except Exception as e:
            error_msg = str(e)[:200]
            if "timeout" in error_msg.lower():
                return CrawlResult(status=CrawlStatus.NETWORK_ERROR, tier_used=3,
                                   error_detail=error_msg)
            return CrawlResult(status=CrawlStatus.PARSE_ERROR, tier_used=3,
                               error_detail=error_msg)
        finally:
            if page:
                try:
                    page.close()
                except Exception:
                    pass


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


# ── 제목-only fallback ──

def _fetch_title_only(url: str) -> Optional[str]:
    """본문 크롤링 실패 시 검색 결과에서 가져온 제목이라도 활용하기 위한 fallback.

    현재는 빈 문자열 반환 — 호출자가 검색 API의 제목을 직접 넘기면 됨.
    """
    return None


# ── 메인 오케스트레이터 ──

def crawl_cafe_article(url: str) -> CrawlResult:
    """3-Tier 폴백 카페 크롤링.

    Tier 1: 쿠키 인증 Session + 브라우저 헤더 (~0.5초)
    Tier 2: 네이버 내부 카페 API JSON (~0.5초)
    Tier 3: Playwright + 쿠키 주입 + 스텔스 (~3초)

    실패 유형:
        SUCCESS: 본문 확보
        AUTH_BLOCKED: 쿠키 있지만 네이버가 거부 — 제목-only fallback 대상
        LOGIN_REQUIRED: 쿠키 없거나 완전 로그아웃 상태
        NOT_FOUND: 글 삭제/비공개
        NETWORK_ERROR, PARSE_ERROR, EMPTY_CONTENT: 기타
    """
    if not url or "cafe.naver.com" not in url:
        return CrawlResult(status=CrawlStatus.PARSE_ERROR,
                           error_detail="유효하지 않은 카페 URL")

    cookies_available = bool(_get_naver_cookies())

    # Tier 1: 쿠키 Session
    logger.info("[Tier1] 쿠키 Session 시도: %s", url)
    result = _tier1_cookie_requests(url)
    if result.ok:
        logger.info("[Tier1] 성공: %s", result.title[:30])
        return result
    if result.status == CrawlStatus.NOT_FOUND:
        return result

    # Tier 2: 내부 API (쿠키 필수)
    if cookies_available:
        logger.info("[Tier2] 내부 API 시도: %s", url)
        result2 = _tier2_cafe_api(url)
        if result2.ok:
            logger.info("[Tier2] 성공: %s", result2.title[:30])
            return result2
        if result2.status == CrawlStatus.NOT_FOUND:
            return result2
        # Tier 2도 AUTH_BLOCKED면 result2로 업데이트 (더 명확한 에러)
        if result2.status == CrawlStatus.AUTH_BLOCKED:
            result = result2

    # Tier 3: Playwright
    logger.info("[Tier3] Playwright 시도: %s", url)
    result3 = _tier3_playwright(url)
    if result3.ok:
        logger.info("[Tier3] 성공: %s", result3.title[:30])
        return result3
    logger.warning("[Tier3] 실패: %s — %s", result3.status.value, result3.error_detail)

    # Tier 3 결과가 AUTH_BLOCKED/LOGIN_REQUIRED면 그걸 리턴 (title이 있을 수 있음)
    if result3.status in (CrawlStatus.AUTH_BLOCKED, CrawlStatus.LOGIN_REQUIRED, CrawlStatus.NOT_FOUND):
        return result3

    # 그 외 실패는 Tier 3 결과 리턴
    return result3
