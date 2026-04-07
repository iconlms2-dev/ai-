"""
CafeCommentBot — 네이버 카페 댓글 자동 등록

AdsPower 안티디텍트 브라우저 또는 Playwright Stealth를 사용하여
각 댓글을 다른 계정으로 카페 게시글에 자동 등록한다.

멘토님 원칙:
- 계정별 IP/브라우저 완전 분리 (AdsPower)
- 메모장 경유 붙여넣기 (클립보드 → Ctrl+V)
- 댓글 간 30초~3분 랜덤 대기
- 댓글 등록 후 댓글창 닫기
"""

import os
import time
import random
from typing import Optional, Dict, List

try:
    from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page
except ImportError:
    sync_playwright = None

try:
    from playwright_stealth import stealth_sync
    _HAS_STEALTH = True
except ImportError:
    stealth_sync = None
    _HAS_STEALTH = False

import requests as _req

from src.cafe_safety_rules import check_rules, record_comment, get_random_delay


class CafeCommentBot:
    def __init__(self):
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._adspower_profile_id: Optional[str] = None

    # ─── 브라우저 시작 ───

    def start_adspower(self, profile_id: str) -> bool:
        """AdsPower 프로필로 브라우저 시작"""
        if not profile_id:
            raise RuntimeError("AdsPower 프로필 ID 필요")
        self._adspower_profile_id = profile_id
        try:
            resp = _req.get(
                f"http://local.adspower.com:50325/api/v1/browser/start?user_id={profile_id}",
                timeout=30,
            )
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"AdsPower 시작 실패: {data.get('msg', '')}")
            ws_url = data["data"]["ws"]["playwright"]
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.connect_over_cdp(ws_url)
            self._context = self._browser.contexts[0] if self._browser.contexts else self._browser.new_context()
            self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
            return True
        except Exception as e:
            print(f"[CafeBot] AdsPower 연결 실패: {e}")
            return False

    def start_stealth(self, account: Dict) -> bool:
        """Playwright Stealth 모드로 시작 (AdsPower 없을 때 대안)"""
        if sync_playwright is None:
            raise RuntimeError("playwright 미설치")
        self._playwright = sync_playwright().start()
        proxy_config = None
        if account.get('proxy'):
            proxy_config = {'server': account['proxy']}
        self._browser = self._playwright.chromium.launch(
            headless=False,
            proxy=proxy_config,
        )
        self._context = self._browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            viewport={'width': 1280, 'height': 800},
            locale='ko-KR',
            timezone_id='Asia/Seoul',
        )
        self._page = self._context.new_page()
        if _HAS_STEALTH and stealth_sync:
            stealth_sync(self._page)
        return True

    # ─── 네이버 로그인 ───

    def check_login(self) -> bool:
        """현재 네이버 로그인 상태 확인"""
        try:
            self._page.goto('https://nid.naver.com/nidlogin.login', timeout=10000)
            time.sleep(2)
            # 이미 로그인된 상태면 마이페이지로 리다이렉트됨
            if 'nidlogin' not in self._page.url:
                return True
            return False
        except Exception:
            return False

    def login_naver(self, naver_id: str, password: str) -> str:
        """
        네이버 로그인 시도.
        반환: 'success' | 'failed' | 'captcha' | 'suspended' | 'security'
        """
        try:
            self._page.goto('https://nid.naver.com/nidlogin.login', timeout=15000)
            time.sleep(2)

            # 이미 로그인된 상태
            if 'nidlogin' not in self._page.url:
                return 'success'

            # ID 입력 (클립보드 붙여넣기 방식)
            id_input = self._page.query_selector('#id')
            if id_input:
                id_input.click()
                self._page.evaluate(f'navigator.clipboard.writeText("{naver_id}")')
                self._page.keyboard.press('Meta+v' if os.name != 'nt' else 'Control+v')
                time.sleep(0.5)

            # PW 입력
            pw_input = self._page.query_selector('#pw')
            if pw_input:
                pw_input.click()
                self._page.evaluate(f'navigator.clipboard.writeText("{password}")')
                self._page.keyboard.press('Meta+v' if os.name != 'nt' else 'Control+v')
                time.sleep(0.5)

            # 로그인 버튼
            login_btn = self._page.query_selector('#log\\.login')
            if login_btn:
                login_btn.click()
            time.sleep(3)

            url = self._page.url
            html = self._page.content()

            # 상태 판별
            if '보안' in html or 'security' in url:
                return 'security'
            if '캡차' in html or 'captcha' in url:
                return 'captcha'
            if '이용제한' in html or '정지' in html:
                return 'suspended'
            if 'nidlogin' in url:
                return 'failed'
            return 'success'

        except Exception as e:
            print(f"[CafeBot] 로그인 에러: {e}")
            return 'failed'

    # ─── 댓글 등록 ───

    def post_comment(self, post_url: str, comment_text: str) -> Dict:
        """
        카페 게시글에 댓글 등록.
        반환: {'success': bool, 'error': str}
        """
        try:
            self._page.goto(post_url, timeout=20000)
            time.sleep(3)

            # iframe 진입 (네이버 카페는 iframe 사용)
            iframe = None
            try:
                iframe = self._page.frame('cafe_main')
            except Exception:
                pass

            target = iframe if iframe else self._page

            # 댓글 입력란 찾기
            comment_box = None
            selectors = [
                'textarea.comment_inbox',
                'textarea[placeholder*="댓글"]',
                '.comment_writer textarea',
                '#CommentBox textarea',
            ]
            for sel in selectors:
                try:
                    comment_box = target.wait_for_selector(sel, timeout=5000)
                    if comment_box:
                        break
                except Exception:
                    continue

            if not comment_box:
                return {'success': False, 'error': '댓글 입력란을 찾을 수 없음'}

            # 댓글 입력란 클릭 → 활성화
            comment_box.click()
            time.sleep(1)

            # 클립보드에 텍스트 복사 → 붙여넣기 (멘토님 원칙: 메모장 경유)
            self._page.evaluate(f'navigator.clipboard.writeText(`{comment_text}`)')
            time.sleep(0.3)
            self._page.keyboard.press('Meta+v' if os.name != 'nt' else 'Control+v')
            time.sleep(1)

            # 등록 버튼 클릭
            submit_btn = None
            btn_selectors = [
                'a.btn_register',
                'button.btn_register',
                'a.button_comment',
                'button[type="submit"]',
            ]
            for sel in btn_selectors:
                try:
                    submit_btn = target.query_selector(sel)
                    if submit_btn:
                        break
                except Exception:
                    continue

            if not submit_btn:
                return {'success': False, 'error': '등록 버튼을 찾을 수 없음'}

            submit_btn.click()
            time.sleep(3)

            return {'success': True, 'error': ''}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ─── 브라우저 종료 ───

    def close(self):
        """브라우저 종료"""
        try:
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass

        # AdsPower 모드: API로 브라우저 종료
        if self._adspower_profile_id:
            try:
                _req.get(
                    f"http://local.adspower.com:50325/api/v1/browser/stop?user_id={self._adspower_profile_id}",
                    timeout=10,
                )
            except Exception:
                pass

        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._adspower_profile_id = None


def run_auto_comments(post_url: str, comments: List[str], accounts: List[Dict],
                      on_progress=None, on_result=None):
    """
    댓글 자동 등록 메인 함수.

    accounts: [{'id': ..., 'naver_id': ..., 'password': ..., 'adspower_profile_id': ..., 'proxy': ...}, ...]
    on_progress: callback(msg)
    on_result: callback({account_id, comment, success, error})
    """
    # 카페 이름 추출
    cafe_name = ''
    if 'cafe.naver.com/' in post_url:
        parts = post_url.split('cafe.naver.com/')
        if len(parts) > 1:
            cafe_name = parts[1].split('/')[0].split('?')[0]

    results = []
    for i, (comment, account) in enumerate(zip(comments, accounts)):
        acc_id = account.get('id', '')
        acc_label = account.get('label', account.get('naver_id', ''))

        if on_progress:
            on_progress(f'[{i+1}/{len(comments)}] {acc_label} — 댓글 등록 준비 중...')

        # 안전 규칙 체크
        passed, reason = check_rules(acc_id, post_url, post_url)
        if not passed:
            result = {'account_id': acc_id, 'label': acc_label, 'comment': comment[:30], 'success': False, 'error': reason}
            results.append(result)
            if on_result:
                on_result(result)
            continue

        bot = CafeCommentBot()
        try:
            # 브라우저 시작
            if account.get('adspower_profile_id'):
                if on_progress:
                    on_progress(f'[{i+1}/{len(comments)}] {acc_label} — AdsPower 프로필 열기...')
                started = bot.start_adspower(account['adspower_profile_id'])
            else:
                if on_progress:
                    on_progress(f'[{i+1}/{len(comments)}] {acc_label} — 브라우저 시작...')
                started = bot.start_stealth(account)

            if not started:
                result = {'account_id': acc_id, 'label': acc_label, 'comment': comment[:30], 'success': False, 'error': '브라우저 시작 실패'}
                results.append(result)
                if on_result:
                    on_result(result)
                continue

            # 로그인 체크
            if not bot.check_login():
                if on_progress:
                    on_progress(f'[{i+1}/{len(comments)}] {acc_label} — 로그인 중...')
                naver_id = account.get('naver_id', '')
                password = account.get('password', '')
                if not password:
                    result = {'account_id': acc_id, 'label': acc_label, 'comment': comment[:30], 'success': False, 'error': '비밀번호 미설정'}
                    results.append(result)
                    if on_result:
                        on_result(result)
                    continue

                login_status = bot.login_naver(naver_id, password)
                if login_status != 'success':
                    result = {'account_id': acc_id, 'label': acc_label, 'comment': comment[:30], 'success': False, 'error': f'로그인 실패: {login_status}'}
                    results.append(result)
                    if on_result:
                        on_result(result)
                    # 정지/보안 감지 시 계정 상태 업데이트 필요
                    if login_status in ('suspended', 'security'):
                        result['status_change'] = '정지 의심'
                    continue

            # 댓글 등록
            if on_progress:
                on_progress(f'[{i+1}/{len(comments)}] {acc_label} — 댓글 등록 중...')
            post_result = bot.post_comment(post_url, comment)

            # 기록 저장
            record_comment(acc_id, cafe_name, post_url, comment, post_result['success'])

            result = {
                'account_id': acc_id, 'label': acc_label,
                'comment': comment[:30], 'success': post_result['success'],
                'error': post_result.get('error', ''),
            }
            results.append(result)
            if on_result:
                on_result(result)

        except Exception as e:
            result = {'account_id': acc_id, 'label': acc_label, 'comment': comment[:30], 'success': False, 'error': str(e)}
            results.append(result)
            if on_result:
                on_result(result)
        finally:
            bot.close()

        # 다음 댓글까지 랜덤 대기 (마지막 댓글 제외)
        if i < len(comments) - 1:
            delay = get_random_delay()
            if on_progress:
                on_progress(f'[{i+1}/{len(comments)}] 대기 중... ({int(delay)}초)')
            time.sleep(delay)

    return results
