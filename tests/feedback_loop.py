"""피드백 루프 — 실패 시 학습 로그에 자동 기록.

CI 게이트 실패 → docs/learning-log.md에 추가 + CLAUDE.md 최근 5건 동기화.
에이전트가 같은 실수를 반복하지 않도록 구조적으로 강제.
"""
import os
import re
import sys
from datetime import datetime


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEARNING_LOG = os.path.join(BASE_DIR, "docs", "learning-log.md")
CLAUDE_MD = os.path.join(BASE_DIR, "CLAUDE.md")


def add_learning(mistake: str, rule: str):
    """docs/learning-log.md에 새 항목 추가 + CLAUDE.md 최근 5건 동기화."""
    today = datetime.now().strftime("%m-%d")

    with open(LEARNING_LOG, "r", encoding="utf-8") as f:
        content = f.read()

    # 중복 체크
    if mistake in content:
        print(f"[feedback_loop] 이미 기록됨: {mistake}")
        return False

    # learning-log.md 테이블 끝에 추가
    table_pattern = r'(\| \d{2}-\d{2} \| .+ \| .+ \|)'
    matches = list(re.finditer(table_pattern, content))

    if not matches:
        print("[feedback_loop] 학습 루프 테이블을 찾을 수 없음")
        return False

    last_match = matches[-1]
    insert_pos = last_match.end()
    new_row = f"\n| {today} | {mistake} | {rule} |"
    new_content = content[:insert_pos] + new_row + content[insert_pos:]

    with open(LEARNING_LOG, "w", encoding="utf-8") as f:
        f.write(new_content)

    # CLAUDE.md 최근 5건 동기화
    _sync_claude_md()

    print(f"[feedback_loop] 학습 루프 추가: {mistake} → {rule}")
    return True


def _sync_claude_md():
    """learning-log.md에서 최근 5건을 CLAUDE.md에 동기화."""
    with open(LEARNING_LOG, "r", encoding="utf-8") as f:
        log_content = f.read()

    # 모든 테이블 행 추출
    rows = re.findall(r'\| \d{2}-\d{2} \| .+ \| .+ \|', log_content)
    recent = rows[-5:] if len(rows) > 5 else rows

    with open(CLAUDE_MD, "r", encoding="utf-8") as f:
        claude_content = f.read()

    # CLAUDE.md의 최근 학습 섹션 교체
    header = "## 최근 학습 (전체: docs/learning-log.md)\n| 날짜 | 실수 | 규칙 |\n|------|------|------|\n"
    section_pattern = r'## 최근 학습.*?(?=\n## |\Z)'
    replacement = header + "\n".join(recent) + "\n"

    new_claude = re.sub(section_pattern, replacement, claude_content, flags=re.DOTALL)

    with open(CLAUDE_MD, "w", encoding="utf-8") as f:
        f.write(new_claude)


def process_ci_failure(error_msg: str):
    """CI 게이트 실패 메시지를 파싱해서 학습 루프에 추가."""
    patterns = {
        r"bare except": ("bare except 사용", "except Exception as e: 강제"),
        r"API 키 하드코딩": ("API 키 하드코딩", ".env에서 로드 강제"),
        r"import 실패": ("모듈 import 깨짐", "수정 후 import 테스트 필수"),
        r"문법 에러": ("문법 에러 커밋", "py_compile 통과 필수"),
        r"rule_validators 테스트 실패": ("검수기 로직 깨짐", "검수기 수정 시 테스트 필수"),
        r"state_machine 테스트 실패": ("상태 전이 규칙 깨짐", "상태 전이 수정 금지"),
        r"server\.py.*엔드포인트": ("server.py에 직접 엔드포인트 추가", "src/api/{domain}.py에 추가"),
    }

    for pattern, (mistake, rule) in patterns.items():
        if re.search(pattern, error_msg, re.IGNORECASE):
            add_learning(mistake, rule)
            return True

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
        print("feedback_loop.py — 수동 테스트")
        print(f"learning-log: {LEARNING_LOG}")
