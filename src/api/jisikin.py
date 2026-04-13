"""지식인 API 라우터"""
import re
import json
import asyncio

import requests as req
from fastapi import APIRouter, Request
from src.services.sse_helper import sse_dict, SSEResponse

from src.services.config import executor, KEYWORD_DB_ID, CONTENT_DB_ID, NOTION_TOKEN
from src.services.common import error_response
from src.services.ai_client import call_claude
from src.services.review_service import review_and_save
from src.services.notion_client import notion_query_all, extract_prop, notion_headers

router = APIRouter()


# ───────────────────────────── PROMPT BUILDERS ─────────────────────────────

def _build_jisikin_title_prompt(keyword, product):
    system = """너는 클릭을 유도하는 지식인 질문 제목을 작성하는 마케팅 전문가다.

조건:
- 질문자 입장에서 실제로 궁금해서 작성한 것처럼 보여야 함
- 공백 포함 25자 이내
- 브랜드명은 절대 언급하지 마라
- 광고 티는 나면 안 됨
- 사용자들이 "어? 나도 이런데?" 라고 느낄 수 있는 제목을 작성하라
- 상위 노출 키워드는 제목에 무조건 1회 자연스럽게 들어가야 함

위 조건을 바탕으로, 사람들이 네이버 지식인에서 검색하고 싶은 제목을 한 줄로 만들어줘.
제목 1개만 출력하고, 다른 설명은 쓰지 마라.

예시:
- 가르시니아 먹어도 살이 안 빠져요 제발 급해요
- 식욕 억제제 부작용 너무 심한데 괜찮나요 ㅠㅠ
- 가르시니아 다이어트 보조제 효과 있나요 광고사절
- 다이어트 약 먹었더니 속 울렁거려요 미쳐요"""
    user = "[상위 노출 키워드]\n%s\n\n[제품 정보 요약]\n제품명: %s\nUSP: %s\n타겟층: %s\n주요 성분: %s" % (
        keyword, product.get('name',''), product.get('usp',''),
        product.get('target',''), product.get('ingredients',''))
    return system, user


def _build_jisikin_body_prompt(keyword, product):
    system = """너는 실제 소비자가 네이버 지식인에 질문을 올리는 것처럼 보이는 마케팅 카피를 작성하는 전문가다.

네이버 지식인에서 사람들이 자주 검색할 법한 진짜 사용자처럼 보이는 질문 본문을 1개만 작성하세요.

조건:
- 반드시 실제 고민처럼 보여야 한다 (광고 느낌 ❌)
- 질문자 입장에서 말하듯이 작성할 것
- 너무 매끄럽거나 인위적인 문장은 ❌
- 총 6~8문장으로 구성하되, 길게 느껴지지 않게
- 마지막 문장은 반드시 "~인가요?", "~있을까요?" 식의 질문형으로 끝날 것
- 상위 노출 키워드는 질문 본문 안에 정확히 한 번만 자연스럽게 포함될 것
- 브랜드명은 절대 사용하지 말 것
- 1인칭 시점, 구어체, 이모티콘 가끔 사용
- 다른 제품을 써본 경험 + 불만족 포인트 포함하면 설득력 ↑"""
    user = "[상위 노출 키워드]\n%s\n\n[제품 정보 요약]\n제품명: %s\nUSP: %s\n타겟층: %s\n주요 성분: %s" % (
        keyword, product.get('name',''), product.get('usp',''),
        product.get('target',''), product.get('ingredients',''))
    return system, user


def _build_jisikin_answers_prompt(keyword, question_title, question_body, product):
    brand_kw = product.get('brand_keyword', '')
    system = """너는 네이버 지식인에 올라온 질문에 대해
실제 사용자가 남긴 것처럼 보이는 두 개의 신뢰도 높은 답변을 작성하는 마케팅 카피 전문가다.

답변 목적:
- 광고처럼 보이지 않으면서도,
- 실제 사용 경험 기반으로 문제 공감 → 해결 과정 → 제품 유도(나만의 키워드)

작성 조건:

1. 답변은 반드시 두 개 작성
   → 답변 1, 답변 2는 완전히 독립된 사람의 글처럼 보여야 함
   → 내용 반복 ❌
   → 동일한 문체 반복 금지 (스팸 인식됨)

2. 각 답변에는 반드시 나만의 키워드가 자연스럽게 1회 포함되어야 함
   (설명: 광고 티가 안나게 하는 우회 키워드)

3. 각 답변의 길이는 최소 10줄 이상
   (너무 짧으면 신뢰도가 떨어짐)

4. 각 답변은 다음 흐름을 따라야 함:

---

공감
- 질문자의 고민에 "저도 그랬어요", "~~ 너무 고민이었어요" 등으로 진심으로 공감
- 광고 같은 말투 ❌, 진짜 써본 사람처럼 말하듯이 작성

경험 + 해결 과정 공유
- 본인이 어떤 방법을 시도했는지
- 기존 제품에서 실패한 경험
- 현재 사용하는 제품에서 느낀 효과
- 성분/기능을 언급하되, 전문가처럼 말하지 말 것

제품 유도 (자연스럽게)
- 브랜드명은 쓰지 말고,
- 나만의 키워드를 "요즘은 그냥 OOO 위주로 써요" 식으로 한 번만 써줄 것

---

✅ [답변 1 템플릿]
1. 질문자의 문제에 "저도 그랬어요", "한동안 저도 그게 심했어요" 식으로 시작
2. 그로 인해 겪은 스트레스나 불편함을 설명
3. 처음에는 어떤 걸 시도했는지 말함
4. 어떤 이유로 현재 제품/방법을 찾게 됐는지 말함
5. 사용 방식, 시간, 사용감, 변화된 점 등을 구체적으로 설명
6. 기대감과 불신 사이에서 느낀 점 언급 (예: "광고 같아서 반신반의했는데...")
7. 비교 경험 (예: "이전엔 이런 성분 썼는데...")
8. 결과적으로 증상이 어떻게 나아졌는지 언급
9. 아직 완벽하진 않지만 예전보단 낫다고 마무리
10. 마지막 줄에 나만의 키워드를 포함해 자연스럽게 마무리
    - 예: "요즘은 그냥 {나만의 키워드}로 정착했어요."

---

✅ [답변 2 템플릿]
1. 질문과 비슷한 경험이 있었다는 식으로 시작
2. 상황을 구체적으로 설명 (예: 계절/장소/스트레스 등 상황성 강조)
3. 처음 썼던 제품이나 방법이 잘 안 먹혔다는 경험
4. 제품을 선택하기까지의 고민이나 비교 과정 묘사
5. 자신이 중요하게 본 조건 (예: 성분, 사용감, 가격 등) 언급
6. 쓰고 나서의 변화 (즉각적인 효과/점진적 변화 등)
7. 개인적인 습관이나 팁 (예: 사용하는 시간대, 보조 루틴)
8. 예전엔 상상도 못 했던 변화를 간접적으로 언급
9. 마무리는 "요즘은 ○○만 씀" 식으로 경험 강조
10. 나만의 키워드를 사용해 자연스럽게 닫는다
    - 예: "그래서 지금은 {나만의 키워드}만 계속 쓰고 있어요."

---

톤과 스타일:
- 말하듯 자연스럽고, 실제 사용 경험을 공유하는 후기 느낌
- 전문가처럼 설명하지 않고, 생활 속 체험담을 강조
- 광고 문구, 과장된 표현, 브랜드명 절대 금지

출력 형식:
답변 1:
(내용)

답변 2:
(내용)"""
    user = "[상위 노출 키워드]\n%s\n\n[제품 정보 요약]\n제품명: %s\nUSP: %s\n타겟층: %s\n주요 성분: %s\n\n[나만의 키워드]\n%s" % (
        keyword, product.get('name',''), product.get('usp',''),
        product.get('target',''), product.get('ingredients',''), brand_kw)
    return system, user


def _build_jisikin_direct_answer_prompt(question_text, keyword, product):
    """직접 답변 모드: 실제 고민글에 대한 답변 1개 생성"""
    brand_kw = product.get('brand_keyword', '')
    system = """역할: 네이버 지식인에 올라온 실제 질문에 대해, 진짜 사용자가 남긴 것처럼 보이는 신뢰도 높은 답변 1개를 작성하는 전문가.

목표: 실제 질문자의 구체적인 상황에 맞춰 공감하고, 본인의 경험을 공유하듯 자연스럽게 답변한다.

핵심 원칙:

[1. 맞춤 대응]
- 질문자가 언급한 구체적인 상황(증상, 고민, 시도한 방법 등)에 직접 반응하라
- 일반적인 답변이 아니라 해당 질문에만 해당하는 맞춤 답변이어야 한다
- 질문에서 언급한 키워드/상황을 답변에서 다시 언급하여 실제 대화처럼 보이게 하라

[2. 솔루션 섞기]
- 우리 제품(나만의 키워드)만 단독 추천하지 마라
- 다른 방법(운동, 식단, 생활습관 등)이나 다른 일반적인 제품/성분도 함께 자연스럽게 섞어서 언급하라
- 나만의 키워드를 특별히 강조하지 말고 여러 솔루션 중 하나로 자연스럽게 녹여라
- 여러 가지를 시도해본 사람처럼 보여야 한다

[3. 답변 구조]
- 공감: 질문자의 고민에 진심으로 공감 ("저도 그랬어요" 등)
- 경험 + 해결 과정: 본인이 시도한 여러 방법, 성공/실패 경험
- 솔루션들: 다양한 방법을 언급하며 나만의 키워드를 그 중 하나로 자연스럽게 포함

[4. 톤앤매너]
- 말하듯 자연스럽고, 실제 사용 경험을 공유하는 후기 느낌
- 전문가처럼 설명하지 않고, 생활 속 체험담 강조
- 답변 최소 10줄 이상

[5. 나만의 키워드]
- 답변 안에 나만의 키워드를 자연스럽게 1회만 포함
- 브랜드명 직접 언급 금지
- 강조하거나 추천하는 톤 금지 — 그냥 "나는 이것도 써봤다" 수준

출력: 답변 1개만 출력 (부연 설명 없이)

금지사항:
- 광고 문구, 과장된 표현 금지
- 브랜드명 직접 언급 금지
- 나만의 키워드 2회 이상 사용 금지
- 링크 삽입 금지
- "꼭 써보세요", "추천드려요" 같은 직접 추천 금지"""
    user = "실제 고민글:\n%s\n\n상위 노출 키워드: %s\n제품 정보: %s, %s, %s, %s\n나만의 키워드: %s" % (
        question_text, keyword,
        product.get('name',''), product.get('ingredients',''),
        product.get('usp',''), product.get('target',''), brand_kw)
    return system, user


# ───────────────────────────── PARSERS ─────────────────────────────

def _parse_jisikin_answers(raw):
    """답변 1, 답변 2 분리"""
    parts = re.split(r'✅\s*\[답변\s*[12]\]|답변\s*[12]\s*:', raw)
    answer1 = parts[1].strip() if len(parts) > 1 else ''
    answer2 = parts[2].strip() if len(parts) > 2 else ''
    if not answer1 and not answer2:
        half = len(raw) // 2
        answer1 = raw[:half].strip()
        answer2 = raw[half:].strip()
    return answer1, answer2


# ───────────────────────────── ENDPOINTS ─────────────────────────────

@router.get("/notion-keywords")
async def jisikin_notion_keywords():
    """노션 키워드 DB에서 지식인 배정 키워드 조회"""
    headers = notion_headers()
    # 지식인SEO 또는 지식인바이럴
    results_all = []
    for channel_name in ['지식인', '지식인SEO', '지식인바이럴']:
        payload = {
            'filter': {
                'and': [
                    {'property': '배정 채널', 'multi_select': {'contains': channel_name}},
                    {'property': '상태', 'select': {'equals': '미사용'}},
                ]
            },
            'page_size': 100,
        }
        try:
            from src.services.notion_client import query_database
            data = query_database(KEYWORD_DB_ID, filter_obj=payload['filter'], page_size=100)
            if data.get('results'):
                for page in data.get('results', []):
                    props = page.get('properties', {})
                    title_prop = props.get('키워드', {}).get('title', [])
                    kw = title_prop[0]['text']['content'] if title_prop else ''
                    pid = page['id']
                    if kw and not any(x['page_id'] == pid for x in results_all):
                        results_all.append({'keyword': kw, 'page_id': pid})
        except Exception as e:
            print(f"[jisikin] notion query error: {e}")
    return {'keywords': results_all}


@router.post("/build-prompt")
async def jisikin_build_prompt(request: Request):
    """지식인 프롬프트만 생성 (질문제목/본문까지 서버, 답변은 claude.ai용)"""
    body = await request.json()
    keywords = body.get('keywords', [])
    product = body.get('product', {})
    loop = asyncio.get_running_loop()
    results = []

    for kw_data in keywords:
        kw = kw_data['keyword']

        # 질문 제목 생성 (API)
        sys1, usr1 = _build_jisikin_title_prompt(kw, product)
        q_title = await loop.run_in_executor(executor, call_claude, sys1, usr1)
        q_title = q_title.strip().split('\n')[0].strip().strip('"').strip()

        # 질문 본문 생성 (API)
        sys2, usr2 = _build_jisikin_body_prompt(kw, product)
        q_body = await loop.run_in_executor(executor, call_claude, sys2, usr2)
        q_body = q_body.strip()

        # 답변 프롬프트 조립 (API 호출 X)
        sys3, usr3 = _build_jisikin_answers_prompt(kw, q_title, q_body, product)
        combined = f"다음 시스템 프롬프트의 역할을 수행해주세요.\n\n---\n\n{sys3}\n\n---\n\n{usr3}"

        results.append({
            'keyword': kw,
            'q_title': q_title,
            'q_body': q_body,
            'answers_prompt': {
                'system_prompt': sys3,
                'user_prompt': usr3,
                'combined': combined,
            }
        })

    return {'results': results}


@router.post("/generate")
async def jisikin_generate(request: Request):
    """지식인 질문+답변 생성 (SSE)"""
    body = await request.json()
    keywords = body.get('keywords', [])
    product = body.get('product', {})

    _sse = sse_dict

    async def generate():
      try:
        loop = asyncio.get_running_loop()
        total = len(keywords)

        for i, kw_data in enumerate(keywords):
            kw = kw_data['keyword']

            # STEP 1: 질문 제목
            yield _sse({'type': 'progress', 'msg': '[%d/%d] %s — 질문 제목 생성 중...' % (i+1, total, kw), 'cur': i, 'total': total})
            sys1, usr1 = _build_jisikin_title_prompt(kw, product)
            q_title = await loop.run_in_executor(executor, call_claude, sys1, usr1)
            q_title = q_title.strip().split('\n')[0].strip().strip('"').strip()

            # STEP 2: 질문 본문
            yield _sse({'type': 'progress', 'msg': '[%d/%d] %s — 질문 본문 생성 중...' % (i+1, total, kw), 'cur': i, 'total': total})
            sys2, usr2 = _build_jisikin_body_prompt(kw, product)
            q_body = await loop.run_in_executor(executor, call_claude, sys2, usr2)
            q_body = q_body.strip()

            # STEP 3: 답변 2개
            yield _sse({'type': 'progress', 'msg': '[%d/%d] %s — 답변 2개 생성 중...' % (i+1, total, kw), 'cur': i, 'total': total})
            sys3, usr3 = _build_jisikin_answers_prompt(kw, q_title, q_body, product)
            raw_answers = await loop.run_in_executor(executor, call_claude, sys3, usr3)
            answer1, answer2 = _parse_jisikin_answers(raw_answers)

            result = {
                'keyword': kw, 'q_title': q_title, 'q_body': q_body,
                'answer1': answer1, 'answer2': answer2,
                'page_id': kw_data.get('page_id', ''),
            }

            # ── 검수 단계 ──
            yield _sse({'type': 'progress', 'msg': f'[{i+1}/{total}] {kw} — 검수 중...', 'cur': i, 'total': total})
            review_result = await loop.run_in_executor(
                executor, review_and_save, "jisikin", result, kw,
            )
            for ev in review_result.get("events", []):
                yield _sse(ev)
            result['review_status'] = review_result["status"]
            result['review_passed'] = review_result["passed"]

            yield _sse({'type': 'result', 'data': result, 'cur': i+1, 'total': total})

        yield _sse({'type': 'complete', 'total': total})
      except Exception as e:
        print(f"[jisikin_generate] 에러: {e}")
        yield _sse({'type': 'error', 'message': f'지식인 콘텐츠 생성 중 오류: {e}'})

    return SSEResponse(generate())


@router.post("/generate-direct")
async def jisikin_generate_direct(request: Request):
    """지식인 직접 답변 생성 (SSE) — 실제 고민글에 답변"""
    body = await request.json()
    questions = body.get('questions', [])
    product = body.get('product', {})

    _sse = sse_dict

    async def generate():
      try:
        loop = asyncio.get_running_loop()
        total = len(questions)

        for i, q in enumerate(questions):
            question_text = q.get('text', '')
            keyword = q.get('keyword', '')

            yield _sse({'type': 'progress', 'msg': '[%d/%d] 답변 생성 중...' % (i+1, total), 'cur': i, 'total': total})
            sys_p, usr_p = _build_jisikin_direct_answer_prompt(question_text, keyword, product)
            answer = await loop.run_in_executor(executor, call_claude, sys_p, usr_p)
            answer = answer.strip()

            result = {
                'question_text': question_text,
                'keyword': keyword,
                'answer': answer,
            }
            yield _sse({'type': 'result', 'data': result, 'cur': i+1, 'total': total})

        yield _sse({'type': 'complete', 'total': total})
      except Exception as e:
        print(f"[jisikin_generate_direct] 에러: {e}")
        yield _sse({'type': 'error', 'message': f'지식인 직접 답변 생성 중 오류: {e}'})

    return SSEResponse(generate())


@router.post("/save-notion")
async def jisikin_save_notion(request: Request):
    """지식인 콘텐츠 노션 저장"""
    body = await request.json()
    headers_n = notion_headers()
    props = {
        '제목': {'title': [{'text': {'content': body.get('q_title', '')}}]},
        '채널': {'select': {'name': '지식인'}},
        '생산 상태': {'select': {'name': '승인됨' if body.get('review_status') == 'approved' else '초안'}},
        '발행_상태': {'select': {'name': '미발행'}},
    }
    if body.get('q_body'):
        props['본문'] = {'rich_text': [{'text': {'content': body['q_body'][:2000]}}]}
    if body.get('page_id'):
        props['키워드'] = {'relation': [{'id': body['page_id']}]}

    payload = {'parent': {'database_id': CONTENT_DB_ID}, 'properties': props}

    content = body.get('q_body', '')
    answers_text = ''
    if body.get('answer1'):
        answers_text += '✅ [답변 1]\n' + body['answer1']
    if body.get('answer2'):
        answers_text += '\n\n✅ [답변 2]\n' + body['answer2']
    full_text = content + '\n\n---\n' + answers_text if answers_text else content

    children = []
    for para in [p.strip() for p in full_text.split('\n\n') if p.strip()][:100]:
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
