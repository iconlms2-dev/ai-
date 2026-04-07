"""
CommentTracker — 댓글 성과 추적

작성된 댓글의 좋아요 수, 노출 상태, 삭제 여부 등을 추적한다.
"""

import json
import os
import time
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Callable

from src.youtube_bot import _get_data_dir


class CommentTracker:
    """댓글 성과 추적 관리."""

    def __init__(self):
        self._comments: Dict[str, Dict] = {}  # {comment_id: {...}}
        self._history_file = _get_data_dir() / "tracking_history.json"
        self._lock = threading.Lock()
        self._stop_flag = False
        self._log_callback: Optional[Callable] = None
        self._progress_callback: Optional[Callable] = None
        self._load_history()

    def _load_history(self):
        if self._history_file.exists():
            try:
                data = json.loads(self._history_file.read_text(encoding="utf-8"))
                self._comments = data
            except Exception:
                pass

    def _save_history(self):
        with self._lock:
            tmp = self._history_file.with_suffix('.tmp')
            tmp.write_text(
                json.dumps(self._comments, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(str(tmp), str(self._history_file))

    def set_log_callback(self, callback: Callable):
        self._log_callback = callback

    def set_progress_callback(self, callback: Callable):
        self._progress_callback = callback

    def _log(self, message: str, level: str = "info"):
        if self._log_callback:
            self._log_callback(message, level)

    def _extract_comment_id(self, comment_url: str) -> str:
        """댓글 URL에서 comment ID를 추출한다."""
        import re
        from urllib.parse import urlparse, parse_qs
        try:
            parsed = urlparse(comment_url)
            qs = parse_qs(parsed.query)
            lc = qs.get("lc", [""])[0]
            if lc:
                return lc
        except Exception:
            pass
        # fallback: URL 해시
        import hashlib
        return hashlib.md5(comment_url.encode()).hexdigest()[:12]

    def register_comment(
        self,
        comment_url: str,
        video_url: str = "",
        video_title: str = "",
        comment_text: str = "",
        account_label: str = "",
    ) -> str:
        """댓글을 트래킹 목록에 등록한다."""
        comment_id = self._extract_comment_id(comment_url)
        with self._lock:
            self._comments[comment_id] = {
                "comment_url": comment_url,
                "video_url": video_url,
                "video_title": video_title,
                "comment_text": comment_text[:100] if comment_text else "",
                "account": account_label,
                "registered_at": datetime.now().isoformat(),
                "last_checked_at": None,
                "status": "active",  # active, hidden, deleted
                "likes": 0,
                "check_count": 0,
            }
        self._save_history()
        return comment_id

    def remove_comment(self, comment_id: str) -> bool:
        """트래킹 목록에서 댓글을 제거한다."""
        with self._lock:
            if comment_id in self._comments:
                del self._comments[comment_id]
                self._save_history()
                return True
        return False

    def check_comment(self, comment_id: str) -> Optional[Dict]:
        """단일 댓글의 현재 상태를 확인한다."""
        if comment_id not in self._comments:
            return None

        entry = self._comments[comment_id]
        # 실제 YouTube 페이지 방문하여 상태 확인은 별도 구현 필요
        # 여기서는 메타데이터만 반환
        entry["last_checked_at"] = datetime.now().isoformat()
        entry["check_count"] += 1
        self._save_history()
        return entry

    def check_selected(self, comment_ids: List[str]) -> List[Dict]:
        """선택된 댓글들의 상태를 확인한다."""
        results = []
        for cid in comment_ids:
            result = self.check_comment(cid)
            if result:
                results.append(result)
        return results

    def check_all(self) -> List[Dict]:
        """모든 등록된 댓글의 상태를 확인한다."""
        self._stop_flag = False
        total = len(self._comments)
        results = []

        for i, (cid, _) in enumerate(list(self._comments.items())):
            if self._stop_flag:
                self._log("트래킹 중지됨", "warning")
                break

            if self._progress_callback:
                self._progress_callback(i + 1, total)

            result = self.check_comment(cid)
            if result:
                results.append(result)

        return results

    def stop_tracking(self):
        """진행 중인 트래킹을 중지한다."""
        self._stop_flag = True

    def get_summary(self) -> Dict:
        """트래킹 요약 정보를 반환한다."""
        total = len(self._comments)
        active = sum(1 for c in self._comments.values() if c.get("status") == "active")
        hidden = sum(1 for c in self._comments.values() if c.get("status") == "hidden")
        deleted = sum(1 for c in self._comments.values() if c.get("status") == "deleted")
        total_likes = sum(c.get("likes", 0) for c in self._comments.values())

        return {
            "total": total,
            "active": active,
            "hidden": hidden,
            "deleted": deleted,
            "total_likes": total_likes,
        }
