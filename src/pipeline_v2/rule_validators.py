"""채널별 규칙 검수기 (코드 강제). 실패 항목만 부분 수정 대상."""
import re
from src.pipeline_v2.seo_analyzer import analyze_seo


# ── 공통 ──

AD_WORDS_GENERIC = [
    "강추", "대박", "최고의", "미쳤다", "완전 좋", "꼭 사세요",
    "인생템", "갓", "킹", "찐", "레전드", "넘사벽", "역대급",
    "무조건 사야", "안 사면 후회",
]

AD_WORDS_VIRAL = [
    "최저가", "무료배송", "할인", "쿠폰", "이벤트", "특가", "파격",
    "지금 바로 구매", "구매링크", "www.", "http", ".com", ".kr",
    "광고", "협찬", "제공받", "원래 가격", "정가",
]

AD_PATTERNS_COMMUNITY = [
    r'광고', r'협찬', r'제공받', r'체험단', r'원고료',
    r'링크\s*클릭', r'할인\s*코드', r'쿠폰\s*코드',
    r'구매\s*링크', r'바로\s*가기',
]


def _check_emoji(text: str) -> list[str]:
    if re.search(r'[\U0001F600-\U0001F9FF\U0001FA00-\U0001FAFF\U00002702-\U000027B0]', text):
        return ["이모지 발견"]
    return []


def _check_meta_tags(text: str) -> list[str]:
    if re.search(r'\[(연출|자막|장면|화면|전환|효과)\]', text):
        return ["메타 표기 발견"]
    return []


def _check_hook(first_line: str, hook_words: list[str] = None) -> list[str]:
    if hook_words is None:
        hook_words = ["?", "아셨", "솔직히", "진짜", "제가", "그날", "어느 날",
                      "갑자기", "했는데", "었는데", "이었", "그때", "있었",
                      "아시", "근데", "혹시", "알고", "요즘", "나도"]
    if not any(p in first_line for p in hook_words):
        return ["첫 문장 훅 부족"]
    return []


# ── 숏츠 ──

def validate_shorts(script_text: str) -> list[str]:
    errors = []
    c = len(script_text)
    if c < 300:
        errors.append(f"글자수 부족: {c}자 (최소 300)")
    if c > 800:
        errors.append(f"글자수 초과: {c}자 (최대 800)")

    lines = [l.strip() for l in script_text.strip().split("\n") if l.strip()]
    first = lines[0] if lines else ""
    errors.extend(_check_hook(first))

    tail = " ".join(lines[-2:]) if len(lines) >= 2 else (lines[-1] if lines else "")
    cta_words = ["확인", "링크", "검색", "프로필", "클릭", "터치", "보세요"]
    if not any(w in tail for w in cta_words):
        errors.append("CTA 없음")

    errors.extend(_check_emoji(script_text))
    errors.extend(_check_meta_tags(script_text))
    return errors


# ── 블로그 ──

def validate_blog(title: str, body: str, keyword: str,
                  char_count: int = None, keyword_count: int = None) -> list[str]:
    errors = []
    c = char_count if char_count is not None else len(body)
    if c < 2200:
        errors.append(f"글자수 부족: {c}자 (최소 2200)")

    kw = keyword_count if keyword_count is not None else (
        body.lower().count(keyword.lower()) + title.lower().count(keyword.lower()))
    if kw < 8:
        errors.append(f"키워드 부족: {kw}회 (최소 8회)")

    subtitle_patterns = re.findall(r'(?:^|\n)\s*##\s+.+|(?:^|\n)\s*\*\*[^*]+\*\*', body)
    paragraph_count = len([p for p in body.split('\n\n') if p.strip()])
    if len(subtitle_patterns) < 4 and paragraph_count < 8:
        errors.append(f"소제목 {len(subtitle_patterns)}개, 문단 {paragraph_count}개 (소제목 4개+ 또는 문단 8개+ 필요)")

    has_photo = '[사진]' in body or '(사진)' in body or bool(re.search(r'\[이미지\d*\]', body))
    if not has_photo:
        errors.append("[사진] 또는 [이미지] 태그 없음")

    # SEO 분석 (warnings → errors에 추가)
    seo = analyze_seo(body, keyword, title)
    errors.extend(f"[SEO] {w}" for w in seo.warnings)
    return errors


# ── 카페SEO ──

CAFE_FORBIDDEN_WORDS = [
    "병원", "진료", "가격", "하더라구요",
]


def validate_cafe_seo(body: str, keyword: str, comments_text: str,
                      replies_text: str = '', sub_keywords: str = '',
                      target_char: int = 0, target_repeat: int = 0,
                      target_photo: int = 0) -> list[str]:
    errors = []
    c = len(body)
    # 글자수: 동적 기준이 있으면 ±100, 없으면 기본 범위
    if target_char > 0:
        if c < target_char - 100:
            errors.append(f"글자수 부족: {c}자 (기준 {target_char}±100)")
        if c > target_char + 100:
            errors.append(f"글자수 초과: {c}자 (기준 {target_char}±100)")
    else:
        if c < 800:
            errors.append(f"글자수 부족: {c}자 (최소 800)")
        if c > 1500:
            errors.append(f"글자수 초과: {c}자 (최대 1500)")

    # 키워드 반복: 동적 기준이 있으면 target_repeat+1, 없으면 기본 3~6
    kw_count = body.lower().count(keyword.lower())
    if target_repeat > 0:
        expected = target_repeat + 1
        if kw_count < expected:
            errors.append(f"키워드 부족: {kw_count}회 (기준 {expected}회)")
    else:
        if kw_count < 3:
            errors.append(f"키워드 부족: {kw_count}회 (최소 3회)")
        if kw_count > 6:
            errors.append(f"키워드 과다: {kw_count}회 (최대 6회)")

    # 서브 키워드 포함 여부
    if sub_keywords:
        for sk in [s.strip() for s in sub_keywords.split(',') if s.strip()]:
            if sk.lower() not in body.lower():
                errors.append(f"서브 키워드 미포함: '{sk}'")

    # 댓글 수량 검증
    comment_lines = [l.strip() for l in comments_text.strip().split("\n") if l.strip()]
    if len(comment_lines) < 10:
        errors.append(f"댓글 부족: {len(comment_lines)}개 (최소 10개)")

    # 답글 수량 검증
    if replies_text:
        reply_markers = re.findall(r'(?:^|\n)\s*→', replies_text)
        if len(reply_markers) < 10:
            errors.append(f"답글 부족: {len(reply_markers)}개 (최소 10개)")

    # 사진 태그 수 검증
    photo_tags = re.findall(r'\[어울릴 사진[^\]]*\]|\[이미지\d*\]', body)
    if target_photo > 0:
        expected_photo = target_photo + 1
        if len(photo_tags) < expected_photo:
            errors.append(f"사진 태그 부족: {len(photo_tags)}개 (기준 {expected_photo}개)")
    elif len(photo_tags) < 3:
        errors.append(f"사진 태그 부족: {len(photo_tags)}개 (최소 3개)")

    # 광고성 표현 검사
    for w in AD_WORDS_GENERIC:
        if w in body:
            errors.append(f"광고성 표현 발견: '{w}'")
            break

    # 금칙어 잔존 검사 (polish 후에도 남아있는지)
    for fw in CAFE_FORBIDDEN_WORDS:
        if fw in body and fw.lower() != keyword.lower():
            errors.append(f"금칙어 잔존: '{fw}'")

    # SEO 분석 (카페는 제목 없이 본문만 분석)
    seo = analyze_seo(body, keyword)
    errors.extend(f"[SEO] {w}" for w in seo.warnings)
    return errors


# ── 카페바이럴 ──

def _stage_text(stage: dict) -> str:
    if not stage:
        return ""
    parts = [p for p in [stage.get("title", ""), stage.get("body", "")] if p]
    return "\n".join(parts)


def validate_cafe_viral(stage1: dict, stage2: dict, stage3: dict) -> list[str]:
    errors = []
    s1 = _stage_text(stage1)
    s2 = _stage_text(stage2)
    s3 = _stage_text(stage3)

    if not s1:
        errors.append("1단계(일상글) 누락")
    if not s2:
        errors.append("2단계(고민글) 누락")
    if not s3:
        errors.append("3단계(침투글) 누락")

    if s1 and len(s1) < 200:
        errors.append(f"1단계 글자수 부족: {len(s1)}자 (최소 200)")
    if s2 and len(s2) < 200:
        errors.append(f"2단계 글자수 부족: {len(s2)}자 (최소 200)")
    if s3 and len(s3) < 200:
        errors.append(f"3단계 글자수 부족: {len(s3)}자 (최소 200)")

    for word in AD_WORDS_VIRAL:
        if word in s1:
            errors.append(f"1단계에 광고성 표현: '{word}'")
            break
        if word in s2:
            errors.append(f"2단계에 광고성 표현: '{word}'")
            break

    comments = stage3.get("comments", "") if stage3 else ""
    if not comments or len(comments.strip()) < 10:
        s3_body = stage3.get("body", "") if stage3 else ""
        comment_patterns = ["댓글1", "댓글2", "댓글 1", "댓글 2", "공감", "저도"]
        if not any(p in s3_body for p in comment_patterns):
            errors.append("3단계 댓글 누락 또는 너무 짧음")
    return errors


# ── 지식인 ──

def validate_jisikin(q_title: str, q_body: str, answer1: str, answer2: str, keyword: str) -> list[str]:
    errors = []
    if len(answer1) < 300:
        errors.append(f"답변1 글자수 부족: {len(answer1)}자 (최소 300)")
    if len(answer2) < 200:
        errors.append(f"답변2 글자수 부족: {len(answer2)}자 (최소 200)")
    if q_body.strip() == answer1.strip():
        errors.append("질문과 답변이 동일함")

    kw_lower = keyword.lower()
    title_has = kw_lower in q_title.lower()
    answer_has = kw_lower in answer1.lower() or kw_lower in answer2.lower()
    if not title_has and not answer_has:
        errors.append(f"키워드 '{keyword}' 미포함")

    if len(q_title.strip()) < 5:
        errors.append(f"질문 제목 너무 짧음: {len(q_title.strip())}자")
    if len(q_body.strip()) < 20:
        errors.append(f"질문 본문 너무 짧음: {len(q_body.strip())}자")

    ad_words = ["최고", "대박", "강추", "미쳤다", "링크", "바로가기", "구매하세요", "할인"]
    for w in ad_words:
        if w in answer1 or w in answer2:
            errors.append(f"광고성 표현 발견: '{w}'")
            break
    return errors


# ── 유튜브 댓글 ──

def validate_youtube_comment(comment_text: str, video_title: str) -> list[str]:
    errors = []
    c = len(comment_text.strip())
    if c < 50:
        errors.append(f"글자수 부족: {c}자 (최소 50)")
    if c > 200:
        errors.append(f"글자수 초과: {c}자 (최대 200)")

    stopwords = {'이런', '저런', '어떤', '무슨', '모든', '정말', '진짜', '너무', '아주',
                 '그리고', '하지만', '그래서', '왜냐하면', '때문에', '그런데', '따라서',
                 '있는', '없는', '하는', '되는', '같은', '이렇게', '그렇게', '어떻게',
                 '분들은', '사람들', '여러분', '우리가', '이것은', '그것은', '무조건',
                 '드셔야', '나옵니다', '좋은', '먹으면', '알고', '합니다', '됩니다'}
    title_words = re.findall(r'[가-힣]+', video_title)
    meaningful = [w for w in title_words if len(w) >= 2 and w not in stopwords]
    if meaningful:
        found = any(w in comment_text for w in meaningful)
        if not found:
            found = any(mw[:len(mw)-1] in comment_text for mw in meaningful if len(mw) > 2)
        if not found:
            errors.append(f"영상 제목 관련 단어 미포함")

    spam = [r'http[s]?://', r'www\.', r'\.com/', r'\.kr/']
    for pat in spam:
        if re.search(pat, comment_text):
            errors.append(f"스팸성 패턴 발견")
            break

    ad_words = ['구매하세요', '지금 바로', '할인', '최저가', '무료배송', '이벤트', '쿠폰']
    for w in ad_words:
        if w in comment_text:
            errors.append(f"광고성 단어 발견: {w}")
            break
    return errors


# ── 틱톡 ──

def _clean_tiktok_script(raw: str) -> str:
    lines = raw.strip().split("\n")
    cleaned = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if re.match(r'^\[(?:후킹|문제\s*공감|전환점|마무리)\]', s):
            continue
        if re.match(r'^\[연출[:：]', s):
            continue
        s = s.strip('"').strip('\u201c').strip('\u201d')
        if s:
            cleaned.append(s)
    return "\n".join(cleaned)


def validate_tiktok(script_text: str) -> list[str]:
    errors = []
    text = _clean_tiktok_script(script_text)
    c = len(text)
    if c < 200:
        errors.append(f"글자수 부족: {c}자 (최소 200)")
    if c > 500:
        errors.append(f"글자수 초과: {c}자 (최대 500)")

    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    first = lines[0] if lines else ""
    errors.extend(_check_hook(first))
    errors.extend(_check_emoji(text))
    errors.extend(_check_meta_tags(text))
    return errors


# ── 커뮤니티 ──

def validate_community(post_body: str, comments_text: str) -> list[str]:
    errors = []
    if len(post_body.strip()) < 200:
        errors.append(f"게시글 글자수 부족: {len(post_body.strip())}자 (최소 200)")

    comment_lines = [l.strip() for l in comments_text.strip().split("\n") if l.strip()]
    if len(comment_lines) < 3:
        errors.append(f"댓글 부족: {len(comment_lines)}개 (최소 3)")

    full = post_body + " " + comments_text
    for pat in AD_PATTERNS_COMMUNITY:
        if re.search(pat, full):
            errors.append(f"광고성 표현 발견: {pat}")
            break
    return errors


# ── 파워컨텐츠 ──

def validate_powercontent(ad_title: str, ad_desc: str, body: str,
                          keyword: str, char_count: int = None) -> list[str]:
    errors = []
    c = char_count if char_count is not None else len(body)
    if c < 3000:
        errors.append(f"글자수 부족: {c}자 (최소 3000)")

    kw = body.lower().count(keyword.lower())
    if kw < 10:
        errors.append(f"키워드 부족: {kw}회 (최소 10회)")

    if not ad_title or len(ad_title.strip()) < 2:
        errors.append("광고 제목 없음")
    if not ad_desc or len(ad_desc.strip()) < 2:
        errors.append("광고 설명 없음")

    # SEO 분석
    seo = analyze_seo(body, keyword, ad_title)
    errors.extend(f"[SEO] {w}" for w in seo.warnings)
    return errors


# ── 쓰레드 ──

def validate_threads(text: str) -> list[str]:
    errors = []
    c = len(text)
    if c < 100:
        errors.append(f"글자수 부족: {c}자 (최소 100)")
    if c > 500:
        errors.append(f"글자수 초과: {c}자 (최대 500)")

    emoji_pattern = re.compile(
        r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF'
        r'\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF'
        r'\U0001F900-\U0001F9FF\U0001FA00-\U0001FAFF'
        r'\U00002702-\U000027B0\U0000FE00-\U0000FE0F'
        r'\U0000200D\U00002600-\U000026FF\U00002700-\U000027BF]'
    )
    emoji_count = len(emoji_pattern.findall(text))
    if emoji_count > 5:
        errors.append(f"이모지 과다: {emoji_count}개 (최대 5개)")

    ad_words = ["최저가", "할인", "구매링크", "무료배송", "선착순", "한정수량",
                "지금 바로 구매", "클릭하세요", "www.", "http"]
    ad_count = sum(1 for w in ad_words if w in text)
    if ad_count >= 3:
        errors.append(f"광고성 과도: 광고 키워드 {ad_count}개 발견")

    formal = len(re.findall(r'(?:합니다|습니다|입니다|세요|시오)', text))
    casual = len(re.findall(r'(?:거든|잖아|했음|인듯|ㅋㅋ|ㅎㅎ|임다)', text))
    if formal > 3 and casual > 3:
        errors.append("말투 혼용")
    return errors
