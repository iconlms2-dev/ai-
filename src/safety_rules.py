"""
SafetyRules — 댓글 자동화 안전 규칙

가이드라인 기준:
- 1일 1계정당 3~5개
- 같은 영상에 계정 무관 1회만 (수동 해제 가능)
- 댓글 간격 10분
"""

import os
import re
import time
import random
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Tuple, Dict, Optional, Set
from urllib.parse import urlparse, parse_qs


class SafetyRules:
    """댓글 자동화 안전 규칙 관리."""

    def __init__(self):
        self._lock = threading.Lock()
        self._comment_history = defaultdict(list)  # {account_label: [(timestamp, video_id, text), ...]}
        self._daily_counts = defaultdict(int)       # {account_label: count}
        self._daily_date = datetime.now().date()
        # 동일 영상 글로벌 차단 (계정 무관)
        self._posted_videos: Set[str] = set()       # {video_id, ...}
        self._allowed_videos: Set[str] = set()      # 수동 해제된 video_id

    @property
    def max_per_day(self) -> int:
        return int(os.getenv("MAX_COMMENTS_PER_DAY", "5"))

    @property
    def same_video_interval_min(self) -> int:
        return int(os.getenv("SAME_VIDEO_INTERVAL_MIN", "30"))

    @property
    def comment_interval_sec(self) -> int:
        return int(os.getenv("COMMENT_INTERVAL_SEC", "600"))

    def _reset_daily_if_needed(self):
        with self._lock:
            today = datetime.now().date()
            if today != self._daily_date:
                self._daily_counts.clear()
                self._daily_date = today

    def _extract_video_id(self, url: str) -> str:
        """YouTube URL에서 video ID를 추출한다."""
        if not url:
            return ""
        try:
            parsed = urlparse(url)
            if "youtu.be" in (parsed.hostname or ""):
                return parsed.path.lstrip("/")
            qs = parse_qs(parsed.query)
            return qs.get("v", [""])[0]
        except Exception:
            match = re.search(r'(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})', url)
            return match.group(1) if match else ""

    def check_all_rules(
        self,
        account_label: str,
        youtube_url: str,
        comment_text: str,
        skip_interval: bool = False,
    ) -> Tuple[bool, str]:
        """모든 안전 규칙을 검사한다.

        Returns:
            (passed: bool, reason: str)
        """
        self._reset_daily_if_needed()
        video_id = self._extract_video_id(youtube_url)

        # 1. 일일 제한
        if self._daily_counts[account_label] >= self.max_per_day:
            return False, f"일일 제한 초과 ({self.max_per_day}회)"

        # 2. 동일 영상 차단 (계정 무관 — 글로벌)
        if video_id and video_id in self._posted_videos and video_id not in self._allowed_videos:
            return False, f"이미 댓글이 작성된 영상입니다 (영상 ID: {video_id})"

        # 3. 댓글 간격 (skip_interval이 아닌 경우)
        if not skip_interval and self._comment_history[account_label]:
            last_ts = self._comment_history[account_label][-1][0]
            elapsed_sec = time.time() - last_ts
            if elapsed_sec < self.comment_interval_sec:
                remaining = self.comment_interval_sec - elapsed_sec
                return False, f"댓글 간격 미달 ({remaining:.0f}초 남음)"

        # 4. 중복 댓글 체크 (같은 영상 + 같은 텍스트)
        if video_id:
            for _, vid, txt in self._comment_history[account_label]:
                if vid == video_id and txt == comment_text:
                    return False, "중복 댓글 (같은 영상에 동일 텍스트)"

        return True, ""

    def record_comment(self, account_label: str, youtube_url: str, comment_text: str):
        """댓글 작성을 기록한다."""
        self._reset_daily_if_needed()
        video_id = self._extract_video_id(youtube_url)
        self._comment_history[account_label].append(
            (time.time(), video_id, comment_text)
        )
        self._daily_counts[account_label] += 1
        # 글로벌 영상 기록
        if video_id:
            self._posted_videos.add(video_id)

    def allow_video(self, youtube_url: str) -> bool:
        """특정 영상의 차단을 수동 해제한다 (재작업 허용)."""
        video_id = self._extract_video_id(youtube_url)
        if video_id:
            self._allowed_videos.add(video_id)
            return True
        return False

    def get_posted_videos(self) -> list:
        """댓글이 작성된 영상 ID 목록."""
        return list(self._posted_videos)

    def get_account_status(self, account_label: str) -> Dict:
        """계정의 오늘 상태를 반환한다."""
        self._reset_daily_if_needed()
        used = self._daily_counts.get(account_label, 0)
        remaining = max(0, self.max_per_day - used)

        last_comment_at = None
        if self._comment_history[account_label]:
            last_ts = self._comment_history[account_label][-1][0]
            last_comment_at = datetime.fromtimestamp(last_ts).isoformat()

        return {
            "account": account_label,
            "used_today": used,
            "remaining": remaining,
            "max_per_day": self.max_per_day,
            "last_comment_at": last_comment_at,
        }

    def get_today_total_success(self) -> int:
        """오늘 전체 계정의 댓글 수를 반환한다."""
        self._reset_daily_if_needed()
        return sum(self._daily_counts.values())

    def get_human_delay(self, action_type: str = "comment") -> Dict:
        """인간형 딜레이 정보를 반환한다."""
        if action_type == "comment":
            base = self.comment_interval_sec
            jitter = random.randint(-30, 60)
            delay = max(60, base + jitter)
            return {
                "delay_sec": delay,
                "description": f"💬 인간형 대기 {delay}초 (기본 {base}초 ± 변동)",
            }
        elif action_type == "reply":
            delay = random.randint(5, 15)
            return {
                "delay_sec": delay,
                "description": f"💬 대댓글 대기 {delay}초",
            }
        else:
            delay = random.randint(3, 10)
            return {
                "delay_sec": delay,
                "description": f"⏳ 대기 {delay}초",
            }
