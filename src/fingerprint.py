"""
FingerprintManager — 브라우저 핑거프린트 관리

계정별로 고유한 브라우저 핑거프린트를 생성/관리하여
YouTube의 자동화 탐지를 우회한다.
"""

import json
import random
import hashlib
from pathlib import Path
from typing import Dict, Optional


# macOS Chrome User-Agent 풀 (최신 버전 포함)
_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

_VIEWPORTS = [
    {"width": 1280, "height": 800},
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1680, "height": 1050},
    {"width": 1920, "height": 1080},
]

_LANGUAGES = ["ko-KR", "ko", "en-US", "en"]


class FingerprintManager:
    """계정별 고유 브라우저 핑거프린트 관리."""

    def __init__(self, storage_dir: Optional[str] = None):
        if storage_dir:
            self._storage = Path(storage_dir)
        else:
            from src.youtube_bot import _get_data_dir
            self._storage = _get_data_dir() / "fingerprints"
        self._storage.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, Dict] = {}

    def get_fingerprint(self, account_label: str) -> Dict:
        """계정에 대한 고유 핑거프린트를 반환한다. 없으면 생성."""
        if account_label in self._cache:
            return self._cache[account_label]

        fp_file = self._storage / f"{self._safe(account_label)}.json"
        if fp_file.exists():
            try:
                fp = json.loads(fp_file.read_text(encoding="utf-8"))
                self._cache[account_label] = fp
                return fp
            except Exception:
                pass

        # 새 핑거프린트 생성 (계정 레이블 기반 시드로 일관성 유지)
        seed = int(hashlib.md5(account_label.encode()).hexdigest(), 16)
        rng = random.Random(seed)

        fp = {
            "user_agent": rng.choice(_USER_AGENTS),
            "viewport": rng.choice(_VIEWPORTS),
            "locale": "ko-KR",
            "timezone_id": "Asia/Seoul",
            "color_scheme": rng.choice(["light", "light", "light", "dark"]),  # 75% light
            "device_scale_factor": rng.choice([1, 2, 2]),  # Retina 비율 높게
            "has_touch": False,
        }

        fp_file.write_text(json.dumps(fp, ensure_ascii=False, indent=2), encoding="utf-8")
        self._cache[account_label] = fp
        return fp

    def get_context_options(self, account_label: str) -> Dict:
        """Playwright browser context 옵션을 반환한다."""
        fp = self.get_fingerprint(account_label)
        return {
            "user_agent": fp["user_agent"],
            "viewport": fp["viewport"],
            "locale": fp.get("locale", "ko-KR"),
            "timezone_id": fp.get("timezone_id", "Asia/Seoul"),
            "color_scheme": fp.get("color_scheme", "light"),
            "device_scale_factor": fp.get("device_scale_factor", 2),
            "has_touch": fp.get("has_touch", False),
        }

    def reset_fingerprint(self, account_label: str):
        """계정의 핑거프린트를 삭제하고 다음 호출 시 새로 생성."""
        safe = self._safe(account_label)
        fp_file = self._storage / f"{safe}.json"
        if fp_file.exists():
            fp_file.unlink()
        self._cache.pop(account_label, None)

    def _safe(self, label: str) -> str:
        import re
        return re.sub(r'[^\w\-]', '_', label)
