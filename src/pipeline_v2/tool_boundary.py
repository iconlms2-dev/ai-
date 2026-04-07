"""도구 경계 — 에이전트별 접근 권한을 코드로 강제.

에이전트 md에 적혀만 있던 도구 경계를 실제로 강제한다.
파이프라인에서 에이전트 호출 전에 이 모듈로 권한 체크.
"""

# ── 에이전트 권한 정의 ──

AGENT_PERMISSIONS = {
    # 유틸리티 (읽기전용 — 데이터 수집/분석만)
    "data-researcher": {"read": True, "write": False, "execute": False},
    "pattern-extractor": {"read": True, "write": False, "execute": False},
    "keyword-analyzer": {"read": True, "write": False, "execute": False},
    "video-analyst": {"read": True, "write": False, "execute": False},

    # 채널별 strategist (생성전용 — 전략 텍스트만 생성)
    **{f"{ch}-strategist": {"read": True, "write": True, "execute": False}
       for ch in ["shorts", "blog", "cafe-seo", "cafe-viral", "jisikin",
                   "youtube", "tiktok", "community", "powercontent", "threads"]},

    # 채널별 writer (생성전용 — 본문/대본 텍스트만 생성)
    **{f"{ch}-writer": {"read": True, "write": True, "execute": False}
       for ch in ["shorts", "blog", "cafe-seo", "cafe-viral", "jisikin",
                   "youtube", "tiktok", "community", "powercontent", "threads"]},

    # 채널별 reviewer (읽기전용 — 평가/점수만 반환)
    **{f"{ch}-reviewer": {"read": True, "write": False, "execute": False}
       for ch in ["shorts", "blog", "cafe-seo", "cafe-viral", "jisikin",
                   "youtube", "tiktok", "community", "powercontent", "threads"]},

    # 시스템 (코드 수정 가능)
    "code-reviewer": {"read": True, "write": False, "execute": False},
    "debugger": {"read": True, "write": True, "execute": True},

    # 파이프라인 오케스트레이터 (전체 권한)
    **{f"{ch}-pipeline": {"read": True, "write": True, "execute": True}
       for ch in ["shorts", "blog", "cafe-seo", "cafe-viral", "jisikin",
                   "youtube", "tiktok", "community", "powercontent", "threads"]},
}


# ── 금지 작업 목록 ──

FORBIDDEN_ACTIONS = {
    # reviewer는 절대 콘텐츠를 수정/생성하면 안 됨
    "reviewer": ["create_content", "modify_content", "save_to_notion", "publish"],
    # strategist는 본문을 직접 쓰면 안 됨
    "strategist": ["write_script", "write_body", "save_to_notion", "publish"],
    # researcher는 생성/수정/저장 전부 안 됨
    "researcher": ["create_content", "modify_content", "save_to_notion", "publish", "write_file"],
}


class ToolBoundaryError(Exception):
    """도구 경계 위반 시 발생하는 에러."""
    pass


def check_permission(agent_name: str, action: str) -> bool:
    """에이전트가 해당 액션을 수행할 수 있는지 확인.

    Args:
        agent_name: 에이전트 이름 (예: "shorts-writer", "data-researcher")
        action: 수행할 액션 (예: "read", "write", "execute", "create_content", "publish")

    Returns:
        True if allowed

    Raises:
        ToolBoundaryError if forbidden
    """
    perms = AGENT_PERMISSIONS.get(agent_name)
    if perms is None:
        raise ToolBoundaryError(f"알 수 없는 에이전트: {agent_name}")

    # 기본 권한 체크
    if action in ("read", "write", "execute"):
        if not perms.get(action, False):
            raise ToolBoundaryError(
                f"도구 경계 위반: {agent_name}은 '{action}' 권한 없음"
            )
        return True

    # 금지 액션 체크
    for role_suffix, forbidden_list in FORBIDDEN_ACTIONS.items():
        if agent_name.endswith(role_suffix) and action in forbidden_list:
            raise ToolBoundaryError(
                f"도구 경계 위반: {agent_name}은 '{action}' 금지"
            )

    return True


def enforce(agent_name: str, action: str):
    """check_permission의 편의 래퍼. 위반 시 에러 메시지 출력 + raise."""
    try:
        return check_permission(agent_name, action)
    except ToolBoundaryError as e:
        print(f"[BOUNDARY] {e}")
        raise
