"""파일시스템 기반 상태 머신 — transitions 라이브러리 적용.

각 프로젝트 = 폴더.  각 단계 완료 = 해당 파일 존재.
중간에 멈춰도 폴더 스캔 → 미완료 단계부터 재개.

transitions 장점:
- 콜백 (on_enter_*, on_exit_*) → 상태 변경 시 자동 저장/로깅
- 조건부 전이 (conditions) → 리비전 횟수 체크 등
- 상세 에러 메시지 → 잘못된 전이 시도 시 가능한 전이 목록 표시
"""
import json
import logging
import os
from datetime import datetime
from typing import Optional

from transitions import Machine, MachineError

logger = logging.getLogger(__name__)

# ── 프로젝트 루트 ──
PROJECTS_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "projects")
os.makedirs(PROJECTS_ROOT, exist_ok=True)


# ── 상태 & 전이 정의 (CLAUDE.md 강제) ──
STATES = ["draft", "under_review", "revision", "approved", "publish_ready", "uploading", "published"]

TRANSITIONS = [
    {"trigger": "submit_review", "source": "draft", "dest": "under_review"},
    {"trigger": "request_revision", "source": "under_review", "dest": "revision"},
    {"trigger": "approve", "source": "under_review", "dest": "approved"},
    {"trigger": "resubmit", "source": "revision", "dest": "under_review"},
    {"trigger": "mark_ready", "source": "approved", "dest": "publish_ready"},
    {"trigger": "start_upload", "source": "publish_ready", "dest": "uploading"},
    {"trigger": "publish_from_ready", "source": "publish_ready", "dest": "published"},
    {"trigger": "publish_from_upload", "source": "uploading", "dest": "published"},
]

# 하위호환: 기존 코드에서 transition("under_review") 같은 직접 상태명 호출용
_TRANSITION_MAP = {
    ("draft", "under_review"): "submit_review",
    ("under_review", "revision"): "request_revision",
    ("under_review", "approved"): "approve",
    ("revision", "under_review"): "resubmit",
    ("approved", "publish_ready"): "mark_ready",
    ("publish_ready", "uploading"): "start_upload",
    ("publish_ready", "published"): "publish_from_ready",
    ("uploading", "published"): "publish_from_upload",
}

# 하위호환: 기존 ALLOWED_TRANSITIONS dict
ALLOWED_TRANSITIONS = {
    "draft": ["under_review"],
    "under_review": ["revision", "approved"],
    "revision": ["under_review"],
    "approved": ["publish_ready"],
    "publish_ready": ["uploading", "published"],
    "uploading": ["published"],
}


class ProjectState:
    """단일 프로젝트의 상태를 관리. transitions 라이브러리 내장."""

    def __init__(self, channel: str, project_id: str):
        self.channel = channel
        self.project_id = project_id
        self.root = os.path.join(PROJECTS_ROOT, channel, project_id)
        self.status_file = os.path.join(self.root, "status.json")
        os.makedirs(self.root, exist_ok=True)

        # transitions Machine은 _init_machine()에서 초기화
        self._machine = None

    def _init_machine(self, initial_state: str = "draft"):
        """transitions Machine 초기화."""
        self._machine = Machine(
            model=self,
            states=STATES,
            transitions=TRANSITIONS,
            initial=initial_state,
            auto_transitions=False,  # 자동 전이 비활성화 (명시적 전이만)
            send_event=True,  # 콜백에 EventData 전달
        )

    # ── 콜백: 상태 진입 시 자동 저장 + 로깅 ──

    def on_enter_under_review(self, event):
        logger.info("[%s/%s] → under_review", self.channel, self.project_id)
        self._persist_status()

    def on_enter_revision(self, event):
        logger.info("[%s/%s] → revision", self.channel, self.project_id)
        self._persist_status()

    def on_enter_approved(self, event):
        logger.info("[%s/%s] → approved", self.channel, self.project_id)
        self._persist_status()

    def on_enter_publish_ready(self, event):
        logger.info("[%s/%s] → publish_ready", self.channel, self.project_id)
        self._persist_status()

    def on_enter_uploading(self, event):
        logger.info("[%s/%s] → uploading", self.channel, self.project_id)
        self._persist_status()

    def on_enter_published(self, event):
        logger.info("[%s/%s] → published", self.channel, self.project_id)
        self._persist_status()

    def _persist_status(self):
        """현재 상태를 status.json에 기록."""
        if os.path.exists(self.status_file):
            s = self._load_status()
            s["status"] = self.state
            self._save_status(s)

    # ── 생성 / 로드 ──

    @classmethod
    def create(cls, channel: str, project_id: Optional[str] = None, **meta) -> "ProjectState":
        if project_id is None:
            project_id = f"{channel}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        ps = cls(channel, project_id)
        ps._init_machine("draft")
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
        current_status = ps._load_status().get("status", "draft")
        ps._init_machine(current_status)
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
                ps = cls(channel, d)
                current_status = ps._load_status().get("status", "draft")
                ps._init_machine(current_status)
                return ps
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

    # ── 상태 전이 (하위호환: 기존 transition(new_status) 인터페이스 유지) ──

    def transition(self, new_status: str):
        """기존 인터페이스 호환. transition("approved") 형태로 호출."""
        if self._machine is None:
            current = self._load_status().get("status", "draft")
            self._init_machine(current)

        current = self.state
        trigger_name = _TRANSITION_MAP.get((current, new_status))

        if trigger_name is None:
            allowed = ALLOWED_TRANSITIONS.get(current, [])
            raise ValueError(
                f"상태 전이 불가: {current} → {new_status} "
                f"(허용: {allowed})"
            )

        try:
            getattr(self, trigger_name)()
        except MachineError as e:
            allowed = ALLOWED_TRANSITIONS.get(current, [])
            raise ValueError(
                f"상태 전이 불가: {current} → {new_status} "
                f"(허용: {allowed}) — {e}"
            ) from e
        # on_enter_* 콜백이 _persist_status()로 이미 status.json 갱신 완료

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
