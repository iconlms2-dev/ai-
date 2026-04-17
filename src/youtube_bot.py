"""
YouTubeBot — Playwright 기반 유튜브 댓글 자동화 (안티디텍트 강화)

Playwright + Stealth + 프록시 + 핑거프린트 관리를 통해
YouTube에 댓글을 자동 게시한다.
"""

import os
import json
import time
import re
from pathlib import Path
from typing import Optional, Dict, List

# Playwright (동기 API)
try:
    from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page
except ImportError:
    sync_playwright = None

# Playwright Stealth
try:
    from playwright_stealth import stealth_sync
    _HAS_STEALTH = True
except ImportError:
    stealth_sync = None
    _HAS_STEALTH = False


# ─── 데이터 디렉토리 ───

def _get_data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", "~")).expanduser() / "CommentBoost"
    else:
        base = Path.home() / "Library" / "Application Support" / "CommentBoost"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _get_cookies_dir() -> Path:
    d = _get_data_dir() / "cookies"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get_profiles_dir() -> Path:
    d = _get_data_dir() / "profiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_label(label: str) -> str:
    return re.sub(r'[^\w\-]', '_', label)


def has_stealth() -> bool:
    """playwright-stealth 설치 여부 반환."""
    return _HAS_STEALTH


# ─── 안티디텍트 스크립트 ───

from src.services.stealth import STEALTH_INIT_SCRIPT

_STEALTH_INIT_SCRIPT = STEALTH_INIT_SCRIPT


class YouTubeBot:
    """Playwright 기반 유튜브 댓글 봇 (안티디텍트 강화)."""

    def __init__(
        self,
        user_id: Optional[int] = None,
        fingerprint_manager=None,
        account_label: str = "",
        antidetect_mode: str = "stealth",  # "stealth" | "adspower"
    ):
        self.user_id = user_id
        self.fingerprint_manager = fingerprint_manager
        self.account_label = account_label
        self.antidetect_mode = antidetect_mode
        self.headless: bool = True

        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._adspower_profile_id: Optional[str] = None

    def start_browser(self, account: Optional[Dict] = None) -> bool:
        """브라우저를 시작한다. antidetect_mode에 따라 분기."""
        if self.antidetect_mode == "adspower":
            return self._start_adspower(account)
        return self._start_stealth(account)

    def _start_adspower(self, account: Optional[Dict] = None) -> bool:
        """AdsPower 로컬 API로 브라우저를 시작한다."""
        import requests as _req

        profile_id = (account or {}).get("adspower_profile_id", "")
        if not profile_id:
            raise RuntimeError("AdsPower 프로필 ID가 설정되지 않았습니다.")

        self._adspower_profile_id = profile_id

        # AdsPower 로컬 API로 브라우저 열기
        try:
            resp = _req.get(
                f"http://local.adspower.com:50325/api/v1/browser/start?user_id={profile_id}",
                timeout=30,
            )
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"AdsPower 브라우저 시작 실패: {data.get('msg', '')}")

            # Playwright로 AdsPower 브라우저에 연결
            ws_url = data["data"]["ws"]["playwright"]
            if sync_playwright is None:
                raise RuntimeError("playwright가 설치되지 않았습니다.")

            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.connect_over_cdp(ws_url)
            self._context = self._browser.contexts[0] if self._browser.contexts else self._browser.new_context()
            self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
            return True

        except Exception as e:
            print(f"[YouTubeBot] AdsPower 연결 실패: {e}")
            raise

    def _start_stealth(self, account: Optional[Dict] = None) -> bool:
        """Playwright Stealth 모드로 브라우저를 시작한다."""
        if sync_playwright is None:
            raise RuntimeError(
                "playwright가 설치되지 않았습니다. "
                "pip install playwright && playwright install chromium"
            )

        self._playwright = sync_playwright().start()
        try:
            label = self.account_label or (account or {}).get("label", "default")
            safe = _safe_label(label)

            # ─── 핑거프린트 매니저에서 context 옵션 가져오기 ───
            if self.fingerprint_manager:
                context_opts = self.fingerprint_manager.get_context_options(label)
            else:
                context_opts = {
                    "user_agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                    ),
                    "viewport": {"width": 1280, "height": 800},
                    "locale": "ko-KR",
                    "timezone_id": "Asia/Seoul",
                }

            # ─── 프록시 설정 ───
            proxy_config = None
            proxy_str = (account or {}).get("proxy", "")
            if proxy_str:
                proxy_config = self._parse_proxy(proxy_str)

            # ─── 브라우저 실행 ───
            launch_opts = {
                "headless": self.headless,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-infobars",
                    "--disable-dev-shm-usage",
                    "--disable-accelerated-2d-canvas",
                    "--no-first-run",
                    "--no-zygote",
                    "--disable-gpu",
                    "--window-size=1280,800",
                ],
            }
            if proxy_config:
                launch_opts["proxy"] = proxy_config

            self._browser = self._playwright.chromium.launch(**launch_opts)

            # ─── 브라우저 컨텍스트 생성 ───
            self._context = self._browser.new_context(**context_opts)

            # ─── 쿠키 복원 ───
            cookies_path = _get_cookies_dir() / f"{safe}.json"
            if cookies_path.exists():
                try:
                    cookies = json.loads(cookies_path.read_text(encoding="utf-8"))
                    self._context.add_cookies(cookies)
                except Exception:
                    pass

            # ─── 안티디텍트 스크립트 주입 ───
            self._context.add_init_script(_STEALTH_INIT_SCRIPT)

            # ─── 페이지 생성 ───
            self._page = self._context.new_page()

            # ─── playwright-stealth 적용 (설치된 경우) ───
            if _HAS_STEALTH and stealth_sync:
                stealth_sync(self._page)

            return True
        except Exception:
            # 초기화 중 실패 시 playwright 및 browser 정리
            try:
                if self._browser:
                    self._browser.close()
            except Exception:
                pass
            try:
                if self._playwright:
                    self._playwright.stop()
            except Exception:
                pass
            self._browser = None
            self._context = None
            self._page = None
            self._playwright = None
            raise

    def _parse_proxy(self, proxy_str: str) -> Optional[Dict]:
        """프록시 문자열을 Playwright 프록시 설정으로 변환.

        지원 형식:
        - http://host:port
        - http://user:pass@host:port
        - socks5://user:pass@host:port
        """
        if not proxy_str:
            return None

        try:
            # 프로토콜 추출
            if "://" not in proxy_str:
                proxy_str = "http://" + proxy_str

            from urllib.parse import urlparse
            parsed = urlparse(proxy_str)

            result = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}
            if parsed.username:
                result["username"] = parsed.username
            if parsed.password:
                result["password"] = parsed.password

            return result
        except Exception:
            return None

    def login_youtube(self, account: Optional[Dict] = None) -> bool:
        """YouTube 로그인 상태를 확인한다."""
        if not self._page:
            return False

        self._page.goto(
            "https://www.youtube.com",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        time.sleep(3)

        # 로그인 상태 확인 — 아바타 버튼 존재 여부
        try:
            avatar = self._page.query_selector(
                'button#avatar-btn, img#img[alt], '
                'yt-img-shadow#avatar img'
            )
            if avatar:
                return True
        except Exception:
            pass

        return False

    def manual_login(self, timeout_sec: int = 120) -> bool:
        """수동 로그인 — 브라우저를 열어서 사용자가 직접 로그인."""
        if not self._page:
            return False

        self._page.goto(
            "https://accounts.google.com/ServiceLogin?service=youtube",
            timeout=30000,
        )

        start = time.time()
        while time.time() - start < timeout_sec:
            try:
                current_url = self._page.url
                if "youtube.com" in current_url or "myaccount.google.com" in current_url:
                    time.sleep(2)
                    self.save_cookies()
                    return True
            except Exception:
                pass
            time.sleep(2)

        return False

    def save_cookies(self):
        """쿠키를 파일로 저장."""
        if not self._context:
            return
        label = _safe_label(self.account_label or "default")
        cookies_path = _get_cookies_dir() / f"{label}.json"
        cookies = self._context.cookies()
        cookies_path.write_text(
            json.dumps(cookies, ensure_ascii=False),
            encoding="utf-8",
        )

    def post_comment(self, youtube_url: str, comment_text: str) -> Optional[str]:
        """유튜브 영상에 댓글을 작성하고 댓글 URL을 반환한다."""
        if not self._page:
            return None

        try:
            self._page.goto(youtube_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)

            # 쿠키 동의 팝업 처리
            self._dismiss_consent()

            # 댓글 영역까지 스크롤
            self._page.evaluate("window.scrollBy(0, 500)")
            time.sleep(2)
            self._page.evaluate("window.scrollBy(0, 300)")
            time.sleep(2)

            # 댓글 입력란 클릭
            comment_box = self._page.wait_for_selector(
                '#simplebox-placeholder, #placeholder-area',
                timeout=15000,
            )
            if comment_box:
                comment_box.click()
                time.sleep(1)

            # 실제 입력란에 텍스트 입력
            editor = self._page.wait_for_selector(
                '#contenteditable-root, div[contenteditable="true"]',
                timeout=10000,
            )
            if not editor:
                return None

            # 인간형 타이핑 (50~120ms 딜레이)
            editor.click()
            time.sleep(0.5)

            import random
            for char in comment_text:
                self._page.keyboard.type(char, delay=random.randint(30, 100))
                if random.random() < 0.05:  # 5% 확률로 짧은 멈춤
                    time.sleep(random.uniform(0.3, 0.8))

            time.sleep(1)

            # 댓글 버튼 클릭
            submit_btn = self._page.wait_for_selector(
                '#submit-button button, tp-yt-paper-button#submit-button',
                timeout=5000,
            )
            if submit_btn:
                submit_btn.click()
                time.sleep(3)

            # 댓글 URL 추출
            comment_url = self._extract_my_comment_url(youtube_url)
            return comment_url

        except Exception as e:
            print(f"[YouTubeBot] 댓글 작성 실패: {e}")
            return None

    def post_reply(
        self,
        youtube_url: str,
        parent_comment_id: str,
        reply_text: str,
    ) -> Optional[str]:
        """기존 댓글에 대댓글을 작성한다."""
        if not self._page:
            return None

        try:
            self._page.goto(youtube_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)
            self._page.evaluate("window.scrollBy(0, 500)")
            time.sleep(2)

            reply_buttons = self._page.query_selector_all('#reply-button-end button')
            if reply_buttons:
                reply_buttons[0].click()
                time.sleep(1)

                editor = self._page.wait_for_selector(
                    '#contenteditable-root',
                    timeout=10000,
                )
                if editor:
                    editor.click()
                    self._page.keyboard.type(reply_text, delay=50)
                    time.sleep(1)

                    submit = self._page.wait_for_selector(
                        '#submit-button button',
                        timeout=5000,
                    )
                    if submit:
                        submit.click()
                        time.sleep(3)
                        return f"{youtube_url}&lc={parent_comment_id}"

        except Exception as e:
            print(f"[YouTubeBot] 대댓글 작성 실패: {e}")

        return None

    def get_top_comment_likes(self, youtube_url: str, count: int = 3) -> List[int]:
        """상위 댓글들의 좋아요 수를 반환한다."""
        if not self._page:
            return []

        try:
            self._page.goto(youtube_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)
            self._page.evaluate("window.scrollBy(0, 500)")
            time.sleep(3)

            likes = []
            like_elements = self._page.query_selector_all('#vote-count-middle')
            for el in like_elements[:count]:
                text = el.inner_text().strip()
                if not text:
                    likes.append(0)
                else:
                    text = text.replace(',', '')
                    if '천' in text:
                        likes.append(int(float(text.replace('천', '')) * 1000))
                    elif '만' in text:
                        likes.append(int(float(text.replace('만', '')) * 10000))
                    else:
                        try:
                            likes.append(int(text))
                        except ValueError:
                            likes.append(0)
            return likes

        except Exception:
            return []

    def get_top_comments_with_text(self, youtube_url: str, count: int = 5) -> List[Dict]:
        """상위 댓글들의 텍스트와 좋아요 수를 반환한다."""
        if not self._page:
            return []

        try:
            self._page.goto(youtube_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)
            self._page.evaluate("window.scrollBy(0, 500)")
            time.sleep(3)

            comments = []
            entries = self._page.query_selector_all('ytd-comment-thread-renderer')
            for entry in entries[:count]:
                try:
                    text_el = entry.query_selector('#content-text')
                    like_el = entry.query_selector('#vote-count-middle')
                    text = text_el.inner_text().strip() if text_el else ""
                    like_text = like_el.inner_text().strip() if like_el else "0"
                    comments.append({"text": text, "likes": like_text})
                except Exception:
                    pass
            return comments

        except Exception:
            return []

    def _dismiss_consent(self):
        """YouTube 쿠키 동의 팝업 처리."""
        try:
            btn = self._page.query_selector(
                'button[aria-label*="Accept"], '
                'button[aria-label*="동의"], '
                'tp-yt-paper-button.style-scope.ytd-consent-bump-v2-lightbox'
            )
            if btn:
                btn.click()
                time.sleep(1)
        except Exception:
            pass

    def close_browser(self):
        """브라우저를 안전하게 종료한다."""
        # AdsPower 모드: API로 브라우저 종료
        if self.antidetect_mode == "adspower" and self._adspower_profile_id:
            try:
                import requests as _req
                _req.get(
                    f"http://local.adspower.com:50325/api/v1/browser/stop?user_id={self._adspower_profile_id}",
                    timeout=10,
                )
            except Exception:
                pass
        else:
            # Stealth 모드: 쿠키 저장
            try:
                if self._context:
                    self.save_cookies()
            except Exception:
                pass

        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None

    def close(self):
        self.close_browser()

    def _extract_my_comment_url(self, youtube_url: str) -> Optional[str]:
        """방금 작성한 내 댓글의 URL을 추출한다."""
        try:
            time.sleep(2)
            first_comment = self._page.query_selector(
                'ytd-comment-thread-renderer #author-text'
            )
            if first_comment:
                permalink = self._page.query_selector(
                    'ytd-comment-thread-renderer #header-author a.yt-simple-endpoint'
                )
                if permalink:
                    href = permalink.get_attribute('href')
                    if href and 'lc=' in href:
                        return f"https://www.youtube.com{href}"

            return youtube_url

        except Exception:
            return youtube_url
