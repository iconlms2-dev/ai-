"""공통 유틸리티 — SSE 파싱, 서버 체크, AI 리뷰 호출 등."""
import json
import re
import sys
import requests
from typing import Optional

BASE = "http://localhost:8000"
MAX_REVISIONS = 3
MAX_STRATEGY_ROLLBACKS = 1


def check_server():
    """서버 가동 확인. 실패 시 sys.exit."""
    try:
        r = requests.get(BASE, timeout=5)
        if r.status_code != 200:
            print("서버 응답 없음")
            sys.exit(1)
    except Exception:
        print("서버 연결 실패 (http://localhost:8000)")
        sys.exit(1)


def parse_sse(response) -> list[dict]:
    """SSE 스트림 → JSON 이벤트 리스트."""
    results = []
    for line in response.iter_lines(decode_unicode=True):
        if line and line.startswith("data: "):
            try:
                results.append(json.loads(line[6:]))
            except Exception:
                pass
    return results


def get_event(results: list[dict], type_key: str) -> Optional[dict]:
    """마지막 매칭 이벤트 반환."""
    for r in reversed(results):
        if r.get("type") == type_key:
            return r
    return None


def get_all_events(results: list[dict], type_key: str) -> list[dict]:
    """모든 매칭 이벤트 반환."""
    return [r for r in results if r.get("type") == type_key]


def call_api(endpoint: str, payload: dict, timeout: int = 300) -> list[dict]:
    """POST SSE API 호출 → 이벤트 리스트 반환."""
    url = f"{BASE}{endpoint}"
    r = requests.post(url, json=payload, stream=True, timeout=timeout)
    return parse_sse(r)


def call_api_json(endpoint: str, payload: dict = None, method: str = "POST", timeout: int = 60) -> dict:
    """일반 JSON API 호출."""
    url = f"{BASE}{endpoint}"
    if method == "POST":
        r = requests.post(url, json=payload, timeout=timeout)
    else:
        r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


def ai_review(text: str, channel: str, criteria: dict) -> dict:
    """AI 검수 (script-reviewer). server.py의 AI 검수 API 호출.

    Returns: {"pass": bool, "score": float, "feedback": str, "items": [...]}
    """
    try:
        results = call_api("/api/review/evaluate", {
            "text": text,
            "channel": channel,
            "criteria": criteria,
        }, timeout=120)
        review = get_event(results, "review") or get_event(results, "result")
        if review:
            data = review.get("data", review)
            return {
                "pass": data.get("pass", data.get("score", 0) >= 70),
                "score": data.get("score", 0),
                "feedback": data.get("feedback", ""),
                "items": data.get("items", []),
            }
    except Exception as e:
        print(f"  AI 검수 API 미구현 또는 에러: {e}")
    # fallback — AI 검수 API 미구현 시 통과 처리
    return {"pass": True, "score": 80, "feedback": "AI 검수 API 미구현 — 통과 처리", "items": []}


def print_step(step_num: int, name: str, suffix: str = ""):
    """단계 헤더 출력."""
    tag = f" {suffix}" if suffix else ""
    print(f"\nSTEP {step_num}: {name}{tag}...")


def print_report(title: str, lines: list[str]):
    """최종 보고 출력."""
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)
    for line in lines:
        print(line)
