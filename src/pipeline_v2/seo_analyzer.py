"""SEO 분석기 — 코드 기반 객관 점수.

python-seo-analyzer(sethblack) 참고하되, 웹 크롤링 없이
생성된 콘텐츠 텍스트를 직접 분석한다.

주요 분석:
- 키워드 밀도 (%) + 과다/과소 판정
- 헤딩 구조 (H2/H3 계층)
- 제목 최적화 (키워드 위치, 길이)
- 읽기 용이성 (문장 길이, 문단 밀도)
- 종합 SEO 점수 (0~100)
"""
import re
from dataclasses import dataclass, field


@dataclass
class SEOResult:
    score: int = 0
    keyword_density: dict = field(default_factory=dict)
    heading_structure: dict = field(default_factory=dict)
    title_optimization: dict = field(default_factory=dict)
    readability: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)

    def summary_text(self) -> str:
        """검수 로그용 1줄 요약."""
        parts = [f"SEO {self.score}/100"]
        kd = self.keyword_density
        if kd:
            parts.append(f"밀도:{kd.get('density_pct', 0):.1f}%({kd.get('verdict', '')})")
        hs = self.heading_structure
        if hs:
            parts.append(f"헤딩:{'OK' if hs.get('hierarchy_ok') else 'NG'}")
        to = self.title_optimization
        if to:
            parts.append(f"제목:{to.get('score', 0)}점")
        rd = self.readability
        if rd:
            parts.append(f"가독성:{rd.get('score', 0)}점")
        return " | ".join(parts)


# ── 키워드 밀도 ──────────────────────────────────────────────────

def keyword_density(text: str, keyword: str) -> dict:
    """키워드 밀도(%) 계산 + 과다/과소/적정 판정.

    한국어는 글자 기반이므로 영어보다 밀도가 높게 나온다.
    적정 범위: 1.0% ~ 5.0% (한국어 SEO 기준, 글자 기반)
    최적 지점: 약 2.5%
    """
    if not text or not keyword:
        return {"count": 0, "total_chars": 0, "density_pct": 0.0, "verdict": "N/A", "score": 0}

    text_lower = text.lower()
    kw_lower = keyword.lower()
    count = text_lower.count(kw_lower)
    total_chars = len(text_lower)
    kw_chars = len(kw_lower) * count

    density_pct = (kw_chars / total_chars * 100) if total_chars > 0 else 0.0

    if density_pct < 1.0:
        verdict = "과소"
        score = max(0, int(density_pct / 1.0 * 60))
    elif density_pct <= 5.0:
        verdict = "적정"
        # 2.5% 근처가 최적
        diff = abs(density_pct - 2.5)
        score = max(60, 100 - int(diff * 15))
    else:
        verdict = "과다"
        score = max(0, 100 - int((density_pct - 5.0) * 15))

    return {
        "count": count,
        "total_chars": total_chars,
        "density_pct": round(density_pct, 2),
        "verdict": verdict,
        "score": min(100, max(0, score)),
    }


# ── 헤딩 구조 ──────────────────────────────────────────────────

def heading_structure(text: str) -> dict:
    """H2/H3 계층 검증 + 논리적 순서 체크.

    마크다운 ## / ### 또는 **볼드** 소제목 인식.
    """
    h2_pattern = re.findall(r'(?:^|\n)\s*##(?!#)\s+(.+)', text)
    h3_pattern = re.findall(r'(?:^|\n)\s*###(?!#)\s+(.+)', text)
    bold_pattern = re.findall(r'(?:^|\n)\s*\*\*([^*]+)\*\*', text)

    h2_count = len(h2_pattern)
    h3_count = len(h3_pattern)
    bold_count = len(bold_pattern)

    issues = []
    hierarchy_ok = True

    # H3이 있는데 H2가 없으면 계층 문제
    if h3_count > 0 and h2_count == 0:
        issues.append("H3(###)이 H2(##) 없이 사용됨")
        hierarchy_ok = False

    # 전체 소제목 수 (H2 + H3 + bold)
    total_headings = h2_count + h3_count + bold_count
    if total_headings < 3:
        issues.append(f"소제목 부족: {total_headings}개 (최소 3개 권장)")

    # 점수: 소제목 4개 이상 + 계층 정상 = 100
    score = 0
    if total_headings >= 4 and hierarchy_ok:
        score = 100
    elif total_headings >= 3 and hierarchy_ok:
        score = 80
    elif total_headings >= 2:
        score = 60
    elif total_headings >= 1:
        score = 40
    else:
        score = 20

    if not hierarchy_ok:
        score = max(0, score - 20)

    return {
        "h2_count": h2_count,
        "h3_count": h3_count,
        "bold_headings": bold_count,
        "total_headings": total_headings,
        "hierarchy_ok": hierarchy_ok,
        "issues": issues,
        "score": score,
    }


# ── 제목 최적화 ──────────────────────────────────────────────────

def title_optimization(title: str, keyword: str) -> dict:
    """제목 SEO 분석: 키워드 위치, 길이 적정성."""
    if not title:
        return {"length": 0, "length_ok": False, "keyword_present": False,
                "keyword_position": -1, "score": 0, "issues": ["제목 없음"]}

    length = len(title)
    issues = []

    # 길이: 15~40자가 적정 (네이버 검색 노출 기준)
    length_ok = 15 <= length <= 40
    if length < 15:
        issues.append(f"제목 너무 짧음: {length}자 (15자 이상 권장)")
    elif length > 40:
        issues.append(f"제목 너무 김: {length}자 (40자 이하 권장)")

    # 키워드 포함 + 위치
    kw_lower = keyword.lower() if keyword else ""
    title_lower = title.lower()
    keyword_present = kw_lower in title_lower if kw_lower else False
    keyword_position = title_lower.find(kw_lower) if keyword_present else -1

    if not keyword_present and kw_lower:
        issues.append("제목에 키워드 미포함")

    # 키워드가 앞쪽(전체의 50% 이내)에 있으면 가산
    front_bonus = keyword_present and keyword_position <= len(title) * 0.5

    # 점수 계산
    score = 0
    if length_ok:
        score += 40
    elif length < 15:
        score += max(0, 40 - (15 - length) * 5)
    else:
        score += max(0, 40 - (length - 40) * 3)

    if keyword_present:
        score += 40
        if front_bonus:
            score += 20
    else:
        score += 0

    return {
        "length": length,
        "length_ok": length_ok,
        "keyword_present": keyword_present,
        "keyword_position": keyword_position,
        "front_bonus": front_bonus,
        "score": min(100, max(0, score)),
        "issues": issues,
    }


# ── 읽기 용이성 ──────────────────────────────────────────────────

def readability(text: str) -> dict:
    """문장 길이 + 문단 밀도 분석.

    한국어 기준:
    - 평균 문장 길이 30자 이하 = 좋음
    - 문단당 3~5문장 = 좋음
    """
    if not text:
        return {"avg_sentence_len": 0, "avg_paragraph_len": 0,
                "sentence_count": 0, "paragraph_count": 0,
                "score": 0, "issues": ["텍스트 없음"]}

    # 문장 분리 (마침표, 물음표, 느낌표, 줄바꿈)
    sentences = re.split(r'[.!?。]\s*|\n', text)
    sentences = [s.strip() for s in sentences if s.strip() and len(s.strip()) > 5]
    sentence_count = len(sentences)

    avg_sentence_len = sum(len(s) for s in sentences) / sentence_count if sentence_count else 0

    # 문단 분리 (빈 줄)
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    paragraph_count = len(paragraphs)

    avg_paragraph_len = sentence_count / paragraph_count if paragraph_count else 0

    issues = []

    # 문장 길이 점수
    if avg_sentence_len <= 30:
        sentence_score = 50
    elif avg_sentence_len <= 45:
        sentence_score = max(20, 50 - int((avg_sentence_len - 30) * 2))
        issues.append(f"평균 문장 {avg_sentence_len:.0f}자 — 30자 이하 권장")
    else:
        sentence_score = 10
        issues.append(f"평균 문장 {avg_sentence_len:.0f}자 — 30자 이하 권장")

    # 문단 밀도 점수
    if 3 <= avg_paragraph_len <= 5:
        paragraph_score = 50
    elif 2 <= avg_paragraph_len <= 7:
        paragraph_score = 35
    else:
        paragraph_score = 20
        if avg_paragraph_len > 7:
            issues.append(f"문단당 평균 {avg_paragraph_len:.1f}문장 — 3~5문장 권장")

    score = sentence_score + paragraph_score

    return {
        "avg_sentence_len": round(avg_sentence_len, 1),
        "avg_paragraph_len": round(avg_paragraph_len, 1),
        "sentence_count": sentence_count,
        "paragraph_count": paragraph_count,
        "score": min(100, max(0, score)),
        "issues": issues,
    }


# ── 종합 분석 ──────────────────────────────────────────────────

def analyze_seo(text: str, keyword: str, title: str = "") -> SEOResult:
    """SEO 종합 분석. 4개 항목 분석 → 가중 평균 점수.

    가중치:
    - 키워드 밀도: 35%
    - 헤딩 구조: 25%
    - 제목 최적화: 25%
    - 읽기 용이성: 15%
    """
    kd = keyword_density(text, keyword)
    hs = heading_structure(text)
    to = title_optimization(title, keyword)
    rd = readability(text)

    # 가중 평균 (제목 없으면 가중치 재분배)
    if title:
        weighted = (
            kd["score"] * 0.35 +
            hs["score"] * 0.25 +
            to["score"] * 0.25 +
            rd["score"] * 0.15
        )
    else:
        # 제목 없으면 밀도/헤딩/가독성으로 재분배
        weighted = (
            kd["score"] * 0.40 +
            hs["score"] * 0.35 +
            rd["score"] * 0.25
        )
    overall = min(100, max(0, round(weighted)))

    # warnings 수집
    warnings = []
    if kd["verdict"] == "과소":
        warnings.append(f"키워드 밀도 과소: {kd['density_pct']}% (1.0%~5.0% 권장)")
    elif kd["verdict"] == "과다":
        warnings.append(f"키워드 밀도 과다: {kd['density_pct']}% (1.0%~5.0% 권장)")
    warnings.extend(hs.get("issues", []))
    if title:
        warnings.extend(to.get("issues", []))
    warnings.extend(rd.get("issues", []))

    return SEOResult(
        score=overall,
        keyword_density=kd,
        heading_structure=hs,
        title_optimization=to,
        readability=rd,
        warnings=warnings,
    )
