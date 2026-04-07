"""숏츠 벤치마킹 — YouTube 레퍼런스 크롤링 + AI 분석 + 패턴 추출.

벤치마크 시스템 흐름:
  URL 3~4개 → 메타데이터/자막/댓글 수집 → AI 분석 → 패턴 추출 → 팩트체크
"""
import json
import re
import requests
from typing import Optional

from .common import call_api, call_api_json, get_event


def _extract_video_id(url: str) -> Optional[str]:
    """YouTube URL에서 video ID 추출."""
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([a-zA-Z0-9_-]{11})',
        r'youtube\.com/embed/([a-zA-Z0-9_-]{11})',
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return None


def fetch_video_metadata(url: str) -> dict:
    """YouTube 영상 메타데이터 수집 (oembed API — API 키 불필요)."""
    video_id = _extract_video_id(url)
    if not video_id:
        return {"error": f"유효하지 않은 URL: {url}", "url": url}

    meta = {"video_id": video_id, "url": url}

    # oEmbed로 기본 메타데이터
    try:
        oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
        r = requests.get(oembed_url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            meta["title"] = data.get("title", "")
            meta["author"] = data.get("author_name", "")
            meta["thumbnail"] = data.get("thumbnail_url", "")
    except Exception as e:
        meta["oembed_error"] = str(e)

    return meta


def fetch_transcript_via_api(url: str) -> str:
    """서버 API를 통한 자막 수집 (MCP youtube-transcript 활용)."""
    try:
        result = call_api_json("/api/shorts/transcript", {"url": url}, timeout=60)
        return result.get("transcript", "")
    except Exception:
        return ""


def fetch_comments_via_api(video_id: str, max_results: int = 20) -> list[str]:
    """YouTube Data API로 댓글 수집 (서버 API 경유)."""
    try:
        result = call_api_json(
            "/api/shorts/comments",
            {"video_id": video_id, "max_results": max_results},
            timeout=30,
        )
        return result.get("comments", [])
    except Exception:
        return []


def benchmark_from_urls(urls: list[str]) -> dict:
    """YouTube URL들에서 레퍼런스 데이터 수집.

    Returns:
        {
            "references": [...],  # 각 영상의 메타+자막+댓글
            "count": int,
        }
    """
    references = []
    for url in urls:
        url = url.strip()
        if not url:
            continue

        ref = fetch_video_metadata(url)
        video_id = ref.get("video_id")

        # 자막 수집
        transcript = fetch_transcript_via_api(url)
        if transcript:
            ref["transcript"] = transcript

        # 댓글 수집
        if video_id:
            comments = fetch_comments_via_api(video_id)
            if comments:
                ref["comments"] = comments

        references.append(ref)

    return {"references": references, "count": len(references)}


def analyze_references(references: list[dict]) -> dict:
    """Claude에게 레퍼런스 패턴 분석 요청.

    Returns:
        {
            "analysis": str,  # AI 분석 텍스트
            "success_factors": [...],
            "hook_patterns": [...],
            "structure_patterns": [...],
            "tone": str,
        }
    """
    if not references:
        return {"analysis": "", "skipped": True}

    # 분석용 텍스트 구성
    ref_texts = []
    for i, ref in enumerate(references, 1):
        parts = [f"## 영상 {i}: {ref.get('title', '제목 없음')}"]
        if ref.get("transcript"):
            parts.append(f"자막:\n{ref['transcript'][:2000]}")
        if ref.get("comments"):
            parts.append(f"인기 댓글:\n" + "\n".join(ref["comments"][:10]))
        ref_texts.append("\n".join(parts))

    ref_block = "\n\n---\n\n".join(ref_texts)

    results = call_api("/api/shorts/analyze-refs", {
        "references_text": ref_block,
    }, timeout=120)

    analysis_d = get_event(results, "analysis")
    if analysis_d:
        return {
            "analysis": analysis_d.get("text", ""),
            "success_factors": analysis_d.get("success_factors", []),
            "hook_patterns": analysis_d.get("hook_patterns", []),
            "structure_patterns": analysis_d.get("structure_patterns", []),
            "tone": analysis_d.get("tone", ""),
        }

    return {"analysis": "", "skipped": True, "reason": "분석 API 미응답"}


def extract_patterns(analyses: list[dict]) -> dict:
    """여러 분석 결과에서 공통 패턴 추출.

    Returns:
        {
            "common_hooks": [...],
            "common_structure": str,
            "tone_guide": str,
            "key_elements": [...],
        }
    """
    if not analyses or all(a.get("skipped") for a in analyses):
        return {"skipped": True}

    texts = [a.get("analysis", "") for a in analyses if a.get("analysis")]
    if not texts:
        return {"skipped": True}

    combined = "\n\n".join(texts)

    results = call_api("/api/shorts/extract-patterns", {
        "analyses_text": combined,
    }, timeout=120)

    patterns_d = get_event(results, "patterns")
    if patterns_d:
        return {
            "common_hooks": patterns_d.get("common_hooks", []),
            "common_structure": patterns_d.get("common_structure", ""),
            "tone_guide": patterns_d.get("tone_guide", ""),
            "key_elements": patterns_d.get("key_elements", []),
        }

    return {"skipped": True, "reason": "패턴 추출 API 미응답"}


def run_benchmark(urls: list[str]) -> dict:
    """벤치마킹 전체 흐름 실행.

    Returns: {references, analysis, patterns}
    """
    print("  레퍼런스 수집 중...")
    ref_data = benchmark_from_urls(urls)
    refs = ref_data["references"]

    if not refs:
        print("  레퍼런스 없음 — 벤치마킹 스킵")
        return {"skipped": True, "references": [], "analysis": {}, "patterns": {}}

    print(f"  {len(refs)}개 영상 수집 완료")

    # AI 분석
    print("  AI 분석 중...")
    analysis = analyze_references(refs)

    # 패턴 추출
    print("  패턴 추출 중...")
    patterns = extract_patterns([analysis])

    return {
        "references": refs,
        "analysis": analysis,
        "patterns": patterns,
    }
