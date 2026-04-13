"""틱톡 숏폼 스크립트 생성"""
import json
import asyncio

import requests as req
from fastapi import APIRouter, Request
from src.services.sse_helper import sse_dict, SSEResponse

from src.services.config import executor, KEYWORD_DB_ID, CONTENT_DB_ID, NOTION_TOKEN
from src.services.ai_client import call_claude
from src.services.review_service import review_and_save

router = APIRouter()


# ── helpers ──────────────────────────────────────────────────────────

def _build_tiktok_prompt(keyword, appeal, buying_one, product, forbidden):
    brand_kw = product.get('brand_keyword', '')
    system = """역할: 틱톡 숏폼 영상의 스크립트를 작성하는 바이럴 콘텐츠 전문가.

목표: 제품의 소구점과 타겟 고민을 기반으로, 틱톡에서 자연스럽게 시청되고 검색 유도 효과를 만드는 숏폼 영상 스크립트 1개를 생성한다. UGC(User Generated Content) 스타일 — 실제 사용자가 찍은 듯한 자연스러운 톤이 핵심.

스크립트 구조 (15~30초 분량):

[1. 후킹] (0~3초)
- 시청자의 스크롤을 멈추게 하는 첫 문장
- 부정 편향 or 궁금증 자극 or 충격적 사실
- 소구점의 구매원씽에서 파생된 결핍 언어 사용

[2. 문제 공감] (3~10초)
- 타겟이 겪는 구체적 상황/증상 묘사
- 혼잣말 톤: "나도 진짜 이거 때문에 미치는 줄…"
- 기존에 시도했던 방법 + 실패 경험 간략히

[3. 전환점] (10~20초)
- 해결 계기를 자연스럽게 소개
- 나만의 키워드를 1회 자연스럽게 삽입
- 구체적 변화 언급: 기간 + 체감 효과

[4. 마무리] (20~30초)
- 간결한 결과 요약
- 검색 유도: "궁금하면 {나만의 키워드} 검색해봐"
- 또는 댓글 유도: "나만 이런 거 아니지…?"

작성 규칙:
[톤과 말투]
- 자연스러운 구어체. 친구한테 말하듯이.
- 혼잣말 톤 중심: "~~했음", "~~뒤집어짐ㅠㅠ"
- 딱딱하거나 격식 있는 표현 금지
- 이모티콘/감정 표현 자연스럽게 사용

[길이] 공백 제외 200~400자. 짧고 임팩트 있게.

[제품 노출]
- 나만의 키워드를 스크립트 안에 1회만 자연스럽게 포함
- 제품명 직접 언급 금지 (나만의 키워드만 사용)
- 해시태그·구매링크 금지

[영상 연출 가이드]
- 스크립트 옆에 [연출: ...] 메모를 간단히 표기

출력 형식:
[후킹] (0~3초)
(대사)
[연출: ...]

[문제 공감] (3~10초)
(대사)
[연출: ...]

[전환점] (10~20초)
(대사)
[연출: ...]

[마무리] (20~30초)
(대사)
[연출: ...]

금지사항:
- "강추", "인생템", "꼭 사세요" 등 광고 어투 금지
- 구매 링크·쇼핑몰 언급 금지
- 나만의 키워드 2회 이상 사용 금지
- 제품명(브랜드명) 직접 언급 금지
- 스튜디오 촬영 느낌 금지 — UGC 느낌 유지
"""

    user = "메인 키워드: %s\n소구점: %s\n구매원씽: %s\n제품명: %s\n주요 성분: %s\n핵심 특징: %s\n타겟층: %s\n나만의 키워드: %s" % (
        keyword, appeal, buying_one,
        product.get('name', ''), product.get('ingredients', ''),
        product.get('usp', ''), product.get('target', ''), brand_kw)
    return system, user


# ── endpoints ────────────────────────────────────────────────────────

@router.get("/notion-keywords")
async def tiktok_notion_keywords():
    headers = {
        'Authorization': 'Bearer %s' % NOTION_TOKEN,
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28',
    }
    payload = {
        'filter': {'and': [
            {'property': '배정 채널', 'multi_select': {'contains': '틱톡'}},
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
    except Exception as e:
        return {'keywords': []}


@router.post("/generate")
async def tiktok_generate(request: Request):
    body = await request.json()
    keywords = body.get('keywords', [])
    product = body.get('product', {})
    appeal = body.get('appeal', '')
    buying_one = body.get('buying_one', '')
    forbidden = body.get('forbidden', '')
    count = body.get('count', 1)

    _sse = sse_dict

    async def generate():
      try:
        loop = asyncio.get_running_loop()
        total = len(keywords) * count
        idx = 0
        for kw_data in keywords:
            kw = kw_data['keyword']
            for c in range(count):
                idx += 1
                label = '%s' % kw if count == 1 else '%s (#%d)' % (kw, c+1)
                yield _sse({'type': 'progress', 'msg': '[%d/%d] %s — 스크립트 생성 중...' % (idx, total, label), 'cur': idx-1, 'total': total})
                sys_p, usr_p = _build_tiktok_prompt(kw, appeal, buying_one, product, forbidden)
                script = await loop.run_in_executor(executor, call_claude, sys_p, usr_p)
                script = script.strip()
                result = {
                    'keyword': kw, 'script': script,
                    'page_id': kw_data.get('page_id', ''),
                    'num': c + 1,
                }

                # ── 검수 단계 ──
                yield _sse({'type': 'progress', 'msg': f'[{idx}/{total}] {label} — 검수 중...', 'cur': idx-1, 'total': total})
                review_result = await loop.run_in_executor(
                    executor, review_and_save, "tiktok", result, kw,
                )
                for ev in review_result.get("events", []):
                    yield _sse(ev)
                result['review_status'] = review_result["status"]
                result['review_passed'] = review_result["passed"]

                yield _sse({'type': 'result', 'data': result, 'cur': idx, 'total': total})
        yield _sse({'type': 'complete', 'total': total})
      except Exception as e:
        print(f"[tiktok_generate] 에러: {e}")
        yield _sse({'type': 'error', 'message': f'틱톡 스크립트 생성 중 오류: {e}'})

    return SSEResponse(generate())


@router.post("/save-notion")
async def tiktok_save_notion(request: Request):
    body = await request.json()
    headers_n = {
        'Authorization': 'Bearer %s' % NOTION_TOKEN,
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28',
    }
    kw = body.get('keyword', '')
    props = {
        '제목': {'title': [{'text': {'content': '%s 틱톡 스크립트' % kw}}]},
        '채널': {'select': {'name': '틱톡'}},
        '생산 상태': {'select': {'name': '승인됨' if body.get('review_status') == 'approved' else '초안'}},
        '발행_상태': {'select': {'name': '미발행'}},
    }
    script = body.get('script', '')
    if script:
        props['본문'] = {'rich_text': [{'text': {'content': script[:2000]}}]}
    if body.get('page_id'):
        props['키워드'] = {'relation': [{'id': body['page_id']}]}
    payload = {'parent': {'database_id': CONTENT_DB_ID}, 'properties': props}
    if script:
        children = []
        for para in [p.strip() for p in script.split('\n\n') if p.strip()][:100]:
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
