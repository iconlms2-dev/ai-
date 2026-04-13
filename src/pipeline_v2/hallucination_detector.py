"""마케팅 콘텐츠 환각 탐지기.

OCR(Open Code Review)의 3계층 환각 탐지 개념을 마케팅 콘텐츠에 맞게 변환.
- L1 패턴 탐지: 정규식으로 의심 패턴 추출 (무비용, 빠름)
- L2 제품 대조: product 정보와 콘텐츠 사실 매칭 (무비용, 빠름)
- L3 AI 판단: Gemini 프롬프트에 의심 항목 포함 (기존 호출에 통합)
"""
import re
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ── 환각 유형 ──

class HallucinationType:
    PHANTOM_FACT = "phantom-fact"          # 미확인 통계/수치
    PHANTOM_FEATURE = "phantom-feature"    # 제품에 없는 기능
    PHANTOM_SOURCE = "phantom-source"      # 가짜 출처/전문가 인용
    PHANTOM_CERT = "phantom-cert"          # 가짜 인증/승인 (법적 위험)
    PHANTOM_URL = "phantom-url"            # 검증 불가 URL
    PHANTOM_REVIEW = "phantom-review"      # 조작된 후기/인물


# ── 심각도 ──

class Severity:
    CRITICAL = "critical"  # 법적 위험 (인증/승인 환각)
    HIGH = "high"          # 제품 불일치
    MEDIUM = "medium"      # 미확인 출처/인용
    LOW = "low"            # 미확인 통계 (경고)


# ── 감점표 ──

SEVERITY_DEDUCTIONS = {
    Severity.CRITICAL: 20,
    Severity.HIGH: 15,
    Severity.MEDIUM: 10,
    Severity.LOW: 3,
}


# ── 채널별 환각 프로필 ──

CHANNEL_PROFILES = {
    "blog": {
        "focus": [HallucinationType.PHANTOM_FACT, HallucinationType.PHANTOM_SOURCE],
        "weight": 1.0,
    },
    "cafe-seo": {
        "focus": [HallucinationType.PHANTOM_FEATURE, HallucinationType.PHANTOM_FACT],
        "weight": 1.0,
    },
    "cafe-viral": {
        "focus": [HallucinationType.PHANTOM_FEATURE],
        "weight": 0.7,
    },
    "jisikin": {
        "focus": [HallucinationType.PHANTOM_SOURCE, HallucinationType.PHANTOM_FACT],
        "weight": 1.0,
    },
    "powercontent": {
        "focus": [HallucinationType.PHANTOM_CERT, HallucinationType.PHANTOM_FEATURE],
        "weight": 1.2,
    },
    "youtube": {
        "focus": [HallucinationType.PHANTOM_FACT],
        "weight": 0.5,
    },
    "tiktok": {
        "focus": [HallucinationType.PHANTOM_FACT],
        "weight": 0.5,
    },
    "shorts": {
        "focus": [HallucinationType.PHANTOM_FACT],
        "weight": 0.5,
    },
    "community": {
        "focus": [HallucinationType.PHANTOM_FEATURE],
        "weight": 0.7,
    },
    "threads": {
        "focus": [HallucinationType.PHANTOM_FEATURE],
        "weight": 0.7,
    },
}


@dataclass
class HallucinationIssue:
    """환각 의심 항목."""
    type: str              # HallucinationType
    severity: str          # Severity
    text: str              # 의심 원문
    reason: str            # 탐지 사유
    paragraph: int = 0     # 몇 번째 문단
    deduction: int = 0     # 감점


@dataclass
class HallucinationReport:
    """환각 탐지 결과."""
    issues: list = field(default_factory=list)
    score: int = 100       # 100 - 총감점
    total_deduction: int = 0
    l1_count: int = 0      # L1 패턴 탐지 건수
    l2_count: int = 0      # L2 제품 대조 건수

    def add_issue(self, issue: HallucinationIssue):
        self.issues.append(issue)
        self.total_deduction += issue.deduction
        self.score = max(0, 100 - self.total_deduction)

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "total_deduction": self.total_deduction,
            "l1_count": self.l1_count,
            "l2_count": self.l2_count,
            "issue_count": len(self.issues),
            "issues": [
                {
                    "type": i.type,
                    "severity": i.severity,
                    "text": i.text[:100],
                    "reason": i.reason,
                    "paragraph": i.paragraph,
                    "deduction": i.deduction,
                }
                for i in self.issues
            ],
        }

    def summary_text(self) -> str:
        """Gemini L3 검증용 컨텍스트 텍스트."""
        if not self.issues:
            return ""
        lines = ["[환각 의심 항목]"]
        for i, iss in enumerate(self.issues, 1):
            lines.append(f"{i}. [{iss.type}] {iss.reason} — \"{iss.text[:60]}\"")
        return "\n".join(lines)


# ── L1: 패턴 탐지 (정규식, 무비용) ──

# 미확인 통계 패턴
_STAT_PATTERNS = [
    re.compile(r'(\d{1,3}(?:\.\d+)?)\s*%\s*(?:의|가|이|효과|개선|향상|감소|증가|절감|만족)', re.IGNORECASE),
    re.compile(r'(\d+)\s*배\s*(?:이상|향상|개선|효과|증가|빠른|빠르)', re.IGNORECASE),
    re.compile(r'(\d{1,3}(?:,\d{3})*)\s*명\s*(?:이상|이|이하)?\s*(?:사용|구매|선택|참여|만족)', re.IGNORECASE),
]

# 출처 없는 통계의 예외 (허용)
_STAT_SAFE_MARKERS = [
    "에 따르면", "조사 결과", "연구에 의하면", "자체 조사",
    "출처:", "※", "기준:", "기준 ", "자사 데이터",
]

# 가짜 출처/인용 패턴
_SOURCE_PATTERNS = [
    re.compile(r'(?:서울대|연세대|고려대|한양대|KAIST|MIT|하버드|스탠포드|옥스포드)\s*(?:대학교?)?\s*(?:연구팀|교수|연구진|연구소)', re.IGNORECASE),
    re.compile(r'(?:국내|해외|미국|일본|유럽)\s*(?:유명|저명)?\s*(?:대학|기관|연구소|학회)\s*(?:에서|의|발표)', re.IGNORECASE),
    re.compile(r'[가-힣]{2,4}\s*(?:교수|박사|전문가|의사|약사|변호사)\s*(?:는|가|도|의|에\s*따르면)', re.IGNORECASE),
    re.compile(r'(?:논문|학술지|저널|연구|임상(?:실험|시험))\s*(?:에서|에\s*따르면|결과|발표)', re.IGNORECASE),
]

# 인증/승인 환각 패턴 (법적 위험 — 높은 감점)
_CERT_PATTERNS = [
    re.compile(r'(?:식약처|식품의약품안전처|FDA|CE|GMP|HACCP|ISO\s*\d+|KS)\s*(?:인증|승인|허가|등록|인정|검증|통과)', re.IGNORECASE),
    re.compile(r'(?:특허|실용신안)\s*(?:등록|출원|획득|보유)', re.IGNORECASE),
    re.compile(r'(?:1등|1위|최초|유일|독보적)\s*(?:달성|기록|인정|선정)', re.IGNORECASE),
]

# 가격/수치 패턴
_PRICE_PATTERNS = [
    re.compile(r'(?:정가|원가|시중가|판매가|할인가)\s*(?:는?)?\s*(\d{1,3}(?:,\d{3})*)\s*원', re.IGNORECASE),
]

# 가짜 URL 패턴
_FAKE_URL_PATTERN = re.compile(r'https?://[^\s<>"\')\]]{5,}', re.IGNORECASE)
_SAFE_URL_DOMAINS = [
    "naver.com", "daum.net", "google.com", "youtube.com",
    "instagram.com", "facebook.com", "twitter.com", "tiktok.com",
    "coupang.com", "kakao.com", "notion.so", "threads.net",
]

# 조작된 후기/인물 패턴
_FAKE_REVIEW_PATTERNS = [
    re.compile(r'[가-힣]O{1,2}님', re.IGNORECASE),             # 김OO님, 이O님
    re.compile(r'[가-힣]{1,2}\s*[*○●★☆]{1,3}\s*님'),           # 김**님, 이●●님
    re.compile(r'(?:실제\s*)?(?:사용|구매|체험)\s*(?:자|고객)\s*(?:후기|리뷰|평가)'),  # "실제 사용자 후기"
    re.compile(r'[가-힣]{2,4}\s*\(\d{2,3}세\s*[,/]\s*(?:여|남|직장인|주부|학생)\)'),  # "박지은(32세, 직장인)"
]


def _detect_l1(text: str, channel: str) -> list[HallucinationIssue]:
    """L1 패턴 기반 환각 의심 항목 추출."""
    issues = []
    profile = CHANNEL_PROFILES.get(channel, {"focus": [], "weight": 1.0})
    focus_types = profile["focus"]
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]

    for para_idx, para in enumerate(paragraphs, 1):

        # phantom-fact: 미확인 통계
        if HallucinationType.PHANTOM_FACT in focus_types:
            for pat in _STAT_PATTERNS:
                match = pat.search(para)
                if match:
                    # 출처 마커 있으면 스킵
                    if any(marker in para for marker in _STAT_SAFE_MARKERS):
                        continue
                    issues.append(HallucinationIssue(
                        type=HallucinationType.PHANTOM_FACT,
                        severity=Severity.LOW,
                        text=para[:80],
                        reason=f"출처 없는 통계 수치 '{match.group(0)}'",
                        paragraph=para_idx,
                        deduction=SEVERITY_DEDUCTIONS[Severity.LOW],
                    ))
                    break  # 같은 문단 중복 방지

        # phantom-source: 가짜 출처/인용
        if HallucinationType.PHANTOM_SOURCE in focus_types:
            for pat in _SOURCE_PATTERNS:
                match = pat.search(para)
                if match:
                    issues.append(HallucinationIssue(
                        type=HallucinationType.PHANTOM_SOURCE,
                        severity=Severity.MEDIUM,
                        text=para[:80],
                        reason=f"검증 불가 출처/인용 '{match.group(0)}'",
                        paragraph=para_idx,
                        deduction=SEVERITY_DEDUCTIONS[Severity.MEDIUM],
                    ))
                    break

        # phantom-cert: 인증/승인 환각 (법적 위험)
        if HallucinationType.PHANTOM_CERT in focus_types:
            for pat in _CERT_PATTERNS:
                match = pat.search(para)
                if match:
                    issues.append(HallucinationIssue(
                        type=HallucinationType.PHANTOM_CERT,
                        severity=Severity.CRITICAL,
                        text=para[:80],
                        reason=f"인증/승인 주장 '{match.group(0)}' — 사실 확인 필요",
                        paragraph=para_idx,
                        deduction=SEVERITY_DEDUCTIONS[Severity.CRITICAL],
                    ))
                    break

        # 가격 패턴 (모든 채널)
        for pat in _PRICE_PATTERNS:
            match = pat.search(para)
            if match:
                issues.append(HallucinationIssue(
                    type=HallucinationType.PHANTOM_FACT,
                    severity=Severity.LOW,
                    text=para[:80],
                    reason=f"가격 정보 '{match.group(0)}' — 제품 정보와 대조 필요",
                    paragraph=para_idx,
                    deduction=SEVERITY_DEDUCTIONS[Severity.LOW],
                ))
                break

        # 가짜 URL (모든 채널)
        url_match = _FAKE_URL_PATTERN.search(para)
        if url_match:
            url_text = url_match.group(0)
            if not any(domain in url_text for domain in _SAFE_URL_DOMAINS):
                issues.append(HallucinationIssue(
                    type=HallucinationType.PHANTOM_URL,
                    severity=Severity.HIGH,
                    text=para[:80],
                    reason=f"검증 불가 URL '{url_text[:50]}'",
                    paragraph=para_idx,
                    deduction=SEVERITY_DEDUCTIONS[Severity.HIGH],
                ))

        # 조작된 후기/인물 (모든 채널)
        for pat in _FAKE_REVIEW_PATTERNS:
            match = pat.search(para)
            if match:
                issues.append(HallucinationIssue(
                    type=HallucinationType.PHANTOM_REVIEW,
                    severity=Severity.MEDIUM,
                    text=para[:80],
                    reason=f"조작된 후기/인물 패턴 '{match.group(0)}'",
                    paragraph=para_idx,
                    deduction=SEVERITY_DEDUCTIONS[Severity.MEDIUM],
                ))
                break

    return issues


# ── L2: 제품 정보 대조 (무비용) ──

def _detect_l2(text: str, product: dict, channel: str) -> list[HallucinationIssue]:
    """L2 제품 정보 대조. product dict에서 알려진 특징과 콘텐츠를 비교."""
    if not product:
        return []

    issues = []
    profile = CHANNEL_PROFILES.get(channel, {"focus": [], "weight": 1.0})

    if HallucinationType.PHANTOM_FEATURE not in profile["focus"]:
        return []

    # 제품 정보에서 알려진 특징 추출
    known_features = set()
    for key in ("features", "characteristics", "특징", "성분", "기능"):
        val = product.get(key, "")
        if isinstance(val, str):
            known_features.update(f.strip() for f in val.split(",") if f.strip())
        elif isinstance(val, list):
            known_features.update(str(f).strip() for f in val if f)

    # 제품명
    product_name = product.get("name", product.get("이름", product.get("product_name", "")))

    if not known_features and not product_name:
        return []

    # 기능/성분 관련 키워드 추출 패턴
    feature_patterns = [
        re.compile(r'(?:기능|효과|효능|성분|특징|장점)(?:이|은|는|으로|으로는)?\s*([^.!?\n]{3,30})', re.IGNORECASE),
        re.compile(r'([가-힣a-zA-Z]{2,15})\s*(?:기능|효과|효능|성분)\s*(?:이|을|를)?', re.IGNORECASE),
    ]

    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    text_lower = text.lower()

    for para_idx, para in enumerate(paragraphs, 1):
        for pat in feature_patterns:
            matches = pat.findall(para)
            for match_text in matches:
                match_clean = match_text.strip()
                if len(match_clean) < 2:
                    continue
                # 알려진 특징에 포함되면 OK
                if any(match_clean in feat or feat in match_clean for feat in known_features):
                    continue
                # 제품명이 포함된 일반 설명은 OK
                if product_name and product_name in match_clean:
                    continue
                # 너무 일반적인 표현 스킵
                skip_words = (
                    "좋은", "많은", "다양한", "우수한", "탁월한", "뛰어난",
                    "좋아요", "좋습니다", "있습니다", "됩니다", "합니다",
                    "정말", "매우", "아주", "너무", "진짜", "완전",
                    "그런", "이런", "저런", "같은", "하는", "있는",
                )
                if any(sw in match_clean for sw in skip_words) or len(match_clean) > 20:
                    continue

                issues.append(HallucinationIssue(
                    type=HallucinationType.PHANTOM_FEATURE,
                    severity=Severity.HIGH,
                    text=para[:80],
                    reason=f"제품 정보에 없는 특징/기능 '{match_clean}'",
                    paragraph=para_idx,
                    deduction=SEVERITY_DEDUCTIONS[Severity.HIGH],
                ))
                break  # 같은 문단 중복 방지

    return issues


# ── 메인 함수 ──

def detect_hallucinations(
    text: str,
    channel: str,
    product: Optional[dict] = None,
) -> HallucinationReport:
    """콘텐츠 환각 탐지 (L1 + L2).

    Args:
        text: 검수 대상 텍스트
        channel: 채널명
        product: 제품 정보 dict (없으면 L2 스킵)

    Returns:
        HallucinationReport — L3는 Gemini 프롬프트에 summary_text()로 전달
    """
    report = HallucinationReport()
    profile = CHANNEL_PROFILES.get(channel, {"focus": [], "weight": 1.0})
    weight = profile["weight"]

    if not text or not text.strip():
        return report

    # L1: 패턴 탐지
    l1_issues = _detect_l1(text, channel)
    report.l1_count = len(l1_issues)
    for issue in l1_issues:
        issue.deduction = int(issue.deduction * weight)
        report.add_issue(issue)

    # L2: 제품 정보 대조
    l2_issues = _detect_l2(text, product or {}, channel)
    report.l2_count = len(l2_issues)
    for issue in l2_issues:
        issue.deduction = int(issue.deduction * weight)
        report.add_issue(issue)

    logger.info(
        "환각 탐지 [%s]: L1=%d건, L2=%d건, 총감점=%d, 점수=%d",
        channel, report.l1_count, report.l2_count,
        report.total_deduction, report.score,
    )

    return report
