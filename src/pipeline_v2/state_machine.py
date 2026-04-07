"""파일시스템 기반 상태 머신.

각 프로젝트 = 폴더.  각 단계 완료 = 해당 파일 존재.
중간에 멈춰도 폴더 스캔 → 미완료 단계부터 재개.
"""
import json
import os
import shutil
from datetime import datetime
from typing import Optional


# ── 프로젝트 루트 ──
PROJECTS_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "projects")
os.makedirs(PROJECTS_ROOT, exist_ok=True)


# ── 상태 전이표 (CLAUDE.md 강제) ──
ALLOWED_TRANSITIONS = {
    "draft": ["under_review"],
    "under_review": ["revision", "approved"],
    "revision": ["under_review"],
    "approved": ["publish_ready"],
    "publish_ready": ["published"],
}


class ProjectState:
    """단일 프로젝트의 상태를 관리."""

    def __init__(self, channel: str, project_id: str):
        self.channel = channel
        self.project_id = project_id
        self.root = os.path.join(PROJECTS_ROOT, channel, project_id)
        self.status_file = os.path.join(self.root, "status.json")
        os.makedirs(self.root, exist_ok=True)

    # ── 생성 / 로드 ──

    @classmethod
    def create(cls, channel: str, project_id: Optional[str] = None, **meta) -> "ProjectState":
        if project_id is None:
            project_id = f"{channel}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        ps = cls(channel, project_id)
        status = {
            "project_id": project_id,
            "channel": channel,
            "status": "draft",
            "current_step": 0,
            "revision_count": 0,
            "strategy_rollback_count": 0,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            **meta,
        }
        ps._save_status(status)
        return ps

    @classmethod
    def load(cls, channel: str, project_id: str) -> "ProjectState":
        ps = cls(channel, project_id)
        if not os.path.exists(ps.status_file):
            raise FileNotFoundError(f"프로젝트 없음: {ps.root}")
        return ps

    @classmethod
    def find_latest(cls, channel: str) -> Optional["ProjectState"]:
        channel_dir = os.path.join(PROJECTS_ROOT, channel)
        if not os.path.isdir(channel_dir):
            return None
        dirs = sorted(os.listdir(channel_dir), reverse=True)
        for d in dirs:
            sf = os.path.join(channel_dir, d, "status.json")
            if os.path.exists(sf):
                return cls(channel, d)
        return None

    # ── 상태 읽기 / 쓰기 ──

    def _load_status(self) -> dict:
        with open(self.status_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_status(self, data: dict):
        data["updated_at"] = datetime.now().isoformat()
        with open(self.status_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @property
    def status(self) -> dict:
        return self._load_status()

    def get(self, key: str, default=None):
        return self._load_status().get(key, default)

    def update(self, **kwargs):
        s = self._load_status()
        s.update(kwargs)
        self._save_status(s)

    # ── 상태 전이 (CLAUDE.md 강제) ──

    def transition(self, new_status: str):
        s = self._load_status()
        current = s["status"]
        allowed = ALLOWED_TRANSITIONS.get(current, [])
        if new_status not in allowed:
            raise ValueError(
                f"상태 전이 불가: {current} → {new_status} "
                f"(허용: {allowed})"
            )
        s["status"] = new_status
        self._save_status(s)

    # ── 단계 파일 관리 ──

    def step_dir(self, step_name: str) -> str:
        d = os.path.join(self.root, step_name)
        os.makedirs(d, exist_ok=True)
        return d

    def step_done(self, step_name: str) -> bool:
        d = os.path.join(self.root, step_name)
        if not os.path.isdir(d):
            return False
        return len(os.listdir(d)) > 0

    def save_step_file(self, step_name: str, filename: str, data, as_json: bool = True):
        d = self.step_dir(step_name)
        path = os.path.join(d, filename)
        with open(path, "w", encoding="utf-8") as f:
            if as_json:
                json.dump(data, f, ensure_ascii=False, indent=2)
            else:
                f.write(data)
        return path

    def load_step_file(self, step_name: str, filename: str, as_json: bool = True):
        path = os.path.join(self.root, step_name, filename)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) if as_json else f.read()

    def save_step_binary(self, step_name: str, filename: str, data: bytes):
        d = self.step_dir(step_name)
        path = os.path.join(d, filename)
        with open(path, "wb") as f:
            f.write(data)
        return path

    # ── 리비전 관리 ──

    def increment_revision(self) -> int:
        s = self._load_status()
        s["revision_count"] = s.get("revision_count", 0) + 1
        self._save_status(s)
        return s["revision_count"]

    def increment_strategy_rollback(self) -> int:
        s = self._load_status()
        s["strategy_rollback_count"] = s.get("strategy_rollback_count", 0) + 1
        self._save_status(s)
        return s["strategy_rollback_count"]

    # ── 미완료 단계 감지 (이어하기) ──

    def find_next_step(self, step_names: list[str]) -> Optional[str]:
        for name in step_names:
            if not self.step_done(name):
                return name
        return None

    # ── 편의 ──

    def __repr__(self):
        return f"<ProjectState {self.channel}/{self.project_id}>"
