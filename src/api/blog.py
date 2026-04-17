"""블로그 원고 API 라우터"""
import asyncio
import json
import os
import re
import time
from urllib.parse import quote

import requests as req
from bs4 import BeautifulSoup
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.services.config import (
    executor, KEYWORD_DB_ID, CONTENT_DB_ID, NOTION_TOKEN, BASE_DIR,
)
from src.services.common import error_response
from src.services.ai_client import call_claude
from src.services.review_service import review_and_save
from src.services.sse_helper import sse_dict, SSEResponse

router = APIRouter()

# ── 프롬프트 오버라이드 ──
PROMPT_OVERRIDES_FILE = os.path.join(BASE_DIR, "prompt_overrides.json")


def _prompt_load_overrides():
    if os.path.exists(PROMPT_OVERRIDES_FILE):
        try:
            with open(PROMPT_OVERRIDES_FILE, encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


# ── 상위글 분석 ──

def _analyze_blog_article(url, keyword):
    """개별 블로그 글 분석: 사진수, 키워드반복수, 글자수, 본문텍스트"""
    try:
        # 네이버 블로그 데스크톱 URL은 iframe 구조라 본문이 비어 있음 → 모바일 URL로 변환
        mobile_url = url if 'm.blog.naver.com' in url else url.replace('blog.naver.com', 'm.blog.naver.com')
        headers = {'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15'}
        r = req.get(mobile_url, headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        # 본문 컨테이너 우선 탐색 (네이버 모바일 블로그 구조)
        content_el = soup.select_one('div.se-main-container') or soup.select_one('div#viewTypeSelector') or soup
        body = content_el.get_text(separator='\n', strip=True)
        char_count = len(body.replace(' ', '').replace('\n', '').replace('\t', ''))
        photo_count = len(soup.find_all('img', src=re.compile(r'postfiles|blogfiles|phinf')))
        kw_repeat = body.lower().count(keyword.lower())
        return {
            'photo_count': max(photo_count, 1),
            'keyword_repeat': max(kw_repeat, 1),
            'char_count': char_count,
            'body_text': body,  # 본문 텍스트 (참고용)
        }
    except Exception as e:
        print(f"[_analyze_blog_article] {url}: {e}")
        return None


def _extract_blog_urls(soup, urls, top_titles, seen_ids, max_count):
    """BeautifulSoup에서 블로그 URL 추출 (정형 셀렉터 우선, fallback 포함)"""
    added = 0

    # 정형 셀렉터
    for item in soup.select('.api_txt_lines.total_tit'):
        if added >= max_count:
            break
        title_text = item.get_text(strip=True)
        href = item.get('href', '')
        if not title_text or not href or 'blog.naver.com' not in href:
            continue
        m = re.search(r'blog\.naver\.com/([^/?#]+)/(\d+)', href)
        if not m:
            continue
        article_id = f"{m.group(1)}_{m.group(2)}"
        if article_id in seen_ids:
            continue
        seen_ids.add(article_id)
        top_titles.append(title_text)
        urls.append(href.split('?')[0])
        added += 1

    # fallback
    if added < max_count:
        for a in soup.find_all('a', href=re.compile(r'blog\.naver\.com/[^/]+/\d+')):
            if added >= max_count:
                break
            href = a.get('href', '')
            title_text = a.get_text(strip=True)
            m = re.search(r'blog\.naver\.com/([^/?#]+)/(\d+)', href)
            if not m:
                continue
            article_id = f"{m.group(1)}_{m.group(2)}"
            if article_id in seen_ids or len(title_text) < 5:
                continue
            seen_ids.add(article_id)
            top_titles.append(title_text)
            urls.append(href.split('?')[0])
            added += 1


def _analyze_top_for_blog(keyword):
    """통합검색 우선 → 블로그탭 보충, 상위글 5개 제목+URL 수집 → 상위 3개 본문 분석"""
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'}
    top_titles = []
    urls = []
    seen_ids = set()

    try:
        # Phase 1: 통합검색(nexearch) — 블로그 글 최대 3개
        try:
            r = req.get(f"https://search.naver.com/search.naver?query={quote(keyword)}&where=nexearch",
                        headers=headers, timeout=10)
            soup = BeautifulSoup(r.text, 'html.parser')
            _extract_blog_urls(soup, urls, top_titles, seen_ids, max_count=3)
        except Exception:
            pass

        # Phase 2: 블로그탭(blog) — 나머지 보충 (총 5개까지)
        remaining = 5 - len(top_titles)
        if remaining > 0:
            try:
                r = req.get(f"https://search.naver.com/search.naver?query={quote(keyword)}&where=blog",
                            headers=headers, timeout=10)
                soup = BeautifulSoup(r.text, 'html.parser')
                _extract_blog_urls(soup, urls, top_titles, seen_ids, max_count=remaining)
            except Exception:
                pass

        if not urls:
            return {'photo_count': 8, 'keyword_repeat': 5, 'char_count': 0, 'reference_body': '', 'top_titles': []}

        # 상위 3개 본문 분석
        results = []
        articles = []  # 개별 글 상세 정보
        for url in urls[:3]:
            a = _analyze_blog_article(url, keyword)
            if a:
                results.append(a)
                articles.append({'url': url, 'char_count': a['char_count'], 'photo_count': a['photo_count'], 'keyword_repeat': a['keyword_repeat']})
            time.sleep(0.5)
        if not results:
            return {'photo_count': 8, 'keyword_repeat': 5, 'char_count': 0, 'reference_body': '', 'top_titles': top_titles, 'articles': []}

        avg_char = round(sum(r.get('char_count', 0) for r in results) / len(results))
        # 상위글 중 평균 글자수에 가장 가까운 1개의 본문을 참고용으로 선택
        reference_body = ''
        best_diff = float('inf')
        for r in results:
            body = r.get('body_text', '')
            if body:
                diff = abs(r.get('char_count', 0) - avg_char)
                if diff < best_diff:
                    best_diff = diff
                    reference_body = body[:2000]
        return {
            'photo_count': max(round(sum(r['photo_count'] for r in results) / len(results)), 3),
            'keyword_repeat': max(round(sum(r['keyword_repeat'] for r in results) / len(results)), 3),
            'char_count': avg_char,
            'reference_body': reference_body,
            'top_titles': top_titles,
            'articles': articles,
        }
    except Exception as e:
        print(f"[_analyze_top_for_blog] {e}")
        return {'photo_count': 8, 'keyword_repeat': 5, 'char_count': 0, 'reference_body': '', 'top_titles': []}


# ── 프롬프트 빌더 ──

def _build_blog_title_prompt(keyword, product, top_titles=None):
    """블로그 제목 프롬프트 (STEP 1) — 상위글 제목 참고"""
    system = """너는 네이버 블로그 제목을 쓰는 사람이야.
실제 블로그에 올라온 것처럼 자연스러운 제목 1개를 만들어줘.
깔끔하게 다듬지 말고, 사람이 생각나는 대로 쓴 느낌으로.

[규칙]
1. 키워드는 제목에 반드시 1회 자연스럽게 포함
2. 광고 느낌 금지 ("대박템", "강추", 특수문자 나열 등)
3. 제목만 출력. 다른 설명 없이.

[좋은 제목 예시 — 이 톤과 구조를 참고]
- 손목 저주파 마사지기 내돈내산 만족후기 (feat.미라클메디핏)
- 의료용 손목보호대 추천? 비교해보니 결국 손목통증에 좋은 건…
- 안명홍조 없애는 법 리얼 후기 l 레드포힐 화장품 장벽 재생크림 추천
- 주사피부염 피부 레드포힐 장벽크림 3주 사용후기
- 3040대 악건성피부케어 속보습? 파믹 진정크림으로 해결!
- 남성썬크림 유분기 없는 스포츠 선크림 자외선 차단제 추천템 BEST3

[이 예시들의 특징 — 반드시 반영]
- 키워드가 앞쪽에 옴
- 후기형, 추천형, 비교형, 해결형 등 다양한 스타일
- 구체적 디테일 (기간, 숫자, 나이대 등)
- 제품명이 자연스럽게 들어감
- "내돈내산", "리얼 후기", "솔직" 같은 진짜 느낌 표현
- 질문("추천?", "속보습?"), 구분자("l", "feat.", "…") 활용

[참고]
- 아래 상위 노출 제목들의 말투, 길이, 구조를 흡수해서 같은 검색 결과에 섞여도 어색하지 않게 작성"""

    titles_text = ''
    if top_titles:
        titles_text = '\n'.join(f'- {t}' for t in top_titles[:5])
    else:
        titles_text = '(상위글 제목 데이터 없음 — 키워드만으로 생성)'

    user = f"""[키워드]
{keyword}

[현재 이 키워드의 상위 노출 블로그 제목들]
{titles_text}

위 상위글 제목들과 같은 검색 결과에 자연스럽게 섞일 수 있는 제목 1개를 만들어줘."""
    return system, user


def _build_blog_body_prompt(keyword, stage, product, photo_count, keyword_repeat, title='', char_target=0, reference_body=''):
    """블로그 본문 프롬프트 (STEP 2) — {title}에 STEP 1 결과가 들어옴"""
    # A3: 상위글 평균 글자수 기반 동적 설정 (멘토 가이드: 상위글 평균의 90~110%)
    if char_target and char_target > 0:
        char_min = int(char_target * 0.9)
        char_max = int(char_target * 1.1)
        char_rule = f"- 이 글의 전체 분량은 공백 포함 {char_min}~{char_max}자입니다. (상위글 평균 {char_target}자의 90~110%)"
    else:
        char_rule = "- 이 글의 전체 분량은 공백 포함 2,200자 이상이어야 합니다."

    system = """📌 역할:
당신은 후기형 네이버 블로그 글의 오프닝부터 본문, 클로징까지 작성하는 작가입니다.

📏 필수 지침: 글자 수 강제 조건
__CHAR_RULE__
- 단락 수는 최소 8단락 이상
- 절대 압축 요약하지 말고 느낌, 사례, 생각, 비교 등을 풍부하게 풀어 써주세요.

---

꼭 제목을 참고해서 내용과 제목의 맥락이 맞게 해주세요.

🧩 작성 구조 (5단 구성):

| 구간 | 내용 | 비중 |
|------|------|------|
| 1. 오프닝 | 고민/문제 공감 → 독자가 "내 얘기잖아" 느끼게 | 15% |
| 2. 시도 & 실패 | 다른 방법 시도했지만 실패한 경험 → 객관성 확보 | 15% |
| 3. 발견 & 체험 | 제품을 알게 된 계기 + 초기 사용 과정 | 25% |
| 4. 변화 & 결과 | 구체적 수치로 변화 증명 (kg, 사이즈, 기간 등) | 30% |
| 5. 마무리 | 재구매 의사 + 조건부 추천 ("저한테는 맞았어요") | 15% |

핵심 전략: "공감 → 실패 → 해결 → 변화"의 4단 흐름
- 내 장점을 어필하지 말고, 차선책을 하나씩 지워가며 해결책으로 자연스럽게 연결
- 광고처럼 보이지 않고, "현실적인 공감 + 자연스러운 해결 흐름"을 만들 것

---

🎯 구매여정 단계별 오프닝 분기:

오프닝은 키워드를 보고 소비자가 어떤 심리로 클릭했을지 판단하여 작성합니다.
아래 단계 중 가장 적합한 것을 선택하세요.

● 문제 인식 (0_무지 ~ 1_인지):
"두피가 자꾸 가렵고 각질이 생기는데 왜 그런지 몰랐어요."
→ 공감 중심, 불편한 일상 묘사

● 해결 탐색 (2_호기심 ~ 3_정보습득):
"두피가려움 때문에 이것저것 알아보다가 스케일링, 오일, 샴푸까지 다 찾아봤어요."
→ 다양한 방법 탐색 + 문제 간략 언급

● 해결방법 선택 (3_정보습득):
"여러 가지 다 실패하다가 결국 ○○제품을 알게 됐어요."
→ 자사 제품 선택 계기 + 기대감 묘사

● 비교 검토 (4_의심):
"경쟁사 제품에는 ○○이 없어서 아쉬웠는데, 이 제품은 ○○이 있어서 만족했어요."
→ 경쟁 제품 언급 + 자사 USP 강조

● 구매 직전 (5_구매직전):
"후기들을 보다가 제 기준엔 이게 괜찮더라구요."
→ 사용 후기 중심 + 신뢰 강조 + 링크 클릭 심리 유도

---

📌 오프닝 작성 세부 규칙:
- 제품 이야기를 절대 먼저 꺼내지 않음. 독자의 고민에서 시작
- 나이, 직업, 가족 상황 등 구체적인 페르소나 설정
- 감정적 고통의 디테일 ("두려웠다", "포기하고 싶었다")
- 키워드를 1회 자연스럽게 포함

📌 시도 & 실패 세부 규칙:
- 다른 방법을 시도했지만 효과 없었던 경험을 솔직하게 서술
- 이 단계가 있어야 '광고'가 아닌 '진짜 후기'로 인식됨

📌 발견 & 체험 세부 규칙:
- 제품을 처음 알게 된 계기를 자연스럽게 서술
- "먹자마자 효과가 있었다" 같은 과장 표현 금지
- "~느낌이 들었다", "~것 같다" 수준으로 표현

📌 변화 & 결과 세부 규칙:
- 반드시 구체적인 숫자 포함 (체중, 사이즈, 체지방률, 기간 등)
- 사진과 함께 배치될 때 설득력이 극대화됨

📌 마무리 세부 규칙:
- 재구매 의사 + 조건부 추천 ("저한테는 맞았어요" 식)
- 제품명 검색을 유도하지 마. "활낙산 찾아보세요" ❌ → "전립선 영양제 고를 때 낙산 성분 있는지 확인해보세요" ✅
- 고객은 제품명을 모르고 들어온 사람이야. 카테고리(전립선 영양제, 정력 영양제 등) 기준으로 말해

---

📌 본문 전개 규칙:
- 경쟁 제품의 단점 서술
- 내가 선택한 제품 설명
- USP는 리뷰처럼 자연스럽게 녹이기 (예: "성분이 순해서 그런지 간지러움이 덜했어요.")

📌 이미지 삽입 규칙:
- 이미지는 이미지에 대한 설명을 쓰지 않고 순서만 적음
- [이미지1], [이미지2] ... 형태로 표기
- 총 지정된 사진수만큼 삽입
- 글 – 사진 – 글 – 사진의 일정한 리듬으로 배치
- 이미지 블록 앞뒤로는 빈 줄 1줄

📌 키워드 사용 규칙:
- 키워드는 전체 글에서 지정된 횟수만큼만 삽입
- 억지 삽입 없이 문맥 자연스럽게 유지

📌 클로징 (마무리 단락):
- 후기처럼 마무리
- 직접적인 구매 유도 문장(X), 대신 제안형 문장(O)
- 마지막 문장에는 [링크]라고 적어주고, 그 링크를 클릭하도록 심리를 자극할것.
  다음 리스트에서 무작위로 한 문장을 선택해 출력하세요.
  절대 2개 이상 출력하지 말고, 반드시 1개만 선택해 그대로 출력하세요.
  - 이번주까지만 특가 이벤트 진행한다고 해요. 링크 남겨드릴테니 한번 보시는것도 좋을것 같네요
  - 이제품 첼린지도 하고 난리났더라구요. 링크 남겨드릴테니 후기랑 상세페이지 잘 비교해보시고 구매하시길 바라요
  - 이번에 못 사면 다음 입고까지 한참 기다려야 한다고 하네요ㅠㅠ 제가 구매했던 링크 남겨드릴게요
  - 저는 30%할인할때 샀는데 지금도 하는지는 모르겠네요. 제가 구매했던 링크 남겨드릴게요
  - 단순 건강식품이 아니라 기능성 인정 받은 제품이라 믿고 구매했습니다. 궁금하신분들을 위해 링크 남겨드릴게요
  - 배송 지연 안내 보고 늦기 전에 결제했는데 다행히 다음날 바로 도착하더라구요. 필요하신분들은 아래링크 참고하세요!
  - 저도 여기 보고 알게 돼서 들어가봤는데 확실히 다르더라구요. 제가 구매했던 링크 남겨드릴게요
  - 요즘 카페랑 SNS에서 후기가 폭주 중이던데.. 링크남겨드릴테니 필요하신분은 확인해보세요

---

✍️ 톤 & 문체:
- 아래 [참고 상위글]이 제공되면, 그 글의 말투·문장 길이·표현 방식을 최대한 따라해. 상위글처럼 써야 같은 검색 결과에서 자연스러움.
- 과장된 광고 문구 자제. 정보+체험 혼합 톤.
- 동일 표현의 반복만 제거하고, 다른 표현이면 유지한다. 전체 분량은 상위글 평균 대비 ±10% 이내로 유지한다. (요약 금지)

🚫 금지 표현:
- "치료", "완치", "효과 보장" 등 의료법 위반 표현
- "대박", "강추", "꼭 사세요" 등 직접적 구매 유도
- 이모지 사용 금지
- 불릿/번호 목록, 표, 코드블록 출력 금지
- 성분의 작용 메커니즘을 단계별로 설명하지 마. "A성분 → B에 도움 → B가 C에 도움" 식으로 풀지 말고, "A성분 → C에 도움"으로 바로 연결해.
- 제품과 직접 관련 없는 효과(컨디션, 체중변화, 피로회복 등)를 언급하지 마. 제품의 핵심 효능에만 집중해.
- 장(腸), 장내, 장건강, 장 환경, 흡수 효율 등 장 관련 서술 금지. 성분→효과를 장을 경유해서 설명하지 마.
- AI 번역체 표현 금지: "~것 같았어요", "~영향을 미치는 것 같았어요", "~실제로 ~에도 영향을 미치는", "~하지 않았나 싶더라고요", "~작용하는 느낌이었어요" 같은 매끄럽고 정돈된 문장 금지. 실제 블로그처럼 약간 거칠고 구어체로 써.

---

[형식 규칙]

1. 문장 단위 줄바꿈
   - 한 줄에는 반드시 한 문장만 둔다.
   - 목표 길이: (공백 포함) 22~40자/줄.
   - 허용 범위: 18~55자/줄. 55자를 넘기면 반드시 문장을 둘로 나눠라.

2. 문장 길이가 애매할 때의 분할 기준 (우선순위 순)
   A. 쉼표(,), '그리고/그래서/하지만/또한/다만/혹은' 같은 접속사 앞에서 끊는다.
   B. 조사 '고/며/면서/지만/라도' 앞에서 자연스럽게 끊는다.
   C. 수식어구가 길면 수식어와 핵심 서술(주어+서술어) 사이에서 끊는다.
   D. 의미 단위가 약하면 어미를 조정해 두 개의 완결 문장으로 만든다.
   E. 위 기준이 모두 어색하면, 핵심 주장/사실 우선 문장을 앞으로, 보충/예시는 다음 줄로 보낸다.
   - 끊은 뒤에는 각 줄이 '완결된 문장'이 되도록 종결어미(~요/~다)로 마무리한다.
   - '…'로 문장을 끝내며 끊지 않는다. (생략 부호는 문장 중간에서만 사용)

3. 문단 구성
   - 문단은 2~4줄(=2~4문장)로 묶는다.
   - 기본은 3줄, 흐름상 길거나 짧을 땐 2줄 또는 4줄을 허용한다.
   - 문단과 문단 사이에는 빈 줄 1줄만 둔다. (2줄 이상 금지)

4. 제목과 소제목
   - 제목은 첫 줄에 사용하되, Markdown H1(# 제목) 표기만 허용.
   - 제목 다음에는 빈 줄 1줄을 둔다. 소제목이 없으면 새로 만들지 않는다.

5. 이미지 플레이스홀더
   - [이미지N] 형식으로 표기하고, 한 줄을 독립 문단처럼 배치한다.
   - 글 – 사진 – 글 – 사진의 일정한 리듬으로 배치한다.
   - 이미지 블록 앞뒤로는 빈 줄 1줄을 둔다.

6. 기호/문장부호
   - 큰따옴표는 그대로 유지하되, 불필요한 인용부호 추가 금지.
   - 마침표 남발 금지. 그러나 각 줄은 완결 문장으로 끝낸다.
   - 이모지는 사용하지 않는다. 불릿/번호 목록, 표, 코드블록 출력 금지.

7. 금지 사항
   - 줄글(한 줄에 두 문장 이상) 금지.
   - 문단 사이 공백 2줄 이상 금지.
   - 제목 추가 생성/임의 소제목 생성 금지.
   - 임의 요약/삭제/추가 정보 삽입 금지.
   - 문장 중간 강제 개행(의미 단절) 금지.

[출력 예시 미니 샘플] ← 구조만 참고 (실제 내용 아님)

# 제목 예시

첫 문장은 문제 상황을 짧게 제시해요.
다음 문장은 맥락을 연결해요.
세 번째 문장은 독자의 공감을 이끌어요.

해결을 위해 시도했던 방법을 간단히 말해요.
핵심 실패 요인을 한 문장으로 정리해요.
전환 문장으로 다음 단락을 예고해요.

[이미지1]

제품을 사용한 계기를 한 문장으로 말해요.
사용 직후 느낀 포인트를 한 문장으로 말해요.
다음 문장으로 결과를 간결히 마무리해요.""".replace('__CHAR_RULE__', char_rule)

    user = f"""[시스템 자동 전달]
제목: {title}

[사용자 입력]
상위 노출 키워드: {keyword}
제품명: {product.get('name', '')}
제품 USP (차별 포인트): {product.get('usp', '')}
타겟층: {product.get('target', '')}
주요 성분: {product.get('ingredients', '')}
나만의 키워드: {product.get('brand_keyword', '')}
구매여정 단계: {stage}
사진 수: {photo_count}장
키워드 반복 수: {keyword_repeat}회

위 정보를 기반으로, 제목과 맥락이 맞는 후기형 블로그 본문을 작성해주세요."""

    # 상위글 참고 본문 추가 (user 프롬프트에만 — 시스템 프롬프트 미수정)
    if reference_body:
        user += f"""

---
[참고 상위글 — 이 글의 말투를 따라해]
아래는 이 키워드로 네이버 상위 노출된 실제 블로그 글입니다.
이 글의 말투, 문장 길이, 표현 방식, 줄바꿈 습관을 최대한 따라 써.
내용을 베끼지 말고, "이 사람이 다른 주제로 글을 쓰면 이렇게 쓰겠다" 느낌으로 문체만 흡수해.

{reference_body}"""

    return system, user


# 하위 호환: 기존 코드에서 _build_blog_prompts 호출하는 곳 대응
def _build_blog_prompts(keyword, stage, product, photo_count, keyword_repeat):
    """하위 호환용 — 제목+본문 통합 프롬프트 (레거시)"""
    return _build_blog_body_prompt(keyword, stage, product, photo_count, keyword_repeat, '')


# ── 엔드포인트 ──

@router.get("/notion-keywords")
async def blog_notion_keywords():
    """노션 키워드 DB에서 블로그 배정 키워드 조회"""
    headers = {
        'Authorization': f'Bearer {NOTION_TOKEN}',
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28',
    }
    payload = {
        'filter': {
            'and': [
                {'property': '배정 채널', 'multi_select': {'contains': '블로그'}},
                {'property': '상태', 'select': {'equals': '미사용'}},
            ]
        },
        'page_size': 100,
    }
    try:
        from src.services.notion_client import query_database
        data = query_database(KEYWORD_DB_ID, filter_obj=payload['filter'], page_size=100)
        keywords = []
        for page in data.get('results', []):
            props = page.get('properties', {})
            title_prop = props.get('키워드', {}).get('title', [])
            kw = title_prop[0]['text']['content'] if title_prop else ''
            stage_prop = props.get('구매여정_단계', {}).get('select')
            stage_name = stage_prop.get('name', '') if stage_prop else ''
            if kw:
                keywords.append({'keyword': kw, 'stage': stage_name, 'page_id': page['id']})
        return {'keywords': keywords}
    except Exception as e:
        return {'keywords': [], 'error': str(e)}


@router.post("/check-forbidden")
async def blog_check_forbidden(request: Request):
    """셀프모아 금칙어 검사"""
    body = await request.json()
    text = body.get('text', '')
    if not text:
        return {'forbidden_words': [], 'count': 0, 'clean': True}
    try:
        r = req.post('https://www.selfmoa.com/filter/wordcheck.php',
                     data={'title': text},
                     headers={'Content-Type': 'application/x-www-form-urlencoded',
                              'User-Agent': 'Mozilla/5.0'},
                     timeout=15)
        r.encoding = 'utf-8'
        # 빨간색 하이라이트된 단어 추출
        found = re.findall(r'<font\s+color=["\']?red["\']?>(.*?)</font>', r.text, re.IGNORECASE)
        if not found:
            found = re.findall(r'color:\s*red[^>]*>(.*?)</', r.text, re.IGNORECASE)
        unique = list(dict.fromkeys(found))  # 중복 제거, 순서 유지
        return {'forbidden_words': unique, 'count': len(unique), 'clean': len(unique) == 0}
    except Exception as e:
        return JSONResponse({'forbidden_words': [], 'count': 0, 'clean': True, 'error': str(e)}, 500)


@router.post("/fix-forbidden")
async def blog_fix_forbidden(request: Request):
    """금칙어를 대체어로 수정"""
    body = await request.json()
    text = body.get('text', '')
    forbidden_words = body.get('forbidden_words', [])
    if not text or not forbidden_words:
        return {'fixed_text': text, 'replacements': []}
    words_str = ', '.join(forbidden_words)
    sys_prompt = f"""너는 네이버 블로그 콘텐츠 편집 전문가야.
아래 원고에서 금칙어를 자연스러운 대체어로 바꿔줘.
금칙어 목록: [{words_str}]

규칙:
- 원고의 맥락과 흐름을 유지하면서 금칙어만 대체
- 대체어는 네이버 블로그에서 안전한 단어로 선택
- 원고 전체 분량과 구조는 그대로 유지
- 수정된 전체 원고만 출력 (설명 없이)"""
    loop = asyncio.get_running_loop()
    fixed = await loop.run_in_executor(executor, call_claude, sys_prompt, text)
    replacements = [{'from': w, 'to': '(수정됨)'} for w in forbidden_words]
    return {'fixed_text': fixed, 'replacements': replacements}


@router.post("/build-prompt")
async def blog_build_prompt(request: Request):
    """블로그 프롬프트만 생성 (크롤링+제목까지 서버, 본문은 claude.ai용 복사)"""
    body = await request.json()
    keywords = body.get('keywords', [])
    product = body.get('product', {})
    user_title = body.get('user_title', '')
    loop = asyncio.get_running_loop()
    results = []

    for kw_data in keywords:
        kw = kw_data['keyword']
        stage = kw_data.get('stage', '3_정보습득')

        # 1. 상위글 분석 (크롤링)
        analysis = await loop.run_in_executor(executor, _analyze_top_for_blog, kw)
        pc = analysis['photo_count']
        kr = analysis['keyword_repeat']
        ct = analysis.get('char_count', 0)

        # 2. 제목 프롬프트 조립 (API 호출 X — claude.ai에서 직접 테스트)
        overrides = _prompt_load_overrides()
        title_sys = overrides.get('블로그_제목', None)
        if title_sys:
            title_usr = f"[입력 정보]\n- 상위 노출 키워드: {kw}\n\n[제목 작성 규칙]\n\"{kw}\"는 제목에 반드시 1회 자연스럽게 포함"
        else:
            title_sys, title_usr = _build_blog_title_prompt(kw, product, top_titles=analysis.get('top_titles', []))
        combined_title = f"다음 시스템 프롬프트의 역할을 수행해주세요.\n\n---\n\n{title_sys}\n\n---\n\n{title_usr}"
        # 사용자가 제목을 입력했으면 사용, 아니면 placeholder
        title = user_title if user_title else '(제목란에 입력하세요)'

        # 3. 본문 프롬프트 조립 (API 호출 X)
        ref_body = analysis.get('reference_body', '')
        body_sys = overrides.get('블로그_본문', None)
        if body_sys:
            body_usr = f"[시스템 자동 전달]\n제목: {title}\n\n[사용자 입력]\n상위 노출 키워드: {kw}\n제품명: {product.get('name','')}\n제품 USP (차별 포인트): {product.get('usp','')}\n타겟층: {product.get('target','')}\n주요 성분: {product.get('ingredients','')}\n나만의 키워드: {product.get('brand_keyword','')}\n구매여정 단계: {stage}\n사진 수: {pc}장\n키워드 반복 수: {kr}회\n\n위 정보를 기반으로, 제목과 맥락이 맞는 후기형 블로그 본문을 작성해주세요."
        else:
            body_sys, body_usr = _build_blog_body_prompt(kw, stage, product, pc, kr, title, char_target=ct, reference_body=ref_body)
        combined = f"다음 시스템 프롬프트의 역할을 수행해주세요.\n\n---\n\n{body_sys}\n\n---\n\n{body_usr}"

        results.append({
            'keyword': kw,
            'stage': stage,
            'title': title,
            'analysis': {'photo_count': pc, 'keyword_repeat': kr, 'char_count': ct},
            'crawled': {'top_titles': analysis.get('top_titles', []), 'reference_body': ref_body[:2000], 'articles': analysis.get('articles', [])},
            'title_prompt': {
                'system_prompt': title_sys,
                'user_prompt': title_usr,
                'combined': combined_title,
            },
            'body_prompt': {
                'system_prompt': body_sys,
                'user_prompt': body_usr,
                'combined': combined,
            }
        })

    return {'results': results}


@router.post("/generate")
async def blog_generate(request: Request):
    """블로그 원고 생성 (SSE)"""
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
            stage = kw_data.get('stage', '3_정보습득')

            msg1 = '[%d/%d] %s — 상위글 분석 중...' % (i+1, total, kw)
            yield _sse({'type': 'progress', 'msg': msg1, 'cur': i, 'total': total})
            analysis = await loop.run_in_executor(executor, _analyze_top_for_blog, kw)

            pc = analysis['photo_count']
            kr = analysis['keyword_repeat']
            ct = analysis.get('char_count', 0)
            # STEP 1: 제목 생성
            msg2 = '[%d/%d] %s — 제목 생성 중...' % (i+1, total, kw)
            yield _sse({'type': 'progress', 'msg': msg2, 'cur': i, 'total': total})
            overrides = _prompt_load_overrides()
            title_sys = overrides.get('블로그_제목', None)
            if title_sys:
                title_usr = f"[입력 정보]\n- 상위 노출 키워드: {kw}\n\n[제목 작성 규칙]\n\"{kw}\"는 제목에 반드시 1회 자연스럽게 포함"
            else:
                title_sys, title_usr = _build_blog_title_prompt(kw, product, top_titles=analysis.get('top_titles', []))
            title_raw = await loop.run_in_executor(executor, call_claude, title_sys, title_usr)
            title = title_raw.strip().replace('제목:', '').replace('제목 :', '').strip()
            if '\n' in title:
                title = title.split('\n')[0].strip()

            # STEP 2: 본문 생성 (제목을 변수로 전달)
            ct_info = '상위글%d자, ' % ct if ct else ''
            msg3 = '[%d/%d] %s — 본문 생성 중... (%s사진%d장, 키워드%d회)' % (i+1, total, kw, ct_info, pc, kr)
            yield _sse({'type': 'progress', 'msg': msg3, 'cur': i, 'total': total})
            ref_body = analysis.get('reference_body', '')
            body_sys = overrides.get('블로그_본문', None)
            if body_sys:
                body_usr = f"[시스템 자동 전달]\n제목: {title}\n\n[사용자 입력]\n상위 노출 키워드: {kw}\n제품명: {product.get('name','')}\n제품 USP (차별 포인트): {product.get('usp','')}\n타겟층: {product.get('target','')}\n주요 성분: {product.get('ingredients','')}\n나만의 키워드: {product.get('brand_keyword','')}\n구매여정 단계: {stage}\n사진 수: {pc}장\n키워드 반복 수: {kr}회\n\n위 정보를 기반으로, 제목과 맥락이 맞는 후기형 블로그 본문을 작성해주세요."
            else:
                body_sys, body_usr = _build_blog_body_prompt(kw, stage, product, pc, kr, title, char_target=ct, reference_body=ref_body)
            body_text = await loop.run_in_executor(executor, call_claude, body_sys, body_usr)
            body_text = body_text.strip()

            actual_repeat = body_text.count(kw)
            char_count = len(body_text)

            result = {
                'keyword': kw, 'stage': stage, 'title': title, 'body': body_text,
                'photo_count': pc, 'keyword_repeat': kr,
                'actual_repeat': actual_repeat, 'char_count': char_count,
                'page_id': kw_data.get('page_id', ''),
            }

            # ── 검수 단계 ──
            yield _sse({'type': 'progress', 'msg': f'[{i+1}/{total}] {kw} — 검수 중...', 'cur': i, 'total': total})

            def _regenerate_blog(content, errors):
                fix_prompt = f"아래 블로그 원고를 수정하세요.\n\n[수정 필요 항목]\n"
                for err in errors:
                    fix_prompt += f"- {err}\n"
                fix_prompt += f"\n[원고]\n제목: {content['title']}\n\n{content['body']}"
                sys_p = "당신은 블로그 원고 수정 전문가입니다. 지적된 항목만 수정하고 나머지는 유지하세요. 수정된 본문만 출력하세요."
                fixed_body = call_claude(sys_p, fix_prompt, channel="blog")
                content['body'] = fixed_body.strip()
                content['char_count'] = len(content['body'])
                content['actual_repeat'] = content['body'].lower().count(kw.lower())
                return content

            review_result = await loop.run_in_executor(
                executor, review_and_save,
                "blog", result, kw, product, _regenerate_blog,
            )

            # 검수 이벤트 전달
            for ev in review_result.get("events", []):
                yield _sse(ev)

            # 검수 결과를 result에 병합
            result = review_result["content"]
            result['review_status'] = review_result["status"]
            result['review_passed'] = review_result["passed"]
            result['revision_count'] = review_result["revision_count"]
            result['project_id'] = review_result["project_id"]
            result['ai_review'] = review_result.get("ai_review", {})
            result['page_id'] = kw_data.get('page_id', '')

            yield _sse({'type': 'result', 'data': result, 'cur': i+1, 'total': total})

        yield _sse({'type': 'complete', 'total': total})
      except Exception as e:
        print(f"[blog_generate] 에러: {e}")
        yield _sse({'type': 'error', 'message': f'블로그 원고 생성 중 오류: {e}'})

    return SSEResponse(generate())


@router.post("/save-notion")
async def blog_save_notion(request: Request):
    """블로그 원고를 노션 콘텐츠 DB에 저장"""
    body = await request.json()
    headers = {
        'Authorization': f'Bearer {NOTION_TOKEN}',
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28',
    }
    review_status = body.get('review_status', 'draft')
    production_status = '승인됨' if review_status == 'approved' else '초안'
    props = {
        '제목': {'title': [{'text': {'content': body.get('title', '')}}]},
        '채널': {'select': {'name': '블로그'}},
        '생산 상태': {'select': {'name': production_status}},
        '발행_상태': {'select': {'name': '미발행'}},
    }
    if body.get('body_summary'):
        props['본문'] = {'rich_text': [{'text': {'content': body['body_summary'][:2000]}}]}
    if body.get('photo_count') is not None:
        props['사진수'] = {'number': body['photo_count']}
    if body.get('keyword_repeat') is not None:
        props['키워드_반복수'] = {'number': body['keyword_repeat']}
    if body.get('page_id'):
        props['키워드'] = {'relation': [{'id': body['page_id']}]}

    payload = {'parent': {'database_id': CONTENT_DB_ID}, 'properties': props}

    body_text = body.get('body', '')
    if body_text:
        paragraphs = [p.strip() for p in body_text.split('\n\n') if p.strip()]
        children = []
        for para in paragraphs[:100]:
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
