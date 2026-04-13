"""IndexNow API — 발행 즉시 검색엔진에 URL 알림.

Bing, Yandex 등 IndexNow 지원 검색엔진에 새 콘텐츠 URL을 즉시 제출.
네이버 블로그/카페 URL은 제외 (플랫폼 자체 인덱싱 사용).
"""
import logging
import os
from urllib.parse import urlparse

import requests as req

from src.services.config import BASE_DIR

logger = logging.getLogger(__name__)

INDEXNOW_KEY = os.environ.get("INDEXNOW_KEY", "")
INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"

# 자체 도메인만 제출 (네이버/카카오 등 플랫폼 URL 제외)
PLATFORM_HOSTS = {"blog.naver.com", "m.blog.naver.com", "cafe.naver.com",
                  "kin.naver.com", "youtube.com", "www.youtube.com",
                  "tiktok.com", "www.tiktok.com", "threads.net"}


def submit_url(url: str) -> bool:
    """IndexNow에 단일 URL 제출. 성공 시 True."""
    if not INDEXNOW_KEY:
        logger.debug("INDEXNOW_KEY 미설정 — 스킵")
        return False

    host = urlparse(url).hostname or ""
    if host in PLATFORM_HOSTS:
        logger.debug("플랫폼 URL 스킵: %s", host)
        return False

    try:
        r = req.get(INDEXNOW_ENDPOINT, params={
            "url": url,
            "key": INDEXNOW_KEY,
        }, timeout=10)
        if r.status_code in (200, 202):
            logger.info("IndexNow 제출 성공: %s", url)
            return True
        logger.warning("IndexNow 응답 %d: %s", r.status_code, r.text[:200])
        return False
    except Exception as e:
        logger.error("IndexNow 호출 실패: %s", e)
        return False


def submit_urls(urls: list[str]) -> int:
    """복수 URL 일괄 제출 (IndexNow batch API). 성공 건수 반환."""
    if not INDEXNOW_KEY or not urls:
        return 0

    # 플랫폼 URL 필터링
    own_urls = [u for u in urls
                if (urlparse(u).hostname or "") not in PLATFORM_HOSTS]
    if not own_urls:
        return 0

    host = urlparse(own_urls[0]).hostname
    try:
        r = req.post(INDEXNOW_ENDPOINT, json={
            "host": host,
            "key": INDEXNOW_KEY,
            "urlList": own_urls,
        }, timeout=15)
        if r.status_code in (200, 202):
            logger.info("IndexNow 일괄 제출 %d건 성공", len(own_urls))
            return len(own_urls)
        logger.warning("IndexNow batch 응답 %d: %s", r.status_code, r.text[:200])
        return 0
    except Exception as e:
        logger.error("IndexNow batch 실패: %s", e)
        return 0
