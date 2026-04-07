"""카페바이럴 API 라우터"""
import re
import json
import asyncio

import requests as req
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from src.services.config import executor, CONTENT_DB_ID, NOTION_TOKEN
from src.services.common import error_response
from src.services.ai_client import call_claude
from src.services.notion_client import notion_headers

router = APIRouter()


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
- 반드시 경험 공유형 톤으로 ("~먹어보고 있는데 괜찮은 것 같아요")
- 홍보 톤 절대 금지 ("추천드려요", "꼭 써보세요")

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

@router.post("/generate")
async def viral_generate(request: Request):
    """카페바이럴 세트 생성 (SSE)"""
    body = await request.json()
    category = body.get('category', '')
    product = body.get('product', {})
    set_count = body.get('set_count', 3)
    target_concern = product.get('target_concern', '')
    brand_keyword = product.get('brand_keyword', '')
    product_name = product.get('name', '')
    usp = product.get('usp', '')
    ingredients = product.get('ingredients', '')
    product_category = product.get('product_category', '')

    def _sse(obj):
        return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"

    async def generate():
      try:
        loop = asyncio.get_running_loop()
        total_steps = set_count * 3

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
            yield _sse({'type': 'result', 'data': result, 'cur': step_base+3, 'total': total_steps})

        yield _sse({'type': 'complete', 'total': set_count})
      except Exception as e:
        print(f"[viral_generate] 에러: {e}")
        yield _sse({'type': 'error', 'message': f'카페바이럴 생성 중 오류: {e}'})

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/save-notion")
async def viral_save_notion(request: Request):
    """카페바이럴 단계별 노션 저장"""
    body = await request.json()
    headers_n = notion_headers()
    props = {
        '제목': {'title': [{'text': {'content': body.get('title', '')}}]},
        '채널': {'select': {'name': '카페'}},
        '생산 상태': {'select': {'name': '초안'}},
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
        r = req.post('https://api.notion.com/v1/pages', headers=headers_n, json=payload, timeout=15)
        return {'success': r.status_code == 200, 'error': '' if r.status_code == 200 else r.text[:300]}
    except Exception as e:
        return {'success': False, 'error': str(e)}
