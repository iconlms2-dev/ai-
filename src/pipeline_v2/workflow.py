"""워크플로우 설정 — auto/ask 모드 관리.

auto 모드: 모든 결정을 AI가 자동 수행
ask 모드: 전략 선택, 최종 승인 등에서 사용자 입력 대기
"""
import json
import os
from dataclasses import dataclass, field
from typing import Optional


# ask 모드에서 사용자 입력을 요구하는 단계들
ASK_STEPS = {"02_strategy", "09_upload"}


@dataclass
class WorkflowConfig:
    """파이프라인 워크플로우 설정."""
    mode: str = "auto"  # "auto" | "ask"
    voice_id: str = ""
    art_style: str = "realistic"
    channel_name: str = ""
    benchmark_urls: list = field(default_factory=list)
    # 비용 추적
    cost_limit: float = 5.0  # 영상 1개당 상한 ($)

    @classmethod
    def load(cls, project_dir: str) -> "WorkflowConfig":
        """프로젝트 폴더의 workflow.json 로드. 없으면 기본값."""
        path = os.path.join(project_dir, "workflow.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls(**{k: v for k, v in data.items()
                         if k in cls.__dataclass_fields__})
        return cls()

    def save(self, project_dir: str):
        """workflow.json 저장."""
        path = os.path.join(project_dir, "workflow.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.__dict__, f, ensure_ascii=False, indent=2)

    def should_ask(self, step_name: str) -> bool:
        """이 단계에서 사용자 입력이 필요한지."""
        if self.mode == "auto":
            return False
        return step_name in ASK_STEPS


@dataclass
class CostTracker:
    """API 호출 비용 추적."""
    items: list = field(default_factory=list)

    def add(self, service: str, amount: float, detail: str = ""):
        self.items.append({
            "service": service,
            "amount": amount,
            "detail": detail,
        })

    @property
    def total(self) -> float:
        return sum(item["amount"] for item in self.items)

    def summary(self) -> dict:
        by_service = {}
        for item in self.items:
            svc = item["service"]
            by_service[svc] = by_service.get(svc, 0) + item["amount"]
        return {"total": round(self.total, 2), "by_service": by_service}
