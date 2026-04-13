"""쓰레드(Threads) 콘텐츠 생성 / 계정관리 / 스케줄러"""
import json
import os
import re
import time
import uuid
import random
import asyncio
import threading
from datetime import datetime, timedelta
from urllib.parse import quote

import requests as req
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from src.services.sse_helper import sse_dict, SSEResponse

from src.services.config import (
    executor,
    CONTENT_DB_ID,
    KEYWORD_DB_ID,
    NOTION_TOKEN,
    THREADS_APP_ID,
    THREADS_APP_SECRET,
    THREADS_ACCOUNTS_FILE,
    THREADS_QUEUE_FILE,
    REDIRECT_BASE_URL,
)
from src.services.ai_client import call_claude
from src.services.review_service import review_and_save

router = APIRouter()

# ═══════════════════════════ 내부 상태 / 잠금 ═══════════════════════════

_threads_lock = threading.Lock()


# ═══════════════════════════ 헬퍼 함수 ═══════════════════════════

def _threads_load_accounts():
    with _threads_lock:
        if os.path.exists(THREADS_ACCOUNTS_FILE):
            with open(THREADS_ACCOUNTS_FILE, 'r') as f:
                return json.load(f)
        return {'accounts': []}


def _threads_save_accounts(data):
    with _threads_lock:
        with open(THREADS_ACCOUNTS_FILE, 'w') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def _threads_load_queue():
    with _threads_lock:
        if os.path.exists(THREADS_QUEUE_FILE):
            with open(THREADS_QUEUE_FILE, 'r') as f:
                return json.load(f)
        return {'queue': []}


def _threads_save_queue(data):
    with _threads_lock:
        with open(THREADS_QUEUE_FILE, 'w') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def _threads_api(access_token, endpoint, method='GET', data=None):
    """Threads Graph API 래퍼"""
    base = 'https://graph.threads.net/v1.0'
    url = f'{base}/{endpoint}'
    headers = {'Authorization': f'Bearer {access_token}'}
    try:
        if method == 'GET':
            r = req.get(url, headers=headers, params=data, timeout=15)
        else:
            r = req.post(url, headers=headers, json=data, timeout=15)
        if r.status_code == 200:
            return {'ok': True, 'data': r.json()}
        return {'ok': False, 'error': r.text[:300], 'status': r.status_code}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


# ────── 계정 관리 ──────

@router.get("/accounts")
async def threads_accounts_list():
    data = _threads_load_accounts()
    safe = []
    for acc in data.get('accounts', []):
        safe.append({
            'id': acc['id'],
            'role': acc.get('role', 'support'),
            'persona': acc.get('persona', {}),
            'reference_accounts': acc.get('reference_accounts', []),
            'schedule': acc.get('schedule', {}),
            'connected': bool(acc.get('token', {}).get('access_token')),
            'username': acc.get('username', ''),
            'token_expires': acc.get('token', {}).get('expires_at', ''),
            'daily_count': acc.get('daily_count', 0),
        })
    return {'accounts': safe}


@router.post("/accounts")
async def threads_accounts_add(request: Request):
    body = await request.json()
    data = _threads_load_accounts()
    acc_id = 'threads_' + str(uuid.uuid4())[:8]
    account = {
        'id': acc_id,
        'role': body.get('role', 'support'),
        'token': {},
        'username': '',
        'persona': body.get('persona', {'name': '', 'age': '', 'job': '', 'tone': '친근', 'interests': []}),
        'reference_accounts': body.get('reference_accounts', []),
        'schedule': body.get('schedule', {'daily_posts': 2, 'active_hours': [9, 22], 'min_interval_hours': 4}),
        'daily_count': 0,
        'daily_count_date': datetime.now().strftime('%Y-%m-%d'),
    }
    data['accounts'].append(account)
    _threads_save_accounts(data)
    return {'ok': True, 'id': acc_id}


@router.put("/accounts/{acc_id}")
async def threads_accounts_update(acc_id: str, request: Request):
    body = await request.json()
    data = _threads_load_accounts()
    for acc in data['accounts']:
        if acc['id'] == acc_id:
            if 'persona' in body:
                acc['persona'] = body['persona']
            if 'role' in body:
                acc['role'] = body['role']
            if 'reference_accounts' in body:
                acc['reference_accounts'] = body['reference_accounts']
            if 'schedule' in body:
                acc['schedule'] = body['schedule']
            _threads_save_accounts(data)
            return {'ok': True}
    return JSONResponse({'ok': False, 'error': '계정 없음'}, 404)


@router.delete("/accounts/{acc_id}")
async def threads_accounts_delete(acc_id: str):
    data = _threads_load_accounts()
    data['accounts'] = [a for a in data['accounts'] if a['id'] != acc_id]
    _threads_save_accounts(data)
    return {'ok': True}


# ────── OAuth ──────

@router.get("/auth-url")
async def threads_auth_url(account_id: str = ''):
    if not THREADS_APP_ID:
        return JSONResponse({'error': 'THREADS_APP_ID 미설정'}, 400)
    redirect_uri = f'{REDIRECT_BASE_URL}/api/threads/callback'
    scope = 'threads_basic,threads_content_publish,threads_manage_insights,threads_manage_replies'
    state = account_id or 'default'
    url = (f'https://threads.net/oauth/authorize?client_id={THREADS_APP_ID}'
           f'&redirect_uri={quote(redirect_uri)}&scope={scope}'
           f'&response_type=code&state={state}')
    return {'url': url}


@router.get("/callback")
async def threads_callback(code: str = '', state: str = ''):
    if not code:
        return JSONResponse({'error': 'code 없음'}, 400)
    redirect_uri = f'{REDIRECT_BASE_URL}/api/threads/callback'
    # 1단계: 단기 토큰 발급
    try:
        r = req.post('https://graph.threads.net/oauth/access_token', data={
            'client_id': THREADS_APP_ID,
            'client_secret': THREADS_APP_SECRET,
            'grant_type': 'authorization_code',
            'redirect_uri': redirect_uri,
            'code': code,
        }, timeout=15)
        if r.status_code != 200:
            return JSONResponse({'error': f'토큰 발급 실패: {r.text[:300]}'}, 400)
        short_token = r.json()
    except Exception as e:
        return JSONResponse({'error': str(e)}, 500)

    # 2단계: 장기 토큰 교환 (60일)
    try:
        r2 = req.get('https://graph.threads.net/access_token', params={
            'grant_type': 'th_exchange_token',
            'client_secret': THREADS_APP_SECRET,
            'access_token': short_token.get('access_token', ''),
        }, timeout=15)
        if r2.status_code == 200:
            long_token = r2.json()
            access_token = long_token.get('access_token', short_token.get('access_token', ''))
            expires_in = long_token.get('expires_in', 5184000)
        else:
            access_token = short_token.get('access_token', '')
            expires_in = 3600
    except Exception:
        access_token = short_token.get('access_token', '')
        expires_in = 3600

    expires_at = (datetime.now() + timedelta(seconds=expires_in)).isoformat()
    user_id = short_token.get('user_id', '')

    # 사용자 이름 가져오기
    username = ''
    if access_token:
        me = _threads_api(access_token, 'me', data={'fields': 'id,username'})
        if me.get('ok'):
            username = me['data'].get('username', '')
            user_id = me['data'].get('id', user_id)

    # 계정에 토큰 저장
    data = _threads_load_accounts()
    acc_id = state if state != 'default' else None
    found = False
    for acc in data['accounts']:
        if acc['id'] == acc_id:
            acc['token'] = {'access_token': access_token, 'expires_at': expires_at, 'user_id': user_id}
            acc['username'] = username
            found = True
            break
    if not found and data['accounts']:
        # state 매칭 안되면 첫 미연결 계정에 저장
        for acc in data['accounts']:
            if not acc.get('token', {}).get('access_token'):
                acc['token'] = {'access_token': access_token, 'expires_at': expires_at, 'user_id': user_id}
                acc['username'] = username
                found = True
                break
    if not found:
        # 계정이 아예 없으면 자동 생성
        new_id = 'threads_' + str(uuid.uuid4())[:8]
        data['accounts'].append({
            'id': new_id, 'role': 'main', 'token': {'access_token': access_token, 'expires_at': expires_at, 'user_id': user_id},
            'username': username, 'persona': {'name': '', 'age': '', 'job': '', 'tone': '친근', 'interests': []},
            'reference_accounts': [], 'schedule': {'daily_posts': 3, 'active_hours': [9, 22], 'min_interval_hours': 3},
            'daily_count': 0, 'daily_count_date': datetime.now().strftime('%Y-%m-%d'),
        })
    _threads_save_accounts(data)
    # 대시보드로 리다이렉트
    return RedirectResponse(url=f'{REDIRECT_BASE_URL}/?menu=threads&auth=ok')


@router.get("/status")
async def threads_status():
    data = _threads_load_accounts()
    statuses = []
    now = datetime.now()
    for acc in data.get('accounts', []):
        token = acc.get('token', {})
        connected = bool(token.get('access_token'))
        expires_at = token.get('expires_at', '')
        days_left = -1
        warning = False
        if expires_at:
            try:
                exp = datetime.fromisoformat(expires_at)
                days_left = (exp - now).days
                warning = days_left <= 7
            except Exception:
                pass
        statuses.append({
            'id': acc['id'], 'username': acc.get('username', ''),
            'connected': connected, 'days_left': days_left, 'warning': warning,
        })
    return {'statuses': statuses}


# ────── 참조계정 크롤링 ──────

_threads_crawl_semaphore = asyncio.Semaphore(1)


def _threads_crawl_account(username):
    """Playwright로 Threads 참조계정 최근 글 크롤링"""
    posts = []
    browser = None
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': 430, 'height': 932},
                locale='ko-KR',
            )
            page = ctx.new_page()
            clean_name = username.lstrip('@')
            page.goto(f'https://www.threads.net/@{clean_name}', timeout=20000)
            page.wait_for_timeout(3000)
            # 스크롤해서 포스트 로드
            for _ in range(3):
                page.evaluate('window.scrollBy(0, 800)')
                page.wait_for_timeout(1500)
            # 포스트 텍스트 수집
            elements = page.query_selector_all('[data-pressable-container="true"]')
            for el in elements[:10]:
                text = el.inner_text().strip()
                if text and len(text) > 10:
                    lines = text.split('\n')
                    content = '\n'.join([l for l in lines if l.strip() and not l.strip().startswith('좋아요') and not l.strip().endswith('전')])
                    if content and len(content) > 10:
                        posts.append({'text': content[:500], 'length': len(content)})
    except Exception as e:
        print(f"[threads_crawl] 에러: {e}")
    finally:
        try:
            if browser:
                browser.close()
        except Exception:
            pass
    return posts


@router.post("/crawl-reference")
async def threads_crawl_reference(request: Request):
    body = await request.json()
    account_id = body.get('account_id', '')
    data = _threads_load_accounts()
    acc = next((a for a in data['accounts'] if a['id'] == account_id), None)
    if not acc:
        return JSONResponse({'error': '계정 없음'}, 404)
    ref_accounts = acc.get('reference_accounts', [])
    if not ref_accounts:
        return JSONResponse({'error': '참조계정 미등록'}, 400)

    async with _threads_crawl_semaphore:
        loop = asyncio.get_running_loop()
        all_posts = []
        for ref in ref_accounts[:3]:
            if await request.is_disconnected():
                print("[threads_crawl] 클라이언트 연결 끊김, 크롤링 중단")
                break
            posts = await loop.run_in_executor(executor, _threads_crawl_account, ref)
            all_posts.extend([{**p, 'source': ref} for p in posts])
    return {'posts': all_posts, 'count': len(all_posts)}


# ────── 프롬프트 ──────

def _build_threads_daily_prompt(persona, ref_posts):
    """일상글 프롬프트 — 참조계정 스타일 카피"""
    persona_desc = f"이름: {persona.get('name','')}, 나이: {persona.get('age','')}, 직업: {persona.get('job','')}"
    interests = ', '.join(persona.get('interests', []))
    tone = persona.get('tone', '친근')

    ref_examples = ''
    if ref_posts:
        ref_examples = '참조 계정 글 예시:\n'
        for i, p in enumerate(ref_posts[:5], 1):
            ref_examples += f'---예시 {i}---\n{p["text"][:200]}\n'

    system = f"""역할: Threads(쓰레드)에서 자연스러운 일상글을 작성하는 SNS 사용자.

페르소나:
{persona_desc}
관심사: {interests}
말투: {tone}

목표: 참조 계정의 글 스타일(주제 선택, 문장 길이, 톤)을 분석하고, 이 페르소나의 말투로 변환하여 Threads에 맞는 일상글을 작성한다.

{ref_examples}

Threads 플랫폼 특성 (반드시 반영):
- 트위터와 비슷한 짧은 텍스트 중심 플랫폼
- 1~3문장 단문이 대세. 길어도 5문장 이내
- 줄임말, 구어체, 혼잣말 톤이 자연스러움 ("ㄹㅇ", "진짜", "아 맞다", "근데")
- 완결된 글보다 생각을 툭 던지는 느낌
- 이모티콘은 0~1개 (과하면 봇 느낌)
- 해시태그는 거의 안 씀 (쓰더라도 1개, 안 써도 됨)
- 블로그/카페처럼 정리된 글 금지 — 머릿속 생각을 그대로 옮긴 느낌

작성 규칙:
1. 참조 계정의 주제/감성을 따라하되, 말투는 페르소나에 맞게
2. 200자 이내 권장 (최대 500자)
3. 제품·브랜드·광고 언급 절대 금지
4. 문장 끝을 다양하게 ("~인 듯", "~하다가", "~했는데", "~임", "~ㅋㅋ")
5. 줄바꿈 적극 활용 (한 문장씩 끊기)

출력 형식:
[포스트]
(본문)

[해시태그]
(해시태그 또는 '없음')

★ 출력 규칙: 인사말, 부연 설명, 괄호 설명([어그로], [본문] 등) 절대 넣지 말고 위 형식 그대로만 출력할 것.

예시:
[포스트]
아 요즘 왜 이렇게 피곤한 건지
커피를 세 잔을 마셔도 눈이 안 떠짐
나만 그런 거 아니지..?

[해시태그]
없음"""

    user = f"위 참조 계정의 스타일을 분석해서, 페르소나({persona.get('name','')})의 말투로 일상글 1개를 작성해주세요."
    return system, user


def _build_threads_traffic_prompt(keyword, persona, product, forbidden='', selling_logic='shuffle'):
    """물길글 프롬프트 — 3가지 SL(셀링 로직) 지원"""
    brand_kw = product.get('brand_keyword', '')
    tone = persona.get('tone', '친근')
    persona_job = persona.get('job', '')
    persona_interests = ', '.join(persona.get('interests', []))

    threads_base = f"""Threads 플랫폼 특성 (반드시 반영):
- 짧은 텍스트 중심. 1~5문장.
- 줄임말, 구어체 자연스러움
- 줄바꿈으로 문장 끊기
- 이모티콘 0~1개, 해시태그 0~1개
- 정리된 글 금지 — 생각을 툭 던지는 느낌

★ 첫 줄 어그로 필수:
첫 문장에서 반드시 스크롤을 멈추게 해야 함. 아래 패턴 중 하나 활용:
- 부정 편향: "~하면 진짜 손해", "아직도 ~하는 사람 있음?"
- 숫자 충격: "3년 걸림", "100만원 날렸다"
- 권위: "N년차가 말하는데", "~해본 사람으로서"
- 호기심: "이거 나만 알고 싶은데", "솔직히 말할게"
- 공감: "나만 이런 거 아니지?", "다들 이거 겪어봤을 텐데"

페르소나 말투: {tone}"""

    if selling_logic == 'shuffle':
        system = f"""역할: Threads에서 경험을 공유하는 일반 사용자.

{threads_base}

셀링 로직: 정보 셔플식
대안들 사이에 자연스럽게 제품을 섞어 간접 노출한다.

규칙:
1. [어그로 첫 줄] → 대안 3~4개 짧게 나열 → "나는 개인적으로 ~가 맞았음"
2. 나만의 키워드를 대안 중 하나로 자연스럽게 배치 (1회만)
3. 비교표/번호 매기기 금지 — 대화체로 자연스럽게
4. 200자 이내 권장 (최대 500자)
5. 광고 어투 금지 ("강추", "인생템", "꼭 써보세요")
6. 제품명 직접 언급 금지 (나만의 키워드만 사용)

출력 형식:
[포스트]
(본문)

[해시태그]
(해시태그 또는 '없음')

★ 출력 규칙: 인사말, 부연 설명, 괄호 설명 절대 넣지 말고 위 형식 그대로만 출력할 것.

예시:
[포스트]
아직도 이거 모르는 사람 많던데
A도 써봤고 B도 써봤는데
솔직히 C가 제일 나았음
근데 개인적으로는 걍 (키워드)가 맞았다
뭐 사람마다 다르겠지만

[해시태그]
없음

금지 키워드: {forbidden}"""

    elif selling_logic == 'sympathy':
        system = f"""역할: Threads에서 자신의 사업/제품을 직접 홍보하는 판매자.

{threads_base}

셀링 로직: 연민 판매자식
불쌍한 사연을 깔고 대놓고 홍보한다. 동정심을 유발하되 진심이 느껴져야 함.

구조:
1. [어그로 첫 줄] — 충격적인 사연 한 줄 ("퇴사하고 이거 하나에 올인했는데", "3년 걸렸다 진짜로")
2. 힘든 사연 — 창업 고생, 실패 경험, 밤새 작업, 돈 다 날림 등
3. 이 제품을 왜 만들었는지, 얼마나 공들였는지
4. 대놓고 홍보 — "한번만 봐주세요", "검색해봐 주세요"

규칙:
1. 제품명/나만의 키워드 직접 언급 OK (대놓고 홍보니까)
2. 구걸 느낌 아니고 "진심을 담았다" 느낌
3. 200자 이내 권장 (최대 500자)
4. 줄바꿈 많이, 짧은 문장
5. 과장된 성공 스토리 금지 — 아직 힘든 상황이어야 동정 유발

출력 형식:
[포스트]
(본문)

[해시태그]
(해시태그 또는 '없음')

★ 출력 규칙: 인사말, 부연 설명, 괄호 설명 절대 넣지 말고 위 형식 그대로만 출력할 것.

예시:
[포스트]
퇴사하고 이거 하나에 올인한 지 8개월째인데
솔직히 아직도 통장 잔고 보면 한숨 나옴
근데 진짜 좋은 거 만들었다고 자신 있어서
한번만 검색해봐 주세요 (제품명)
제발ㅠ

[해시태그]
없음

금지 키워드: {forbidden}"""

    else:  # review
        system = f"""역할: Threads에서 전문가 포지션으로 후기를 공유하는 사용자.

{threads_base}

셀링 로직: 후기 신뢰식
이 분야의 전문가/경험자로서 제품 후기를 담백하게 공유한다. 신뢰가 핵심.

페르소나 직업: {persona_job}
페르소나 관심 분야: {persona_interests}

구조:
1. [어그로 첫 줄] — 권위/경험 기반 ("이 업계 N년차가 말하는데", "솔직히 다 거기서 거긴데 이건 좀 달랐음")
2. 전문가 포지셔닝 — 이 분야에서 뭘 해왔는지 간단히
3. 비교 대상 언급 — "A도 써봤고 B도 써봤는데"
4. 이 제품의 구체적 변화/결과 — 담백하고 건조하게

규칙:
1. 제품명/나만의 키워드 직접 언급 OK
2. 페르소나의 직업/관심사가 전문성 근거가 되어야 함
3. 과장 금지 — "인생이 바뀌었다" 같은 표현 금지
4. 구체적 수치/기간 포함 ("2주 써봤는데", "확실히 달라짐")
5. 200자 이내 권장 (최대 500자)

출력 형식:
[포스트]
(본문)

[해시태그]
(해시태그 또는 '없음')

★ 출력 규칙: 인사말, 부연 설명, 괄호 설명 절대 넣지 말고 위 형식 그대로만 출력할 것.

예시:
[포스트]
이 바닥 5년차가 말하는데
솔직히 다 고만고만함
A도 써봤고 B도 써봤는데
근데 (제품명)은 2주 쓰고 확실히 달라짐
과장 아니고 체감이 다름

[해시태그]
없음

금지 키워드: {forbidden}"""

    sl_label = {'shuffle': '정보 셔플식', 'sympathy': '연민 판매자식', 'review': '후기 신뢰식'}.get(selling_logic, '정보 셔플식')
    user = f"""메인 키워드: {keyword}
소구점: {product.get('usp', '')}
타겟층: {product.get('target', '')}
나만의 키워드: {brand_kw}
제품명: {product.get('name', '')}

위 정보를 바탕으로 [{sl_label}]으로 Threads 물길글 1개를 작성해주세요."""
    return system, user


def _build_threads_comment_prompt(post_content, persona):
    """댓글 프롬프트 — 게시물 맥락에 맞는 매력적 댓글"""
    tone = persona.get('tone', '친근')
    system = f"""역할: Threads에서 소통하는 일반 사용자.

말투: {tone}

목표: 아래 게시물에 달기 좋은 자연스러운 댓글 3개를 작성한다.

Threads 댓글 특성:
- 짧다. 한 줄이 대부분 ("ㄹㅇㅋㅋ", "이거 나도 그랬음", "오 대박")
- 공감형, 질문형, 경험공유형을 섞되 전부 짧게
- 이모티콘 0~1개
- 광고·홍보 느낌 금지
- "정보 감사합니다" 같은 정중한 톤 금지 — 친구한테 말하듯

작성 규칙:
1. 각 댓글 1문장 (30자 이내)
2. 3개 모두 톤이 달라야 함
3. 줄임말, 구어체 OK

출력 형식:
1. (댓글1)
2. (댓글2)
3. (댓글3)"""
    user = f"게시물 내용:\n{post_content[:500]}\n\n위 게시물에 달 매력적인 댓글 3개를 작성해주세요."
    return system, user


def _parse_threads_output(raw):
    """쓰레드 생성 결과 파싱: 포스트 본문 + 해시태그 분리 (LLM 인사말 방어 포함)"""
    text = raw.strip()
    hashtag = ''
    # LLM 인사말/부연 제거: [포스트] 태그 이전의 텍스트는 전부 버림
    if '[포스트]' in text:
        text = text[text.index('[포스트]'):]
    # 해시태그 분리
    if '[해시태그]' in text:
        parts = text.split('[해시태그]')
        text = parts[0].strip()
        ht = parts[1].strip()
        if ht and ht != '없음':
            hashtag = ht.strip()
    # [포스트] 태그 제거
    if text.startswith('[포스트]'):
        text = text[len('[포스트]'):].strip()
    # 괄호 설명 태그 잔여물 제거 ("[어그로 첫 줄]" 등)
    text = re.sub(r'\[어그로[^\]]*\]\s*', '', text)
    text = re.sub(r'\[본문[^\]]*\]\s*', '', text)
    text = re.sub(r'\[마무리[^\]]*\]\s*', '', text)
    # 해시태그가 본문 안에 있으면 분리
    if not hashtag:
        ht_match = re.findall(r'#\S+', text)
        if ht_match:
            hashtag = ht_match[0]
    return text.strip(), hashtag


# ────── 콘텐츠 생성 ──────

@router.get("/notion-keywords")
async def threads_notion_keywords():
    headers = {
        'Authorization': 'Bearer %s' % NOTION_TOKEN,
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28',
    }
    payload = {
        'filter': {'and': [
            {'property': '배정 채널', 'multi_select': {'contains': '쓰레드'}},
            {'property': '상태', 'select': {'equals': '미사용'}},
        ]},
        'page_size': 100,
    }
    try:
        from src.services.notion_client import query_database
        data = query_database(KEYWORD_DB_ID, filter_obj=payload['filter'], page_size=100)
        keywords = []
        for page in data.get('results', []):
            props = page.get('properties', {})
            t = props.get('키워드', {}).get('title', [])
            kw = t[0]['text']['content'] if t else ''
            if kw:
                keywords.append({'keyword': kw, 'page_id': page['id']})
        return {'keywords': keywords}
    except Exception:
        return {'keywords': []}


@router.post("/generate")
async def threads_generate(request: Request):
    body = await request.json()
    post_type = body.get('type', 'daily')  # 'daily' or 'traffic'
    account_id = body.get('account_id', '')
    keywords = body.get('keywords', [])
    product = body.get('product', {})
    forbidden = body.get('forbidden', '')
    count = body.get('count', 3)
    ref_posts = body.get('ref_posts', [])
    selling_logic = body.get('selling_logic', 'shuffle')  # shuffle / sympathy / review

    data = _threads_load_accounts()
    acc = next((a for a in data['accounts'] if a['id'] == account_id), None)
    persona = acc.get('persona', {}) if acc else {'tone': '친근'}

    _sse = sse_dict

    async def generate():
      try:
        loop = asyncio.get_running_loop()
        if post_type == 'daily':
            total = count
            for idx in range(1, count + 1):
                if await request.is_disconnected():
                    print("[threads_generate] 클라이언트 연결 끊김, 생성 중단")
                    return
                yield _sse({'type': 'progress', 'msg': f'[{idx}/{total}] 일상글 생성 중...', 'cur': idx-1, 'total': total})
                sys_p, usr_p = _build_threads_daily_prompt(persona, ref_posts)
                raw = await loop.run_in_executor(executor, call_claude, sys_p, usr_p, 0.85)
                text, hashtag = _parse_threads_output(raw)
                full_text = f'{text}\n\n{hashtag}'.strip() if hashtag else text
                result = {'text': text, 'hashtag': hashtag, 'full_text': full_text, 'char_count': len(full_text), 'type': 'daily', 'num': idx}
                yield _sse({'type': 'result', 'data': result, 'cur': idx, 'total': total})
            yield _sse({'type': 'complete', 'total': total})
        else:
            total = len(keywords) * count
            idx = 0
            for kw_data in keywords:
                kw = kw_data if isinstance(kw_data, str) else kw_data.get('keyword', '')
                page_id = '' if isinstance(kw_data, str) else kw_data.get('page_id', '')
                for c in range(count):
                    if await request.is_disconnected():
                        print("[threads_generate] 클라이언트 연결 끊김, 생성 중단")
                        return
                    idx += 1
                    label = kw if count == 1 else f'{kw} (#{c+1})'
                    yield _sse({'type': 'progress', 'msg': f'[{idx}/{total}] {label} — 물길글 생성 중...', 'cur': idx-1, 'total': total})
                    sys_p, usr_p = _build_threads_traffic_prompt(kw, persona, product, forbidden, selling_logic)
                    raw = await loop.run_in_executor(executor, call_claude, sys_p, usr_p, 0.8)
                    text, hashtag = _parse_threads_output(raw)
                    full_text = f'{text}\n\n{hashtag}'.strip() if hashtag else text
                    result = {
                        'keyword': kw, 'text': text, 'hashtag': hashtag,
                        'full_text': full_text, 'char_count': len(full_text),
                        'type': 'traffic', 'page_id': page_id, 'num': c + 1,
                    }

                    # ── 검수 단계 (물길글만) ──
                    yield _sse({'type': 'progress', 'msg': f'[{idx}/{total}] {label} — 검수 중...', 'cur': idx-1, 'total': total})
                    review_result = await loop.run_in_executor(
                        executor, review_and_save, "threads", result, kw,
                    )
                    for ev in review_result.get("events", []):
                        yield _sse(ev)
                    result['review_status'] = review_result["status"]
                    result['review_passed'] = review_result["passed"]

                    yield _sse({'type': 'result', 'data': result, 'cur': idx, 'total': total})
            yield _sse({'type': 'complete', 'total': total})
      except Exception as e:
        print(f"[threads_generate] 에러: {e}")
        yield _sse({'type': 'error', 'message': f'쓰레드 생성 중 오류: {e}'})

    return SSEResponse(generate())


@router.post("/generate-comment")
async def threads_generate_comment(request: Request):
    """댓글 텍스트 생성"""
    body = await request.json()
    post_content = body.get('post_content', '')
    account_id = body.get('account_id', '')
    if not post_content:
        return JSONResponse({'error': '게시물 내용 필요'}, 400)
    data = _threads_load_accounts()
    acc = next((a for a in data['accounts'] if a['id'] == account_id), None)
    persona = acc.get('persona', {}) if acc else {'tone': '친근'}
    loop = asyncio.get_running_loop()
    sys_p, usr_p = _build_threads_comment_prompt(post_content, persona)
    raw = await loop.run_in_executor(executor, call_claude, sys_p, usr_p, 0.8)
    comments = []
    for line in raw.strip().split('\n'):
        line = line.strip()
        if line and line[0].isdigit() and '.' in line:
            comments.append(line.split('.', 1)[1].strip())
        elif line and not line.startswith('['):
            comments.append(line)
    return {'comments': comments[:5]}


# ────── 게시 ──────

def _threads_publish_post(access_token, user_id, text, reply_to=None):
    """Threads 공식 API 2단계 게시"""
    # 500자 제한
    if len(text) > 500:
        text = text[:497] + '...'
    # 1단계: 컨테이너 생성
    container_data = {'media_type': 'TEXT', 'text': text}
    if reply_to:
        container_data['reply_to_id'] = reply_to
    result = _threads_api(access_token, f'{user_id}/threads', 'POST', container_data)
    if not result.get('ok'):
        return result
    creation_id = result['data'].get('id', '')
    if not creation_id:
        return {'ok': False, 'error': 'container id 없음'}
    # 2초 대기 (컨테이너 처리)
    time.sleep(2)
    # 2단계: 게시
    pub_result = _threads_api(access_token, f'{user_id}/threads_publish', 'POST', {'creation_id': creation_id})
    return pub_result


@router.post("/publish")
async def threads_publish(request: Request):
    body = await request.json()
    account_id = body.get('account_id', '')
    text = body.get('text', '')
    reply_to = body.get('reply_to', None)
    if not text:
        return JSONResponse({'error': '텍스트 필요'}, 400)
    data = _threads_load_accounts()
    acc = next((a for a in data['accounts'] if a['id'] == account_id), None)
    if not acc or not acc.get('token', {}).get('access_token'):
        return JSONResponse({'error': '계정 미연결'}, 400)
    token = acc['token']['access_token']
    user_id = acc['token'].get('user_id', 'me')
    # 일일 카운터 체크
    today = datetime.now().strftime('%Y-%m-%d')
    if acc.get('daily_count_date') != today:
        acc['daily_count'] = 0
        acc['daily_count_date'] = today
    if acc['daily_count'] >= 250:
        return JSONResponse({'error': '일일 게시 한도 초과 (250건)'}, 429)

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(executor, _threads_publish_post, token, user_id, text, reply_to)
    if result.get('ok'):
        # Race Condition 방지: 최신 파일 읽고 해당 계정만 업데이트
        fresh = _threads_load_accounts()
        for fa in fresh['accounts']:
            if fa['id'] == account_id:
                today_str = datetime.now().strftime('%Y-%m-%d')
                if fa.get('daily_count_date') != today_str:
                    fa['daily_count'] = 0
                    fa['daily_count_date'] = today_str
                fa['daily_count'] = fa.get('daily_count', 0) + 1
                fa['last_publish_time'] = datetime.now().isoformat()
                break
        _threads_save_accounts(fresh)
    return result


# ────── Notion 저장 ──────

@router.post("/save-notion")
async def threads_save_notion(request: Request):
    body = await request.json()
    headers_n = {
        'Authorization': 'Bearer %s' % NOTION_TOKEN,
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28',
    }
    kw = body.get('keyword', '쓰레드')
    post_type = body.get('type', 'daily')
    type_label = '일상글' if post_type == 'daily' else '물길글'
    props = {
        '제목': {'title': [{'text': {'content': f'{kw} 쓰레드 {type_label}'}}]},
        '채널': {'select': {'name': '쓰레드'}},
        '생산 상태': {'select': {'name': '승인됨' if body.get('review_status') == 'approved' else '초안'}},
        '발행_상태': {'select': {'name': '미발행'}},
    }
    text = body.get('text', '')
    if text:
        props['본문'] = {'rich_text': [{'text': {'content': text[:2000]}}]}
    if body.get('page_id'):
        props['키워드'] = {'relation': [{'id': body['page_id']}]}
    payload = {'parent': {'database_id': CONTENT_DB_ID}, 'properties': props}
    if text:
        children = []
        for para in [p.strip() for p in text.split('\n\n') if p.strip()][:100]:
            for k in range(0, len(para), 2000):
                children.append({'object': 'block', 'type': 'paragraph',
                    'paragraph': {'rich_text': [{'type': 'text', 'text': {'content': para[k:k+2000]}}]}})
        payload['children'] = children[:100]
    try:
        from src.services.notion_client import create_page
        result = create_page(CONTENT_DB_ID, props, children=payload.get('children'))
        return {'success': result['success'], 'error': result.get('error', '')}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ────── 스케줄러 ──────

@router.post("/schedule")
async def threads_schedule_post(request: Request):
    """게시물을 스케줄 큐에 등록"""
    body = await request.json()
    queue = _threads_load_queue()
    item = {
        'id': str(uuid.uuid4())[:8],
        'account_id': body.get('account_id', ''),
        'text': body.get('text', ''),
        'type': body.get('type', 'daily'),
        'keyword': body.get('keyword', ''),
        'page_id': body.get('page_id', ''),
        'created_at': datetime.now().isoformat(),
        'scheduled_at': None,  # 스케줄러가 자동 배정
        'status': 'pending',  # pending / published / failed
    }
    queue['queue'].append(item)
    _threads_save_queue(queue)
    return {'ok': True, 'queue_id': item['id']}


@router.get("/queue")
async def threads_queue_list():
    queue = _threads_load_queue()
    return {'queue': queue.get('queue', [])}


@router.delete("/queue/{queue_id}")
async def threads_queue_delete(queue_id: str):
    queue = _threads_load_queue()
    queue['queue'] = [q for q in queue['queue'] if q['id'] != queue_id]
    _threads_save_queue(queue)
    return {'ok': True}


def _threads_refresh_token(acc):
    """만료 15일 전 장기 토큰 자동 갱신"""
    token = acc.get('token', {})
    access_token = token.get('access_token', '')
    expires_at = token.get('expires_at', '')
    if not access_token or not expires_at:
        return False
    try:
        exp = datetime.fromisoformat(expires_at)
        days_left = (exp - datetime.now()).days
        if days_left > 15:
            return False  # 아직 갱신 불필요
        # 장기 토큰 갱신 API 호출
        r = req.get('https://graph.threads.net/refresh_access_token', params={
            'grant_type': 'th_refresh_token',
            'access_token': access_token,
        }, timeout=15)
        if r.status_code == 200:
            new_data = r.json()
            acc['token']['access_token'] = new_data.get('access_token', access_token)
            new_expires = new_data.get('expires_in', 5184000)
            acc['token']['expires_at'] = (datetime.now() + timedelta(seconds=new_expires)).isoformat()
            print(f"[threads] 토큰 갱신 완료: {acc.get('username','')} (새 만료: {acc['token']['expires_at']})")
            return True
        else:
            print(f"[threads] 토큰 갱신 실패: {r.status_code} {r.text[:200]}")
            return False
    except Exception as e:
        print(f"[threads] 토큰 갱신 에러: {e}")
        return False


async def _threads_scheduler_tick():
    """APScheduler interval job 콜백 — 큐 확인 → 조건 맞으면 자동 게시."""
    try:
        now = datetime.now()
        hour = now.hour
        queue = _threads_load_queue()
        accounts_data = _threads_load_accounts()
        changed = False

        for item in queue.get('queue', []):
            if item['status'] != 'pending':
                continue
            acc_id = item['account_id']
            acc = next((a for a in accounts_data['accounts'] if a['id'] == acc_id), None)
            if not acc or not acc.get('token', {}).get('access_token'):
                continue
            schedule = acc.get('schedule', {})
            active_start, active_end = schedule.get('active_hours', [9, 22])
            daily_max = schedule.get('daily_posts', 3)
            min_interval = schedule.get('min_interval_hours', 3)

            # 활동 시간대 체크
            if hour < active_start or hour >= active_end:
                continue
            # 일일 한도 체크
            today = now.strftime('%Y-%m-%d')
            if acc.get('daily_count_date') != today:
                acc['daily_count'] = 0
                acc['daily_count_date'] = today
            if acc.get('daily_count', 0) >= daily_max:
                continue
            # 최소 간격 체크 (마지막 게시 시간)
            last_pub = acc.get('last_publish_time', '')
            if last_pub:
                try:
                    last_dt = datetime.fromisoformat(last_pub)
                    elapsed = (now - last_dt).total_seconds() / 3600
                    jitter = random.uniform(0, 0.5)
                    if elapsed < min_interval + jitter:
                        continue
                except Exception:
                    pass

            # 게시 실행
            token = acc['token']['access_token']
            user_id = acc['token'].get('user_id', 'me')
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(executor, _threads_publish_post, token, user_id, item['text'])
            if result.get('ok'):
                item['status'] = 'published'
                item['published_at'] = now.isoformat()
                item['post_id'] = result.get('data', {}).get('id', '')
                acc['daily_count'] = acc.get('daily_count', 0) + 1
                acc['last_publish_time'] = now.isoformat()
                changed = True
                print(f"[threads_scheduler] 게시 완료: {acc.get('username','')} - {item['text'][:30]}...")
            else:
                item['status'] = 'failed'
                item['error'] = result.get('error', '')[:200]
                changed = True

        if changed:
            _threads_save_queue(queue)
            fresh_data = _threads_load_accounts()
            for acc in accounts_data.get('accounts', []):
                for fresh_acc in fresh_data.get('accounts', []):
                    if fresh_acc['id'] == acc['id']:
                        fresh_acc['daily_count'] = acc.get('daily_count', 0)
                        fresh_acc['daily_count_date'] = acc.get('daily_count_date', '')
                        fresh_acc['last_publish_time'] = acc.get('last_publish_time', '')
                        if acc.get('token', {}).get('access_token'):
                            fresh_acc['token'] = acc['token']
                        break
            _threads_save_accounts(fresh_data)
    except Exception as e:
        print(f"[threads_scheduler] tick 에러: {e}")


async def _threads_token_refresh_tick():
    """APScheduler interval job 콜백 — 토큰 갱신 체크 (1시간마다)."""
    try:
        accounts_data = _threads_load_accounts()
        loop = asyncio.get_running_loop()
        token_changed = False
        for acc in accounts_data.get('accounts', []):
            if acc.get('token', {}).get('access_token'):
                refreshed = await loop.run_in_executor(executor, _threads_refresh_token, acc)
                if refreshed:
                    token_changed = True
        if token_changed:
            _threads_save_accounts(accounts_data)
    except Exception as e:
        print(f"[threads_scheduler] 토큰 갱신 에러: {e}")


async def start_threads_scheduler():
    """create_app() startup — APScheduler interval job 등록."""
    from src.services.scheduler_service import scheduler
    scheduler.add_job(
        _threads_scheduler_tick, 'interval',
        id='threads_queue_tick', seconds=60,
        replace_existing=True, misfire_grace_time=120,
    )
    scheduler.add_job(
        _threads_token_refresh_tick, 'interval',
        id='threads_token_refresh', hours=1,
        replace_existing=True, misfire_grace_time=600,
    )


# ────── 인사이트 ──────

@router.get("/insights")
async def threads_insights(post_id: str = '', account_id: str = ''):
    if not post_id or not account_id:
        return JSONResponse({'error': 'post_id, account_id 필요'}, 400)
    data = _threads_load_accounts()
    acc = next((a for a in data['accounts'] if a['id'] == account_id), None)
    if not acc or not acc.get('token', {}).get('access_token'):
        return JSONResponse({'error': '계정 미연결'}, 400)
    token = acc['token']['access_token']
    result = _threads_api(token, f'{post_id}/insights', data={
        'metric': 'views,likes,replies,reposts,quotes,shares'
    })
    return result
