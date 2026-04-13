"""카페바이럴 API 라우터"""
import os
import re
import json
import time
import uuid
import asyncio
import threading

import requests as req
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from src.services.sse_helper import sse_dict, SSEResponse

from src.services.config import executor, CONTENT_DB_ID, NOTION_TOKEN, VIRAL_ACCOUNTS_FILE
from src.services.common import error_response
from src.services.ai_client import call_claude
from src.services.review_service import review_and_save
from src.services.notion_client import notion_headers

router = APIRouter()

# ───────────────────────────── 계정 관리 ─────────────────────────────

_viral_lock = threading.RLock()


def _viral_load_raw():
    """lock 없이 파일 읽기 — 반드시 외부에서 _viral_lock을 잡고 호출"""
    if os.path.exists(VIRAL_ACCOUNTS_FILE):
        try:
            with open(VIRAL_ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {'accounts': []}


def _viral_save_raw(data):
    """lock 없이 파일 쓰기 — 반드시 외부에서 _viral_lock을 잡고 호출"""
    with open(VIRAL_ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _viral_load_accounts():
    """계정 목록 로드 (lock 포함 — 단독 호출용)"""
    with _viral_lock:
        return _viral_load_raw()


def _viral_save_accounts(data):
    """계정 목록 저장 (lock 포함 — 단독 호출용)"""
    with _viral_lock:
        _viral_save_raw(data)


def _viral_get_account(account_id):
    """ID로 계정 조회"""
    data = _viral_load_accounts()
    for acc in data['accounts']:
        if acc['id'] == account_id:
            return acc
    return None


def _viral_check_ready(account_id):
    """계정이 침투글(3단계) 실행 가능한 상태인지 체크
    - 일상글 5개 이상이어야 3단계 가능
    - 제품 언급 2회 이상이면 차단
    """
    acc = _viral_get_account(account_id)
    if not acc:
        return {'ready': False, 'reason': '계정을 찾을 수 없습니다.'}
    stage1_count = acc.get('stage1_count', 0)
    stage2_count = acc.get('stage2_count', 0)
    product_mentions = acc.get('product_mentions', {})

    errors = []
    if stage1_count < 5:
        errors.append(f'일상글이 {stage1_count}개입니다. 최소 5개 필요합니다. (현재 {5 - stage1_count}개 부족)')
    if stage1_count + stage2_count < 6:
        errors.append(f'총 활동글(일상+고민)이 {stage1_count + stage2_count}개입니다. 최소 6개 필요합니다.')

    return {'ready': len(errors) == 0, 'errors': errors, 'account': acc}


def _viral_check_product_limit(account_id, product_name):
    """해당 계정에서 특정 제품 언급 횟수 체크 (한 아이디당 1~2회 한계)"""
    acc = _viral_get_account(account_id)
    if not acc:
        return {'allowed': False, 'reason': '계정을 찾을 수 없습니다.'}
    mentions = acc.get('product_mentions', {})
    count = mentions.get(product_name, 0)
    if count >= 2:
        return {'allowed': False, 'reason': f'이 계정은 "{product_name}" 제품을 이미 {count}회 언급했습니다. (한계: 2회)', 'count': count}
    return {'allowed': True, 'count': count}


def _viral_record_activity(account_id, stage, product_name=''):
    """활동 기록 업데이트 (lock으로 전체 구간 보호)"""
    with _viral_lock:
        data = _viral_load_raw()
        for acc in data['accounts']:
            if acc['id'] == account_id:
                if stage == 1:
                    acc['stage1_count'] = acc.get('stage1_count', 0) + 1
                elif stage == 2:
                    acc['stage2_count'] = acc.get('stage2_count', 0) + 1
                elif stage == 3:
                    acc['stage3_count'] = acc.get('stage3_count', 0) + 1
                    if product_name:
                        mentions = acc.get('product_mentions', {})
                        mentions[product_name] = mentions.get(product_name, 0) + 1
                        acc['product_mentions'] = mentions
                acc['last_activity'] = time.strftime('%Y-%m-%d %H:%M')
                history = acc.get('history', [])
                history.append({
                    'stage': stage,
                    'product': product_name,
                    'date': time.strftime('%Y-%m-%d %H:%M'),
                })
                acc['history'] = history[-100:]
                break
        _viral_save_raw(data)


# ── 계정 관리 엔드포인트 ──

@router.get("/accounts")
async def viral_accounts_list():
    """계정 목록 조회"""
    return _viral_load_accounts()


@router.post("/accounts")
async def viral_accounts_add(request: Request):
    """계정 추가"""
    body = await request.json()
    with _viral_lock:
        data = _viral_load_accounts()
        acc = {
            'id': str(uuid.uuid4())[:8],
            'nickname': body.get('nickname', ''),
            'cafe_name': body.get('cafe_name', ''),
            'naver_id': body.get('naver_id', ''),
            'created': time.strftime('%Y-%m-%d'),
            'stage1_count': 0,
            'stage2_count': 0,
            'stage3_count': 0,
            'product_mentions': {},
            'last_activity': '',
            'history': [],
        }
        data['accounts'].append(acc)
        _viral_save_accounts(data)
    return {'ok': True, 'account': acc}


@router.put("/accounts/{acc_id}")
async def viral_accounts_update(acc_id: str, request: Request):
    """계정 수정"""
    body = await request.json()
    with _viral_lock:
        data = _viral_load_accounts()
        for acc in data['accounts']:
            if acc['id'] == acc_id:
                for k in ('nickname', 'cafe_name', 'naver_id'):
                    if k in body:
                        acc[k] = body[k]
                _viral_save_accounts(data)
                return {'ok': True, 'account': acc}
    return JSONResponse({'error': '계정 없음'}, 404)


@router.delete("/accounts/{acc_id}")
async def viral_accounts_delete(acc_id: str):
    """계정 삭제"""
    with _viral_lock:
        data = _viral_load_accounts()
        data['accounts'] = [a for a in data['accounts'] if a['id'] != acc_id]
        _viral_save_accounts(data)
    return {'ok': True}


@router.get("/accounts/{acc_id}/check")
async def viral_accounts_check(acc_id: str, product: str = ''):
    """계정 상태 체크 — 3단계 실행 가능 여부 + 제품 언급 한도"""
    ready = _viral_check_ready(acc_id)
    result = {**ready}
    if product:
        product_check = _viral_check_product_limit(acc_id, product)
        result['product_check'] = product_check
    return result


# ───────────────────────────── PROMPT BUILDERS ─────────────────────────────

def _build_viral_stage1_prompt(category, target='', topic=''):
    system = """너는 네이버 카페에 활동하는 평범한 회원이다.
카페에 올릴 짧은 일상글을 1개 작성한다.

[역할]
- 카페 내부 실제 회원처럼 행동하는 사람
- 광고주, 마케터, 홍보 담당자가 아닌 "그냥 일상을 나누는 사람"

[글 주제 범위]
- 일상 피로, 체력 관리, 육아, 수면, 날씨, 음식, 운동, 생활 고민 등
- 비상업적 주제만 허용
- 제품, 브랜드, 성분, 쇼핑 관련 내용 절대 금지

[톤 & 문체 규칙]
- 존댓말 + 따뜻한 대화체
- 문장 끝: "~했어요", "~하더라구요", "~인 것 같아요" 등 구어체
- 감정 표현: ㅎㅎ, ㅠㅠ, ;;, 👍 중 1~2개 자연스럽게 사용
- 문장 단락: 2~3문장씩 끊기
- 전체 길이: 3~5줄 이내 (짧고 가볍게)

[구조]
- 제목: 일상적 감정/상황을 담은 짧은 문장 (1줄)
- 본문: 일상 상황 묘사 → 가벼운 감정 표현 → 공감 유도 질문 or 마무리

[절대금지]
- 제품명, 브랜드명, 성분명 언급
- 광고 어투: "추천드려요", "꼭 써보세요", "이거 진짜 좋아요"
- 링크, 해시태그, 쇼핑몰 언급
- 정보 전달형 문체 (블로그 톤, 리뷰 톤)
- 같은 문장 구조 반복"""
    user = "다음 조건으로 카페 일상글을 작성해줘.\n\n- 타겟층: %s\n- 글 주제: %s\n\n위 조건에 맞는 카페 일상글을 제목과 본문으로 작성해줘." % (
        target or category, topic or '자유 (일상, 피로, 건강, 운동 등)')
    return system, user


def _build_viral_stage2_prompt(category, target_concern, product_category=''):
    system = """너는 네이버 카페에서 활동하는 평범한 회원이다.
생활 속 고민을 나누는 카페 글을 1개 작성한다.

[역할]
- 특정 고민을 가진 실제 카페 회원
- 광고주가 아닌, 진짜 고민을 가진 사람처럼 글을 쓰는 사람
- 해결책을 "광고"하는 것이 아니라, 경험을 "나누는" 톤

[글 구조] — 반드시 아래 순서를 따른다
1. 제목: 감정형 또는 공감형 문장 (예: "요즘 피로가 너무 심해서요ㅠㅠ")
2. 오프닝: 일상적 상황 묘사 (예: "애 재우고 나면 체력이 바닥이에요…")
3. 중반: 감정 공유 + 기존에 시도한 방법 (예: "커피도 마셔보고 비타민도 챙겨봤는데 그대로네요ㅠ")
4. 후반: 간접적 해결 언급 — 카테고리 수준만 (예: "친구가 알려준 영양제 먹고 좀 나아졌어요ㅎㅎ")
5. 마무리: 질문 또는 공감 유도 (예: "다들 피로할 땐 어떻게 관리하세요?")

[카테고리 언급 규칙]
- 제품명, 브랜드명 절대 금지
- "카테고리" 수준까지만 허용
  예시: "천연 성분 영양제", "수면 도움 제품", "두피관리제", "저자극 클렌저"
- 카테고리 언급은 후반부에서 1회만

[톤 & 문체 규칙]
- 존댓말 + 따뜻한 대화체
- 문장 끝: "~했어요", "~하더라구요", "~인 것 같아요" 등 구어체
- 감정 표현: ㅎㅎ, ㅠㅠ, ;;, 👍 중 1~2개 자연스럽게 사용
- 문장 단락: 2~3문장씩 끊기
- 전체 길이: 5줄 이하

[대화 흐름]
질문 → 공감 → 경험공유 → 마무리

[절대금지]
- 제품명, 브랜드명, 성분명(구체적 성분) 언급
- 광고 어투: "추천드려요", "꼭 써보세요", "이거 진짜 좋아요"
- 링크, 해시태그, 쇼핑몰 언급
- 정보 전달형 문체 (블로그 톤, 리뷰 톤)
- CTA (구매 유도, 검색 유도)
- 같은 문장 구조 반복"""
    user = "다음 조건으로 카페 고민글을 작성해줘.\n\n- 타겟층: %s\n- 고민 키워드: %s\n- 제품 카테고리: %s\n\n위 조건에 맞게, 제목과 본문을 작성해줘.\n제품명은 절대 쓰지 말고 카테고리만 언급해." % (
        category, target_concern, product_category or '건강기능식품')
    return system, user


def _build_viral_stage3_prompt(category, target_concern, brand_keyword, product_name, usp, ingredients='', product_category=''):
    system = """너는 네이버 카페에서 활동하는 평범한 회원이다.
카페 침투글(본문 1개)과 댓글 세트(4개)를 함께 작성한다.

[역할]
- 실제 카페 회원처럼 행동하는 사람
- 제품을 "홍보"하는 것이 아니라, 생활 경험을 "나누는" 사람
- 본문 작성자와 댓글 작성자는 각각 다른 사람이다

[본문 구조] — 반드시 아래 순서를 따른다
1. 제목: 감정형 또는 공감형 문장
2. 오프닝: 일상적 상황 + 고민 묘사
3. 중반: 감정 공유 + 기존 시도 방법
4. 후반: 경험 공유형으로 제품/카테고리 자연스럽게 언급
5. 마무리: 질문 또는 공감 유도

[본문 내 제품 언급 규칙]
- 제품명 또는 나만의 키워드를 본문에서 1회만 언급 가능
- 반드시 경험 공유형 톤으로 작성
- 홍보 톤 절대 금지 ("추천드려요", "꼭 써보세요")
- 예시:
  - "예전에 그냥 커피로 버텼는데 요즘은 천연 성분 들어간 거 꾸준히 챙기니까 확실히 덜 피곤하더라구요ㅎㅎ"
  - "저도 그거 먹고 있어요ㅎㅎ 처음엔 의심했는데 확실히 효과는 있는 것 같아요!"
  - "요즘은 이런 제품들 많더라구요. 직접 써보니까 괜찮아요 :)"

[댓글 세트 규칙] — 4개 댓글을 아래 흐름으로 작성한다
- 댓글1: 공감 반응 ("저도 그래요ㅠㅠ", "완전 공감이에요")
- 댓글2: 경험 공유 (카테고리 수준 — "저는 천연 성분 들어간 거 먹고 좀 괜찮아졌어요ㅎㅎ")
- 댓글3: 관심/질문 ("그거 혹시 어디서 보셨어요?", "저도 궁금해요")
- 댓글4: 자연스러운 정보 제공 — 여기서만 제품명 또는 나만의 키워드 1회 언급 가능
  (예: "저도 요즘 {제품명} 먹고 있는데 꽤 괜찮아요ㅎㅎ")

[댓글 포인트]
- 모든 댓글은 "공감 → 경험 → 자연스러운 연결" 구조
- 각 댓글은 서로 다른 사람이 쓴 것처럼 말투와 표현이 달라야 한다
- 제품명은 댓글 세트 전체에서 1회만 (댓글4에서만)
- 링크 절대 금지

[톤 & 문체 규칙]
- 존댓말 + 따뜻한 대화체
- 문장 끝: "~했어요", "~하더라구요", "~인 것 같아요" 등 구어체
- 감정 표현: ㅎㅎ, ㅠㅠ, ;;, 👍 중 1~2개 자연스럽게 사용
- 문장 단락: 2~3문장씩 끊기
- 본문 전체 길이: 5줄 이하
- 댓글 각각: 1~2문장

[절대금지]
- 광고 어투: "추천드려요", "꼭 써보세요", "이거 진짜 좋아요"
- 링크, 해시태그, 쇼핑몰 언급
- 반복 문체 (동일 문장 구조 복붙)
- 제품명 과다 노출 (본문+댓글 통틀어 최대 2회)
- CTA (구매 유도, 검색 유도, "한번 찾아보세요")
- 본문 작성자와 댓글 작성자가 같은 말투를 쓰는 것"""
    user = """다음 조건으로 카페 침투글(본문 + 댓글 4개 세트)을 작성해줘.

- 타겟층: %s
- 고민 키워드: %s
- 제품명: %s
- 나만의 키워드: %s
- USP: %s
- 주요 성분: %s
- 제품 카테고리: %s

위 조건에 맞게 본문 1개와 댓글 4개를 작성해줘.
본문에서 제품 언급은 경험형으로 1회만, 댓글에서는 댓글4에서만 1회.""" % (
        category, target_concern, product_name, brand_keyword, usp, ingredients, product_category or '건강기능식품')
    return system, user


# ───────────────────────────── PARSERS ─────────────────────────────

def _parse_viral_output(raw):
    """제목: / 본문: 형식 파싱"""
    title = ''
    body = ''
    lines = raw.strip().split('\n')
    body_lines = []
    in_body = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('제목:') or stripped.startswith('제목 :'):
            title = stripped.split(':', 1)[1].strip()
            in_body = False
        elif stripped.startswith('본문:') or stripped.startswith('본문 :'):
            body_start = stripped.split(':', 1)[1].strip()
            if body_start:
                body_lines.append(body_start)
            in_body = True
        elif in_body:
            body_lines.append(line)
        elif not title:
            title = stripped
            in_body = True
        else:
            body_lines.append(line)
    body = '\n'.join(body_lines).strip()
    if not body and not title:
        title = lines[0].strip() if lines else ''
        body = '\n'.join(lines[1:]).strip()
    return {'title': title, 'body': body}


def _parse_viral_stage3(raw):
    """3단계: 글(제목+본문) + 댓글 파싱"""
    result = {'title': '', 'body': '', 'comments': ''}
    parts = re.split(r'\[댓글\]|\[글\]', raw, flags=re.IGNORECASE)
    if len(parts) >= 2:
        post_part = parts[1] if len(parts) >= 3 else parts[0]
        comment_part = parts[-1] if len(parts) >= 2 else ''
        if len(parts) >= 3:
            post_part = parts[1]
            comment_part = parts[2]
        else:
            post_part = parts[0]
            comment_part = parts[1]
        parsed = _parse_viral_output(post_part)
        result['title'] = parsed['title']
        result['body'] = parsed['body']
        result['comments'] = comment_part.strip()
    else:
        parsed = _parse_viral_output(raw)
        result['title'] = parsed['title']
        result['body'] = parsed['body']
    return result


# ───────────────────────────── ENDPOINTS ─────────────────────────────

@router.post("/build-prompt")
async def viral_build_prompt(request: Request):
    """카페바이럴 프롬프트만 생성 (3단계 각각 claude.ai용)"""
    body = await request.json()
    category = body.get('category', '')
    product = body.get('product', {})
    results = []

    # 1단계: 일상글
    sys1, usr1 = _build_viral_stage1_prompt(category, product.get('target', ''), '')
    results.append({
        'name': '1단계 일상글',
        'system_prompt': sys1, 'user_prompt': usr1,
        'combined': f"다음 시스템 프롬프트의 역할을 수행해주세요.\n\n---\n\n{sys1}\n\n---\n\n{usr1}",
    })

    # 2단계: 고민글
    sys2, usr2 = _build_viral_stage2_prompt(category, product.get('target_concern', ''), product.get('product_category', ''))
    results.append({
        'name': '2단계 고민글',
        'system_prompt': sys2, 'user_prompt': usr2,
        'combined': f"다음 시스템 프롬프트의 역할을 수행해주세요.\n\n---\n\n{sys2}\n\n---\n\n{usr2}",
    })

    # 3단계: 침투글
    sys3, usr3 = _build_viral_stage3_prompt(
        category, product.get('target_concern', ''),
        product.get('brand_keyword', ''), product.get('name', ''),
        product.get('usp', ''), product.get('ingredients', ''),
        product.get('product_category', ''))
    results.append({
        'name': '3단계 침투글+댓글',
        'system_prompt': sys3, 'user_prompt': usr3,
        'combined': f"다음 시스템 프롬프트의 역할을 수행해주세요.\n\n---\n\n{sys3}\n\n---\n\n{usr3}",
    })

    return {'steps': results}


@router.post("/generate")
async def viral_generate(request: Request):
    """카페바이럴 세트 생성 (SSE)"""
    body = await request.json()
    category = body.get('category', '')
    product = body.get('product', {})
    set_count = body.get('set_count', 3)
    account_id = body.get('account_id', '')  # 계정 선택 (선택사항)
    target_concern = product.get('target_concern', '')
    brand_keyword = product.get('brand_keyword', '')
    product_name = product.get('name', '')
    usp = product.get('usp', '')
    ingredients = product.get('ingredients', '')
    product_category = product.get('product_category', '')

    _sse = sse_dict

    async def generate():
        try:
            loop = asyncio.get_running_loop()
            total_steps = set_count * 3

            # 계정 선택 시: 3단계 실행 전 체크
            if account_id:
                ready = _viral_check_ready(account_id)
                if not ready['ready']:
                    yield _sse({'type': 'error', 'message': '🚫 계정 상태 미충족: ' + ' / '.join(ready.get('errors', []))})
                    return
                if product_name:
                    prod_check = _viral_check_product_limit(account_id, product_name)
                    if not prod_check['allowed']:
                        yield _sse({'type': 'error', 'message': '🚫 ' + prod_check['reason']})
                        return

            for s in range(set_count):
                step_base = s * 3

                # 1단계: 일상글
                yield _sse({'type': 'progress', 'msg': '[세트 %d/%d] 1단계 일상글 생성 중...' % (s+1, set_count), 'cur': step_base, 'total': total_steps})
                sys1, usr1 = _build_viral_stage1_prompt(category, product.get('target', ''), '')
                raw1 = await loop.run_in_executor(executor, call_claude, sys1, usr1)
                s1 = _parse_viral_output(raw1)

                # 2단계: 대화침투글
                yield _sse({'type': 'progress', 'msg': '[세트 %d/%d] 2단계 대화침투글 생성 중...' % (s+1, set_count), 'cur': step_base+1, 'total': total_steps})
                sys2, usr2 = _build_viral_stage2_prompt(category, target_concern, product_category)
                raw2 = await loop.run_in_executor(executor, call_claude, sys2, usr2)
                s2 = _parse_viral_output(raw2)

                # 3단계: 제품인지글 + 댓글
                yield _sse({'type': 'progress', 'msg': '[세트 %d/%d] 3단계 제품인지글+댓글 생성 중...' % (s+1, set_count), 'cur': step_base+2, 'total': total_steps})
                sys3, usr3 = _build_viral_stage3_prompt(category, target_concern, brand_keyword, product_name, usp, ingredients, product_category)
                raw3 = await loop.run_in_executor(executor, call_claude, sys3, usr3)
                s3 = _parse_viral_stage3(raw3)

                result = {
                    'set_num': s + 1,
                    'stage1': s1,
                    'stage2': s2,
                    'stage3': s3,
                }

                # ── 검수 단계 ──
                yield _sse({'type': 'progress', 'msg': f'[세트 {s+1}/{set_count}] 검수 중...', 'cur': step_base+2, 'total': total_steps})
                review_result = await loop.run_in_executor(
                    executor, review_and_save, "cafe-viral", result, "",
                )
                for ev in review_result.get("events", []):
                    yield _sse(ev)
                result['review_status'] = review_result["status"]
                result['review_passed'] = review_result["passed"]

                # 계정 활동 기록 (검수 통과 시에만)
                if account_id and review_result.get("passed", False):
                    _viral_record_activity(account_id, 1)
                    _viral_record_activity(account_id, 2)
                    _viral_record_activity(account_id, 3, product_name)

                yield _sse({'type': 'result', 'data': result, 'cur': step_base+3, 'total': total_steps})

            yield _sse({'type': 'complete', 'total': set_count})
        except Exception as e:
            print(f"[viral_generate] 에러: {e}")
            yield _sse({'type': 'error', 'message': f'카페바이럴 생성 중 오류: {e}'})

    return SSEResponse(generate())


@router.post("/generate-stage")
async def viral_generate_stage(request: Request):
    """단계별 개별 생성 (1단계 일상글만, 2단계 고민글만 등)
    - account_id 필수
    - stage: 1, 2, 3
    - stage 3은 일상글 5개+고민글 1개 이상이어야 실행 가능
    """
    body = await request.json()
    stage = body.get('stage', 1)
    account_id = body.get('account_id', '')
    count = body.get('count', 1)  # 한 번에 몇 개 생성
    category = body.get('category', '')
    product = body.get('product', {})

    if not account_id:
        return JSONResponse({'error': '계정을 선택하세요.'}, 400)

    # 3단계 실행 전 체크
    if stage == 3:
        ready = _viral_check_ready(account_id)
        if not ready['ready']:
            return JSONResponse({'error': '3단계 실행 불가', 'reasons': ready.get('errors', [])}, 400)
        product_name = product.get('name', '')
        if product_name:
            prod_check = _viral_check_product_limit(account_id, product_name)
            if not prod_check['allowed']:
                return JSONResponse({'error': prod_check['reason']}, 400)

    _sse = sse_dict

    async def generate():
        try:
            loop = asyncio.get_running_loop()
            for i in range(count):
                if stage == 1:
                    yield _sse({'type': 'progress', 'msg': f'[{i+1}/{count}] 일상글 생성 중...'})
                    sys_p, usr_p = _build_viral_stage1_prompt(category, product.get('target', ''), '')
                    raw = await loop.run_in_executor(executor, call_claude, sys_p, usr_p)
                    result = _parse_viral_output(raw)
                    _viral_record_activity(account_id, 1)
                    yield _sse({'type': 'result', 'data': {'stage': 1, 'num': i+1, **result}})

                elif stage == 2:
                    yield _sse({'type': 'progress', 'msg': f'[{i+1}/{count}] 고민글 생성 중...'})
                    sys_p, usr_p = _build_viral_stage2_prompt(category, product.get('target_concern', ''), product.get('product_category', ''))
                    raw = await loop.run_in_executor(executor, call_claude, sys_p, usr_p)
                    result = _parse_viral_output(raw)
                    _viral_record_activity(account_id, 2)
                    yield _sse({'type': 'result', 'data': {'stage': 2, 'num': i+1, **result}})

                elif stage == 3:
                    yield _sse({'type': 'progress', 'msg': f'[{i+1}/{count}] 침투글+댓글 생성 중...'})
                    sys_p, usr_p = _build_viral_stage3_prompt(
                        category, product.get('target_concern', ''),
                        product.get('brand_keyword', ''), product.get('name', ''),
                        product.get('usp', ''), product.get('ingredients', ''),
                        product.get('product_category', ''))
                    raw = await loop.run_in_executor(executor, call_claude, sys_p, usr_p)
                    result = _parse_viral_stage3(raw)
                    # 검수 후 통과 시에만 활동 기록
                    yield _sse({'type': 'progress', 'msg': f'[{i+1}/{count}] 검수 중...'})
                    review_result = await loop.run_in_executor(
                        executor, review_and_save, "cafe-viral", {'stage3': result}, "",
                    )
                    for ev in review_result.get("events", []):
                        yield _sse(ev)
                    result['review_status'] = review_result["status"]
                    result['review_passed'] = review_result["passed"]
                    if review_result.get("passed", False):
                        _viral_record_activity(account_id, 3, product.get('name', ''))
                    yield _sse({'type': 'result', 'data': {'stage': 3, 'num': i+1, **result}})

            yield _sse({'type': 'complete', 'total': count})
        except Exception as e:
            yield _sse({'type': 'error', 'message': str(e)})

    return SSEResponse(generate())


@router.post("/accounts/{acc_id}/plan")
async def viral_create_plan(acc_id: str, request: Request):
    """2주 플랜 생성 — 멘토 가이드: 최소 2주에 걸쳐 1단계→2단계→3단계 진행
    일정 예시:
    - 1~3일차: 1단계 일상글 5개 (하루 1~2개)
    - 4~7일차: 댓글 교류 + 일상글 추가 2~3개
    - 8~10일차: 2단계 고민글 1~2개
    - 11~14일차: 3단계 침투글 1개
    """
    body = await request.json()
    acc = _viral_get_account(acc_id)
    if not acc:
        return JSONResponse({'error': '계정 없음'}, 404)

    start_date = body.get('start_date', time.strftime('%Y-%m-%d'))
    from datetime import datetime, timedelta
    start = datetime.strptime(start_date, '%Y-%m-%d')

    plan = [
        {'day': 1,  'date': (start + timedelta(days=0)).strftime('%Y-%m-%d'), 'task': '1단계 일상글 2개', 'stage': 1, 'count': 2},
        {'day': 2,  'date': (start + timedelta(days=1)).strftime('%Y-%m-%d'), 'task': '1단계 일상글 2개', 'stage': 1, 'count': 2},
        {'day': 3,  'date': (start + timedelta(days=2)).strftime('%Y-%m-%d'), 'task': '1단계 일상글 1개', 'stage': 1, 'count': 1},
        {'day': 4,  'date': (start + timedelta(days=3)).strftime('%Y-%m-%d'), 'task': '댓글 교류 (수동)', 'stage': 0, 'count': 0},
        {'day': 5,  'date': (start + timedelta(days=4)).strftime('%Y-%m-%d'), 'task': '1단계 일상글 1개 + 댓글 교류', 'stage': 1, 'count': 1},
        {'day': 6,  'date': (start + timedelta(days=5)).strftime('%Y-%m-%d'), 'task': '1단계 일상글 1개 + 댓글 교류', 'stage': 1, 'count': 1},
        {'day': 7,  'date': (start + timedelta(days=6)).strftime('%Y-%m-%d'), 'task': '댓글 교류 (수동)', 'stage': 0, 'count': 0},
        {'day': 8,  'date': (start + timedelta(days=7)).strftime('%Y-%m-%d'), 'task': '2단계 고민글 1개', 'stage': 2, 'count': 1},
        {'day': 9,  'date': (start + timedelta(days=8)).strftime('%Y-%m-%d'), 'task': '댓글 교류 (수동)', 'stage': 0, 'count': 0},
        {'day': 10, 'date': (start + timedelta(days=9)).strftime('%Y-%m-%d'), 'task': '2단계 고민글 1개', 'stage': 2, 'count': 1},
        {'day': 11, 'date': (start + timedelta(days=10)).strftime('%Y-%m-%d'), 'task': '댓글 교류 (수동)', 'stage': 0, 'count': 0},
        {'day': 12, 'date': (start + timedelta(days=11)).strftime('%Y-%m-%d'), 'task': '댓글 교류 (수동)', 'stage': 0, 'count': 0},
        {'day': 13, 'date': (start + timedelta(days=12)).strftime('%Y-%m-%d'), 'task': '3단계 침투글 1개', 'stage': 3, 'count': 1},
        {'day': 14, 'date': (start + timedelta(days=13)).strftime('%Y-%m-%d'), 'task': '일상글 1개 (이력 관리)', 'stage': 1, 'count': 1},
    ]

    # 계정에 플랜 저장 (lock으로 전체 구간 보호)
    with _viral_lock:
        data = _viral_load_raw()
        for a in data['accounts']:
            if a['id'] == acc_id:
                a['plan'] = plan
                a['plan_start'] = start_date
                break
        _viral_save_raw(data)

    return {'ok': True, 'plan': plan, 'account_id': acc_id}


@router.get("/accounts/{acc_id}/plan")
async def viral_get_plan(acc_id: str):
    """2주 플랜 조회"""
    acc = _viral_get_account(acc_id)
    if not acc:
        return JSONResponse({'error': '계정 없음'}, 404)
    plan = acc.get('plan', [])
    # 현재 진행 상황 표시
    today = time.strftime('%Y-%m-%d')
    for item in plan:
        if item['date'] < today:
            item['status'] = 'done'
        elif item['date'] == today:
            item['status'] = 'today'
        else:
            item['status'] = 'upcoming'
    return {'plan': plan, 'account': acc}


@router.post("/save-notion")
async def viral_save_notion(request: Request):
    """카페바이럴 단계별 노션 저장"""
    body = await request.json()
    headers_n = notion_headers()
    props = {
        '제목': {'title': [{'text': {'content': body.get('title', '')}}]},
        '채널': {'select': {'name': '카페'}},
        '생산 상태': {'select': {'name': '승인됨' if body.get('review_status') == 'approved' else '초안'}},
        '발행_상태': {'select': {'name': '미발행'}},
    }
    if body.get('body_summary'):
        props['본문'] = {'rich_text': [{'text': {'content': body['body_summary'][:2000]}}]}

    payload = {'parent': {'database_id': CONTENT_DB_ID}, 'properties': props}

    content_text = body.get('body', '')
    if body.get('comments'):
        content_text += '\n\n---\n댓글:\n' + body['comments']
    if content_text:
        children = []
        for para in [p.strip() for p in content_text.split('\n\n') if p.strip()][:100]:
            for k in range(0, len(para), 2000):
                children.append({
                    'object': 'block', 'type': 'paragraph',
                    'paragraph': {'rich_text': [{'type': 'text', 'text': {'content': para[k:k+2000]}}]}
                })
        payload['children'] = children[:100]

    try:
        from src.services.notion_client import create_page
        result = create_page(CONTENT_DB_ID, props, children=payload.get('children'))
        return {'success': result['success'], 'error': result.get('error', '')}
    except Exception as e:
        return {'success': False, 'error': str(e)}
