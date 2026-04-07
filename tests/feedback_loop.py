"""피드백 루프 — 실패 시 학습 루프에 자동 기록.

CI 게이트 실패 → 이 스크립트가 CLAUDE.md 학습 루프 테이블에 자동 추가.
에이전트가 같은 실수를 반복하지 않도록 구조적으로 강제.
"""
import os
import re
import sys
from datetime import datetime


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLAUDE_MD = os.path.join(BASE_DIR, "CLAUDE.md")


def add_learning(mistake: str, rule: str):
    """CLAUDE.md 학습 루프 테이블에 새 항목 추가."""
    today = datetime.now().strftime("%m-%d")

    with open(CLAUDE_MD, "r", encoding="utf-8") as f:
        content = f.read()

    # 학습 루프 테이블 끝 찾기
    # 패턴: | MM-DD | 실수 | 규칙 | 의 마지막 행 뒤에 추가
    table_pattern = r'(\| \d{2}-\d{2} \| .+ \| .+ \|)'
    matches = list(re.finditer(table_pattern, content))

    if not matches:
        print("[feedback_loop] 학습 루프 테이블을 찾을 수 없음")
        return False

    last_match = matches[-1]
    insert_pos = last_match.end()

    new_row = f"\n| {today} | {mistake} | {rule} |"

    # 중복 체크 (같은 실수가 이미 있으면 스킵)
    if mistake in content:
        print(f"[feedback_loop] 이미 기록됨: {mistake}")
        return False

    new_content = content[:insert_pos] + new_row + content[insert_pos:]

    with open(CLAUDE_MD, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"[feedback_loop] 학습 루프 추가: {mistake} → {rule}")
    return True


def process_ci_failure(error_msg: str):
    """CI 게이트 실패 메시지를 파싱해서 학습 루프에 추가."""
    # 에러 메시지에서 패턴 추출
    patterns = {
        r"bare except": ("bare except 사용", "except Exception as e: 강제"),
        r"API 키 하드코딩": ("API 키 하드코딩", ".env에서 로드 강제"),
        r"import 실패": ("모듈 import 깨짐", "수정 후 import 테스트 필수"),
        r"문법 에러": ("문법 에러 커밋", "py_compile 통과 필수"),
        r"rule_validators 테스트 실패": ("검수기 로직 깨짐", "검수기 수정 시 테스트 필수"),
        r"state_machine 테스트 실패": ("상태 전이 규칙 깨짐", "상태 전이 수정 금지"),
    }

    for pattern, (mistake, rule) in patterns.items():
        if re.search(pattern, error_msg, re.IGNORECASE):
            add_learning(mistake, rule)
            return True

    # 알 수 없는 에러도 기록
    if "FAIL" in error_msg:
        short_msg = error_msg[:50].replace("|", "/").replace("\n", " ")
        add_learning(short_msg, "CI 게이트에서 발견 — 원인 분석 필요")
        return True

    return False


if __name__ == "__main__":
    if len(sys.argv) > 1:
        error = " ".join(sys.argv[1:])
        process_ci_failure(error)
    else:
        # 테스트
        print("feedback_loop.py — 수동 테스트")
        print(f"CLAUDE.md 위치: {CLAUDE_MD}")
