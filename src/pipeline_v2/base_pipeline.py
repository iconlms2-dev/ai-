"""v2 베이스 파이프라인 — 모든 채널이 상속.

공통 흐름:
  벤치마킹 → 전략 → 기획 → 집필 → 검수(규칙+환각+AI) → [채널별 후반] → Notion 저장

파일시스템 상태 머신으로 중간 재개 지원.
"""
import sys
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from .state_machine import ProjectState
from .workflow import WorkflowConfig, CostTracker
from .common import (
    check_server, call_api, call_api_json, get_event, get_all_events,
    ai_review, print_step, print_report,
    MAX_REVISIONS, MAX_STRATEGY_ROLLBACKS,
)
from .hallucination_detector import detect_hallucinations


class BasePipeline(ABC):
    """채널별 파이프라인의 베이스 클래스."""

    channel: str = ""           # 하위 클래스에서 설정
    steps: list[str] = []       # 하위 클래스에서 설정 (단계 이름 리스트)

    def __init__(self, project: Optional[ProjectState] = None,
                 workflow: Optional[WorkflowConfig] = None):
        self.project = project
        self.workflow = workflow or WorkflowConfig()
        self.cost = CostTracker()
        self._ask_callback = None  # Slack/Dashboard에서 설정

    def set_ask_callback(self, callback):
        """ask 모드에서 사용자 입력을 받을 콜백 설정.

        callback(question: str, options: list[dict]) -> int (선택 인덱스)
        """
        self._ask_callback = callback

    def ask_user(self, question: str, options: list[dict]) -> int:
        """ask 모드에서 사용자에게 질문. auto면 0(첫번째) 반환."""
        if not self.workflow.should_ask("current"):
            return 0
        if self._ask_callback:
            return self._ask_callback(question, options)
        # CLI fallback
        print(f"\n{question}")
        for i, opt in enumerate(options):
            label = opt.get("label", opt.get("topic", str(opt)))
            print(f"  [{i}] {label}")
        while True:
            try:
                choice = int(input("선택 (번호): "))
                if 0 <= choice < len(options):
                    return choice
            except (ValueError, EOFError):
                pass
            print(f"  0~{len(options)-1} 사이 숫자를 입력하세요.")

    # ── 엔트리 포인트 ──

    def run(self, args) -> ProjectState:
        """파이프라인 실행. 새 프로젝트 생성 또는 기존 프로젝트 이어하기."""
        check_server()

        if self.project is None:
            meta = self.build_meta(args)
            self.project = ProjectState.create(self.channel, **meta)
            print(f"프로젝트 생성: {self.project.project_id}")
        else:
            print(f"프로젝트 재개: {self.project.project_id}")

        # workflow.json 저장
        self.workflow.save(self.project.root)

        # 미완료 단계부터 실행
        next_step = self.project.find_next_step(self.steps)
        if next_step is None:
            print("모든 단계 완료됨.")
            return self.project

        started = False
        for step in self.steps:
            if not started:
                if step == next_step:
                    started = True
                else:
                    continue

            step_num = self.steps.index(step) + 1
            print_step(step_num, step)

            try:
                self.execute_step(step, args)
                self.project.update(current_step=step_num)
            except Exception as e:
                print(f"  단계 실패: {e}")
                self.project.update(last_error=str(e))
                raise

        # 비용 요약 저장
        if self.cost.items:
            self.project.save_step_file("cost", "summary.json", self.cost.summary())

        self.finalize(args)
        return self.project

    def resume(self, args=None) -> ProjectState:
        """기존 프로젝트 이어하기."""
        if self.project is None:
            self.project = ProjectState.find_latest(self.channel)
            if self.project is None:
                print(f"이어할 {self.channel} 프로젝트 없음.")
                sys.exit(1)
        return self.run(args)

    # ── 추상 메서드 (하위 클래스 구현) ──

    @abstractmethod
    def build_meta(self, args) -> dict:
        """프로젝트 메타데이터 생성 (args → dict)."""
        ...

    @abstractmethod
    def execute_step(self, step: str, args):
        """개별 단계 실행."""
        ...

    @abstractmethod
    def finalize(self, args):
        """최종 보고 + 저장."""
        ...

    # ── 공통 단계 구현 (하위 클래스에서 호출) ──

    def do_benchmark(self, args) -> dict:
        """벤치마킹 (레퍼런스 수집 + 분석). 채널마다 API가 다를 수 있음."""
        # 기본: 서버 API가 없으면 스킵
        print("  벤치마킹 (서버 API 미구현 시 스킵)")
        return {"skipped": True}

    def do_strategy(self, args, benchmark_data: dict = None) -> dict:
        """전략 수립 (컨셉 + 훅). 채널별 API 호출."""
        print("  전략 수립 (서버 API 미구현 시 스킵)")
        return {"skipped": True}

    def do_brief(self, args, strategy_data: dict = None) -> str:
        """기획서 작성. 전략 기반."""
        print("  기획서 작성 (서버 API 미구현 시 스킵)")
        return ""

    def do_write(self, args, brief: str = "") -> dict:
        """콘텐츠 생성. 기획서 기반 AI 집필."""
        raise NotImplementedError("하위 클래스에서 구현 필요")

    def do_review(self, content: dict, validator_fn, ai_criteria: dict = None,
                  product: dict = None) -> tuple[bool, list[str]]:
        """3단계 검수: 규칙(코드) + 환각탐지 + AI.

        Returns: (passed, errors)
        """
        # 1차: rule-validator
        text = self._extract_review_text(content)
        rule_errors = validator_fn(content) if callable(validator_fn) else []
        if rule_errors:
            return False, rule_errors

        # 1.5차: 환각 탐지 (L1+L2)
        hal_report = detect_hallucinations(text, self.channel, product)
        if hal_report.issues:
            hal_warnings = [
                f"[환각주의] {iss.reason} (-{iss.deduction}점)"
                for iss in hal_report.issues
                if iss.severity in ("critical", "high")
            ]
            if hal_warnings:
                print(f"  환각 의심 {len(hal_report.issues)}건 (점수: {hal_report.score})")
                for w in hal_warnings[:3]:
                    print(f"    {w}")
            # critical/high 환각이 있고 점수 70 미만이면 차단
            if hal_report.score < 70 and hal_warnings:
                return False, hal_warnings

        # 2차: AI review
        if ai_criteria:
            result = ai_review(text, self.channel, ai_criteria)
            if not result["pass"]:
                return False, [f"AI 검수 실패 (점수: {result['score']}): {result['feedback']}"]

        return True, []

    def do_save_notion(self, endpoint: str, payload: dict) -> bool:
        """Notion 저장."""
        try:
            result = call_api_json(endpoint, payload)
            if result.get("success"):
                print("  Notion 저장 완료")
                return True
            else:
                print(f"  Notion 저장 실패: {result.get('error', '알 수 없음')}")
                return False
        except Exception as e:
            print(f"  Notion 저장 오류: {e}")
            return False

    def _extract_review_text(self, content: dict) -> str:
        """검수 대상 텍스트 추출 (하위 클래스에서 오버라이드 가능)."""
        for key in ["body", "text", "script", "answer1", "full_text"]:
            if key in content:
                return content[key]
        return str(content)

    # ── 검수 루프 (공통 패턴) ──

    def revision_loop(self, args, write_fn, validate_fn, ai_criteria: dict = None,
                      max_revisions: int = MAX_REVISIONS) -> tuple[dict, int]:
        """생성 → 검수 루프. 부분 수정 최대 max_revisions회.

        Returns: (최종 content dict, revision 횟수)
        """
        content = {}
        revision = 0

        while revision <= max_revisions:
            suffix = f"(리비전 {revision})" if revision > 0 else ""
            print(f"  생성{' ' + suffix if suffix else ''}...")

            content = write_fn(args)

            # 규칙 검수
            print("  규칙 검수...")
            passed, errors = self.do_review(content, validate_fn, ai_criteria)

            if passed:
                print(f"  PASS")
                break
            else:
                print(f"  FAIL: {errors}")
                revision += 1
                if revision > max_revisions:
                    print(f"  {max_revisions}회 초과. 현재 버전 사용.")
                    break
                self.project.increment_revision()
                print(f"  → 리비전 {revision}/{max_revisions}")

        return content, revision
