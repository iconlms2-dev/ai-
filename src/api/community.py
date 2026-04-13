"""커뮤니티 침투글 생성 + Notion 저장 + 계정 관리"""
import os
import json
import time
import uuid
import asyncio
import threading

import requests as req
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from src.services.sse_helper import sse_dict, SSEResponse

from src.services.config import executor, CONTENT_DB_ID, NOTION_TOKEN, BASE_DIR
from src.services.ai_client import call_claude
from src.services.review_service import review_and_save

router = APIRouter()

# ── 계정 관리 ──

COMMUNITY_ACCOUNTS_FILE = os.path.join(BASE_DIR, "community_accounts.json")
_cmt_lock = threading.RLock()


def _cmt_load_raw():
    """lock 없이 파일 읽기 — 반드시 외부에서 _cmt_lock을 잡고 호출"""
    if os.path.exists(COMMUNITY_ACCOUNTS_FILE):
        try:
            with open(COMMUNITY_ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {'accounts': []}


def _cmt_save_raw(data):
    """lock 없이 파일 쓰기 — 반드시 외부에서 _cmt_lock을 잡고 호출"""
    with open(COMMUNITY_ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _cmt_load_accounts():
    """lock 포함 파일 읽기 — 단독 호출용"""
    with _cmt_lock:
        return _cmt_load_raw()


def _cmt_save_accounts(data):
    """lock 포함 파일 쓰기 — 단독 호출용"""
    with _cmt_lock:
        _cmt_save_raw(data)


@router.get("/accounts")
async def community_accounts_list():
    """커뮤니티 계정 목록"""
    return _cmt_load_accounts()


@router.post("/accounts")
async def community_accounts_add(request: Request):
    """계정 추가"""
    body = await request.json()
    with _cmt_lock:
        data = _cmt_load_raw()
        acc = {
            'id': str(uuid.uuid4())[:8],
            'nickname': body.get('nickname', ''),
            'community': body.get('community', ''),
            'account_id': body.get('account_id', ''),
            'created': time.strftime('%Y-%m-%d'),
            'normal_activity_start': body.get('normal_activity_start', ''),
            'post_count': 0,
            'monthly_post_count': 0,
            'monthly_reset': time.strftime('%Y-%m'),
            'last_activity': '',
            'status': '숙성중',  # 숙성중 / 활동가능 / 침투가능
            'history': [],
            'deleted_posts': [],
        }
        data['accounts'].append(acc)
        _cmt_save_raw(data)
    return {'ok': True, 'account': acc}


@router.delete("/accounts/{acc_id}")
async def community_accounts_delete(acc_id: str):
    """계정 삭제"""
    with _cmt_lock:
        data = _cmt_load_raw()
        data['accounts'] = [a for a in data['accounts'] if a['id'] != acc_id]
        _cmt_save_raw(data)
    return {'ok': True}


@router.get("/accounts/{acc_id}/check")
async def community_accounts_check(acc_id: str):
    """계정 상태 체크 — 침투 가능 여부
    멘토 가이드: 최소 1~2주 일반 활동 후 침투글, 월 2~3개 글
    """
    from datetime import datetime
    with _cmt_lock:
        data = _cmt_load_raw()
        for acc in data['accounts']:
            if acc['id'] == acc_id:
                errors = []
                # D2: 1~2주 활동 체크
                if acc.get('normal_activity_start'):
                    try:
                        start = datetime.strptime(acc['normal_activity_start'], '%Y-%m-%d')
                        days = (datetime.now() - start).days
                        if days < 14:
                            errors.append(f'일반 활동 {days}일차입니다. 최소 14일(2주) 필요합니다. ({14-days}일 남음)')
                    except ValueError:
                        errors.append(f'normal_activity_start 날짜 형식 오류: {acc["normal_activity_start"]} (YYYY-MM-DD 필요)')
                else:
                    errors.append('일반 활동 시작일이 설정되지 않았습니다.')
                # D3: 월 2~3개 체크
                current_month = time.strftime('%Y-%m')
                if acc.get('monthly_reset') != current_month:
                    acc['monthly_post_count'] = 0
                    acc['monthly_reset'] = current_month
                    _cmt_save_raw(data)
                if acc.get('monthly_post_count', 0) >= 3:
                    errors.append(f'이번 달 침투글 {acc["monthly_post_count"]}개 작성. 월 최대 3개 권장.')
                return {'ready': len(errors) == 0, 'errors': errors, 'account': acc}
    return JSONResponse({'error': '계정 없음'}, status_code=404)


@router.post("/accounts/{acc_id}/record")
async def community_accounts_record(acc_id: str, request: Request):
    """활동 기록"""
    body = await request.json()
    activity_type = body.get('type', 'post')  # post / deleted
    with _cmt_lock:
        data = _cmt_load_raw()
        found = False
        for acc in data['accounts']:
            if acc['id'] == acc_id:
                found = True
                if activity_type == 'post':
                    acc['post_count'] = acc.get('post_count', 0) + 1
                    current_month = time.strftime('%Y-%m')
                    if acc.get('monthly_reset') != current_month:
                        acc['monthly_post_count'] = 0
                        acc['monthly_reset'] = current_month
                    acc['monthly_post_count'] = acc.get('monthly_post_count', 0) + 1
                elif activity_type == 'deleted':
                    # D5: 글 삭제 기록
                    acc['deleted_posts'] = acc.get('deleted_posts', [])
                    acc['deleted_posts'].append({
                        'date': time.strftime('%Y-%m-%d %H:%M'),
                        'note': body.get('note', ''),
                    })
                acc['last_activity'] = time.strftime('%Y-%m-%d %H:%M')
                acc['history'] = acc.get('history', [])
                acc['history'].append({
                    'type': activity_type,
                    'date': time.strftime('%Y-%m-%d %H:%M'),
                })
                acc['history'] = acc['history'][-100:]
                break
        if not found:
            return JSONResponse({'error': '계정 없음'}, status_code=404)
        _cmt_save_raw(data)
    return {'ok': True}

# ── 톤 & 전략 상수 ──

COMMUNITY_TONES = {
    '뽐뿌': '"이거 써봤는데" 후기형 + 사진 3장+ 언급. 광고 감시 강함. 중간 길이(500~1000자).',
    '디시인사이드': '짧고 솔직한 디시 특유 말투, 유동닉 스타일. 광고 적대적. 짧게(200~500자).',
    '에펨코리아': '디시와 유사하나 약간 더 정리된 톤. 과한 홍보 금지. 짧게(200~500자).',
    '클리앙': '분석적, IT/가전 특화 톤. 분석 없는 단순 추천은 무시당함. 중간(500~1000자).',
    '맘스홀릭': '따뜻한 존댓말, 엄마 입장 공감. 구매력 높지만 광고 감지력도 높음. 중간(500~1000자).',
    '더쿠': '연예·뷰티 톤, "~인데" "~이더라" 식. 광고 티 나면 집단 공격. 짧게(200~500자).',
    '인스티즈': '연예·뷰티 톤, 가벼운 대화체. 짧게(200~500자).',
    '화해': '성분 리뷰 특화, 분석적 톤. 성분 근거 없으면 신뢰 안 됨. 중간(500~1000자).',
    '블라인드': '직장인 톤, 간결하고 실용적. 광고 적대적. 짧게(200~500자).',
    '루리웹': '게임/서브컬처/IT 톤, 10~30대 남성, 반말. 광고 적대적. 짧게(200~500자).',
}

STRATEGY_NAME = {
    '1': '고민 공감 + 체험 후기형',
    '2': '추천 요청형 (낚시)',
    '3': '비교 리뷰형',
    '4': '자기 제품 까기 (역발상)',
    '5': '논쟁 유도형 (계정 농사)',
    '6': '정보 제공자 포지션 (전문가 행세)',
}


# ── 헬퍼 함수 ──

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


def _build_benchmark_reference_block(community, keyword=None):
    """커뮤니티 인기글 벤치마킹 결과를 user 프롬프트 참고 블록으로 생성.

    실패 시 빈 문자열 반환 — 기존 COMMUNITY_TONES 하드코딩으로 fallback.
    크롤링이므로 시간이 오래 걸릴 수 있음 — max_posts=2로 제한.
    """
    try:
        from src.services.benchmark import crawl_community_references
        refs = crawl_community_references(community, max_posts=2, keyword=keyword)
        if not refs:
            return ""
        lines = [
            "",
            "---",
            f"[참고 레퍼런스: {community} 최근 인기글]",
            "아래는 현재 해당 커뮤니티에서 반응이 좋은 글의 예시입니다.",
            "톤과 길이를 참고하되, 위의 작성 규칙이 항상 우선합니다.",
            "",
        ]
        for i, ref in enumerate(refs, 1):
            title = ref.get("title", "")
            comments = ref.get("comments", 0)
            body = ref.get("body_preview", "")
            lines.append(f'예시{i}: "{title}" (댓글 {comments}개)')
            if body:
                lines.append(f"> {body}...")
            lines.append("")
        return "\n".join(lines)
    except Exception:
        return ""


def _build_community_post_prompt(community, strategy, keyword, appeal, buying_one, product, forbidden):
    brand_kw = product.get('brand_keyword', '')
    strategy_label = STRATEGY_NAME.get(strategy, strategy)
    system = """너는 온라인 커뮤니티에 자연스럽게 침투하는 체험 공유 글을 작성하는 마케팅 전문가다.

광고 글이 아닌, '진짜 사용자'처럼 보이는 체험 공유 글을 작성해야 한다.
"우리 제품 좋아요 구매하세요" 같은 직접 광고는 즉시 삭제 + 차단 + 네거티브 역효과로 이어진다.

---

[글 유형 — 지정된 유형에 맞춰 작성]

● 유형1: 고민 공감 + 체험 후기형
- 고민 공감으로 시작 → 공감 유도
- 여러 제품 써본 경험 → 객관성 확보
- 나만의 키워드 1회만 자연스럽게 삽입
- 마무리를 '질문'으로 → 댓글 유도 → 글 활성화
- 예시 제목: "탈모 때문에 이것저것 써봤는데 요즘 쓰는 거 공유합니다"

● 유형2: 추천 요청형 (낚시)
- 추천 요청 형태의 자연스러운 질문
- 나만의 키워드를 '들어본 적 있다' 수준으로 언급
- 댓글에서 다른 계정이 "나 써봤는데 괜찮았어" 답변할 수 있는 구조
- 예시 제목: "다이어트 보조제 추천 좀…"

● 유형3: 비교 리뷰형
- 3개 제품 비교 형식 → 정보 가치가 높아 삭제 안 됨
- 내 제품을 3개 중 1개로 자연스럽게 포함
- "개인 의견" 면책 문구 포함
- 예시 제목: "[미니 리뷰] 모공앰플 3종 비교 (A / B / C)"

● 유형4: 자기 제품 까기 (역발상)
- 단점을 먼저 말하면 "광고면 단점을 말하겠어?" → 진짜 사용자로 인식
- 단점은 사소하게(향, 가격), 장점은 구체적으로
- "세일 때 사라" 식으로 구매 유도하면서 광고 안 티남

● 유형5: 논쟁 유도형 (계정 농사)
- 제품 카테고리 관련 토론 글을 올림 (예: "솔직히 탈모샴푸가 효과 있긴 한 거임?")
- 이런 글은 댓글이 폭발함 (커뮤니티는 논쟁을 좋아함)
- 핵심: 글 작성자 본인이 아닌, 댓글에서 다른 사람이 키워드를 언급해야 자연스러움
- 원글에서는 제품을 언급하지 않고, 댓글에서만 나만의 키워드 1회 등장

● 유형6: 정보 제공자 포지션 (전문가 행세)
- 해당 카테고리의 정보글/비교글/정리글을 작성 (내 제품은 안 넣음)
- 예: "탈모샴푸 10종 성분 비교 정리해봤다", "다이어트 보조제 FDA 인증 여부 확인법"
- 이런 글을 올리면 "이 사람은 이 분야를 아는 사람" 인식 형성
- 나중에 추천 요청이 오면 "전에 비교글 올렸는데, 개인적으로는 {{키워드}} 조합이 제일 괜찮았음" 식으로 답변

---

[커뮤니티별 톤 매칭 — 반드시 해당 커뮤니티 말투에 맞출 것]

● 뽐뿌: "이거 써봤는데" 후기형, 30~50대 남녀, 가성비 강조, 사진 3장+ 언급
● 디시인사이드: 짧고 솔직한 톤, 반말, "~임/~함/~ㅋㅋ" 체, 질문형이 안전
● 에펨코리아: IT/일상 톤, 반말, 디시보다 약간 부드러움
● 클리앙: 분석적/논리적 톤, 존댓말, 성분/스펙 비교 선호
● 맘스홀릭: 육아맘 톤, 존댓말, 공감 중심, 가족 상황 언급
● 더쿠/인스티즈: 여성 커뮤 톤, 반말/존댓말 혼용, 가벼운 리뷰
● 화해: 성분 중심 리뷰, 분석적 톤, 존댓말
● 블라인드: 직장인 톤, 존댓말, 현실적 고민 공유
● 루리웹: 게임/서브컬처/IT 톤, 반말, 10~30대 남성

---

[타이밍 활용 — 시즌/이슈 편승]
- 환절기: "요즘 두피 미쳤다… 다들 뭐 쓰냐"
- 여름 전: "다이어트 시작해야 하는데 뭐부터 하냐"
- 블프/연말 세일: "블프 때 뭐 살 거 정해놨음?" → 제품 자연 언급
- 언론 기사 이슈: "탈모 20대 급증이라는데 ㄹㅇ?" → 관련 제품 대화
- 시즌 글에 편승해서 댓글로 끼어들면 광고 의심을 거의 안 받음

[작성 규칙]
- 광고 티 절대 금지 (조금이라도 나면 '홍보충' 낙인)
- 브랜드명 직접 언급 금지
- 나만의 키워드는 글당 1회만 자연스럽게 삽입
- 직접 링크 삽입 금지 → 키워드 검색 유도
- 제목과 본문 모두 출력
- 해당 커뮤니티에서 실제로 올라올 법한 글처럼 작성

[출력 형식]
제목: (내용)

본문:
(내용)"""

    forbidden_line = ("\n금칙어: %s" % forbidden) if forbidden else ''
    user = """[커뮤니티]
%s

[글 유형]
%s

[제품 정보]
제품명: %s
USP: %s
타겟층: %s
주요 성분: %s
소구점: %s
구매원씽: %s%s

[나만의 키워드]
%s""" % (community, strategy_label, product.get('name',''), product.get('usp',''),
         product.get('target',''), product.get('ingredients',''),
         appeal, buying_one, forbidden_line, brand_kw)

    # 벤치마킹 레퍼런스 추가 (user 프롬프트에만 — 시스템 프롬프트 미수정)
    bench_ref = _build_benchmark_reference_block(community, keyword)
    if bench_ref:
        user += bench_ref

    return system, user


def _build_community_comments_prompt(community, post_body, brand_kw):
    tone = COMMUNITY_TONES.get(community, '')
    system = """역할: 커뮤니티 침투글에 달릴 자연스러운 자작 댓글을 작성하는 작가.

목표: 침투글에 대한 자작 댓글 1~2개를 생성한다. 다른 계정이 쓴 것처럼 보여야 한다.

커뮤니티 톤: %s

작성 규칙:
1. 댓글 1~2개 (과하면 의심)
2. 원글 작성자와 완전히 다른 사람의 톤
3. 나만의 키워드는 댓글 전체에서 1회만 (원글에서 이미 언급된 경우 안 써도 됨)
4. 공감형 or "나도 써봤는데" 경험 공유형

출력 형식:
[댓글 1] ...
[댓글 2] ...

금지사항:
- 원글과 같은 톤/말투 사용 금지
- 링크·광고 어투·과도한 칭찬 금지""" % tone
    user = "침투글 본문: %s\n나만의 키워드: %s" % (post_body[:2000], brand_kw)
    return system, user


# ── 엔드포인트 ──

@router.post("/build-prompt")
async def community_build_prompt(request: Request):
    """커뮤니티 프롬프트만 생성 (침투글+댓글 claude.ai용)"""
    body = await request.json()
    keywords = body.get('keywords', [])
    community = body.get('community', '')
    strategy = body.get('strategy', '1')
    product = body.get('product', {})
    appeal = body.get('appeal', '')
    buying_one = body.get('buying_one', '')
    forbidden = body.get('forbidden', '')
    results = []

    for kw in keywords:
        keyword = kw if isinstance(kw, str) else kw.get('keyword', '')

        # 침투글 프롬프트
        sys1, usr1 = _build_community_post_prompt(community, strategy, keyword, appeal, buying_one, product, forbidden)
        # 댓글 프롬프트
        sys2, usr2 = _build_community_comments_prompt(community, '(침투글 본문은 위에서 생성한 결과를 넣어주세요)', product.get('brand_keyword', ''))

        results.append({
            'keyword': keyword,
            'community': community,
            'post_prompt': {
                'system_prompt': sys1, 'user_prompt': usr1,
                'combined': f"다음 시스템 프롬프트의 역할을 수행해주세요.\n\n---\n\n{sys1}\n\n---\n\n{usr1}",
            },
            'comments_prompt': {
                'system_prompt': sys2, 'user_prompt': usr2,
                'combined': f"다음 시스템 프롬프트의 역할을 수행해주세요.\n\n---\n\n{sys2}\n\n---\n\n{usr2}",
            },
        })

    return {'results': results}


@router.post("/generate")
async def community_generate(request: Request):
    body = await request.json()
    keywords = body.get('keywords', [])
    community = body.get('community', '')
    strategy = body.get('strategy', '1')
    product = body.get('product', {})
    appeal = body.get('appeal', '')
    buying_one = body.get('buying_one', '')
    forbidden = body.get('forbidden', '')
    include_comments = body.get('include_comments', True)

    _sse = sse_dict

    async def generate():
      try:
        loop = asyncio.get_running_loop()
        total = len(keywords)
        for i, kw in enumerate(keywords):
            keyword = kw if isinstance(kw, str) else kw.get('keyword', '')
            page_id = '' if isinstance(kw, str) else kw.get('page_id', '')

            # STEP 1: 침투글
            yield _sse({'type': 'progress', 'msg': '[%d/%d] %s — 침투글 생성 중...' % (i+1, total, keyword), 'cur': i, 'total': total})
            sys1, usr1 = _build_community_post_prompt(community, strategy, keyword, appeal, buying_one, product, forbidden)
            raw = await loop.run_in_executor(executor, call_claude, sys1, usr1)
            parsed = _parse_viral_output(raw)

            # STEP 2: 자작 댓글
            comments = ''
            if include_comments:
                yield _sse({'type': 'progress', 'msg': '[%d/%d] %s — 자작 댓글 생성 중...' % (i+1, total, keyword), 'cur': i, 'total': total})
                sys2, usr2 = _build_community_comments_prompt(community, parsed['body'], product.get('brand_keyword', ''))
                comments = await loop.run_in_executor(executor, call_claude, sys2, usr2)
                comments = comments.strip()

            result = {
                'keyword': keyword, 'community': community, 'strategy': strategy,
                'title': parsed['title'], 'body': parsed['body'], 'comments': comments,
                'page_id': page_id,
            }

            # ── 검수 단계 ──
            yield _sse({'type': 'progress', 'msg': f'[{i+1}/{total}] {keyword} — 검수 중...', 'cur': i, 'total': total})
            review_result = await loop.run_in_executor(
                executor, review_and_save, "community", result, keyword,
            )
            for ev in review_result.get("events", []):
                yield _sse(ev)
            result['review_status'] = review_result["status"]
            result['review_passed'] = review_result["passed"]

            yield _sse({'type': 'result', 'data': result, 'cur': i+1, 'total': total})
        yield _sse({'type': 'complete', 'total': total})
      except Exception as e:
        print(f"[community_generate] 에러: {e}")
        yield _sse({'type': 'error', 'message': f'커뮤니티 침투글 생성 중 오류: {e}'})

    return SSEResponse(generate())


@router.post("/save-notion")
async def community_save_notion(request: Request):
    body = await request.json()
    if not body.get('review_passed', True):
        return {'success': False, 'error': '검수 미통과 콘텐츠는 저장할 수 없습니다.'}
    headers_n = {
        'Authorization': 'Bearer %s' % NOTION_TOKEN,
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28',
    }
    props = {
        '제목': {'title': [{'text': {'content': body.get('title', '')}}]},
        '채널': {'select': {'name': '커뮤니티'}},
        '생산 상태': {'select': {'name': '승인됨' if body.get('review_status') == 'approved' else '초안'}},
        '발행_상태': {'select': {'name': '미발행'}},
    }
    if body.get('body'):
        props['본문'] = {'rich_text': [{'text': {'content': body['body'][:2000]}}]}
    if body.get('page_id'):
        props['키워드'] = {'relation': [{'id': body['page_id']}]}
    payload = {'parent': {'database_id': CONTENT_DB_ID}, 'properties': props}
    full = body.get('body', '')
    if body.get('comments'):
        full += '\n\n---\n자작 댓글:\n' + body['comments']
    if full:
        children = []
        for para in [p.strip() for p in full.split('\n\n') if p.strip()][:100]:
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
