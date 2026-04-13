"""쓰레드 인기글 벤치마킹 — Threads Graph API 활용.

기존 src/api/threads.py의 _threads_api() 래퍼를 재사용.
인기 게시물의 텍스트/구조/반응을 수집하여 전략 수립에 활용.
"""
import json
import logging
import os
from typing import Optional

import requests as req

from src.services.config import BASE_DIR

logger = logging.getLogger(__name__)

THREADS_ACCOUNTS_FILE = os.path.join(BASE_DIR, "threads_accounts.json")


def _get_first_access_token() -> Optional[str]:
    """저장된 Threads 계정 중 첫 번째의 access_token 반환."""
    try:
        if os.path.exists(THREADS_ACCOUNTS_FILE):
            with open(THREADS_ACCOUNTS_FILE, "r") as f:
                data = json.load(f)
            accounts = data.get("accounts", [])
            for acc in accounts:
                token = acc.get("access_token")
                if token:
                    return token
    except Exception as e:
        logger.warning("Threads 계정 파일 읽기 실패: %s", e)
    return None


def _threads_api_call(access_token: str, endpoint: str) -> Optional[dict]:
    """Threads Graph API GET 호출."""
    base = "https://graph.threads.net/v1.0"
    url = f"{base}/{endpoint}"
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        r = req.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            return r.json()
        logger.warning("Threads API %d: %s", r.status_code, r.text[:200])
    except Exception as e:
        logger.warning("Threads API 호출 실패: %s", e)
    return None


def crawl_threads_references(keywords: list[str] = None,
                              max_posts: int = 5) -> list[dict]:
    """Threads 인기 게시물 벤치마킹.

    현재 Threads Graph API는 자신의 게시물만 조회 가능하므로,
    자신의 게시물 중 반응(좋아요/답글)이 좋은 것을 분석하여
    성공 패턴을 추출한다.

    Returns:
        [{"text": ..., "likes": int, "replies": int, "timestamp": str}, ...]
    """
    access_token = _get_first_access_token()
    if not access_token:
        logger.info("Threads access_token 없음 — 벤치마킹 스킵")
        return []

    try:
        # 자신의 최근 게시물 조회 (최대 25개)
        data = _threads_api_call(
            access_token,
            "me/threads?fields=id,text,timestamp,like_count,reply_count&limit=25"
        )
        if not data or "data" not in data:
            return []

        posts = data["data"]

        # 반응(좋아요+답글) 순으로 정렬
        for p in posts:
            p["_engagement"] = p.get("like_count", 0) + p.get("reply_count", 0) * 3

        posts.sort(key=lambda x: x["_engagement"], reverse=True)
        top_posts = posts[:max_posts]

        results = []
        for p in top_posts:
            text = p.get("text", "")
            # 키워드 필터 (있으면)
            if keywords:
                if not any(kw in text for kw in keywords):
                    continue

            results.append({
                "text": text[:500],
                "likes": p.get("like_count", 0),
                "replies": p.get("reply_count", 0),
                "timestamp": p.get("timestamp", ""),
                "char_count": len(text),
                "hashtag_count": text.count("#"),
                "line_count": text.count("\n") + 1,
            })

        return results[:max_posts]

    except Exception as e:
        logger.error("Threads 벤치마킹 실패: %s", e)
        return []
