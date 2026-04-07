"""사전 검사 — 위험 명령 차단.

hooks PreToolUse에서 호출: python3 tests/pre_check.py "$TOOL_INPUT"
종료코드 0 = 허용, 1 = 차단
"""
import json
import re
import sys


DANGEROUS_PATTERNS = [
    (r'rm\s+-rf\s+/', "rm -rf / 는 실행할 수 없습니다"),
    (r'DROP\s+TABLE', "DROP TABLE은 실행할 수 없습니다"),
    (r'DROP\s+DATABASE', "DROP DATABASE는 실행할 수 없습니다"),
    (r'notion.*databases.*delete', "Notion DB 삭제는 금지입니다"),
    (r'git\s+push.*--force\s+.*main', "main 브랜치 force push 금지"),
]


def check_command(tool_input: str) -> bool:
    """위험 명령 패턴 검사. True = 안전, False = 차단."""
    for pattern, msg in DANGEROUS_PATTERNS:
        if re.search(pattern, tool_input, re.IGNORECASE):
            print(f"BLOCKED: {msg}")
            return False
    return True


if __name__ == "__main__":
    if len(sys.argv) > 1:
        raw = sys.argv[1]
        try:
            data = json.loads(raw)
            cmd = data.get("command", "")
        except (json.JSONDecodeError, TypeError):
            cmd = raw

        if not check_command(cmd):
            sys.exit(1)
    sys.exit(0)
