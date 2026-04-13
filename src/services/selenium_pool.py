"""Selenium WebDriver 관리 — SeleniumBase UC 모드"""
from seleniumbase import Driver

from src.services.config import selenium_semaphore


def create_driver():
    """SeleniumBase UC(Undetected Chrome) 모드 드라이버 생성.

    UC 모드: 봇 탐지 우회, 자동 대기, 드라이버 자동 관리.
    리턴 타입은 표준 WebDriver 호환 — 기존 호출부 변경 불필요.
    """
    return Driver(
        uc=True,
        headless=True,
        agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    )
