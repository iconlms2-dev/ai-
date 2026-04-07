"""커뮤니티 침투글 생성 + Notion 저장"""
import json
import asyncio

import requests as req
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from src.services.config import executor, CONTENT_DB_ID, NOTION_TOKEN
from src.services.ai_client import call_claude
from src.services.review_service import review_and_save

router = APIRouter()

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
}

STRATEGY_NAME = {
    '1': '고민 공감 + 체험 후기형',
    '2': '추천 요청형 (낚시)',
    '3': '비교 리뷰형',
    '4': '자기 제품 까기 (역발상)',
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

---

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

    def _sse(obj):
        return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"

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

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/save-notion")
async def community_save_notion(request: Request):
    body = await request.json()
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
        r = req.post('https://api.notion.com/v1/pages', headers=headers_n, json=payload, timeout=15)
        return {'success': r.status_code == 200, 'error': '' if r.status_code == 200 else r.text[:300]}
    except Exception as e:
        return {'success': False, 'error': str(e)}
