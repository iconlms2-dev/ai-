#!/usr/bin/env python3
"""
Minimal structural validator for Claude blueprint documents.

Usage:
  python .claude/skills/blueprint/scripts/validate_blueprint_doc.py ./blueprint-my-task.md
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


REQUIRED_TOP_HEADERS = [
    "## 1. 작업 컨텍스트",
    "## 2. 워크플로우 정의",
    "## 3. 구현 스펙",
]

REQUIRED_CONTEXT_SUBHEADERS = [
    "### 배경 및 목적",
    "### 범위",
    "### 입출력 정의",
    "### 제약조건",
    "### 용어 정의",
]

REQUIRED_STEP_FIELDS = [
    "- **처리 주체**:",
    "- **입력**:",
    "- **처리 내용**:",
    "- **출력**:",
    "- **성공 기준**:",
    "- **검증 방법**:",
    "- **실패 시 처리**:",
]

REQUIRED_IMPL_SUBHEADERS = [
    "### 폴더 구조",
    "### 스킬/스크립트 목록",
    "### 스킬 생성 규칙",
]


STEP_HEADING_RE = re.compile(r"^#### Step \d+:", flags=re.MULTILINE)
FENCED_BLOCK_RE = re.compile(r"```.*?```", flags=re.DOTALL)


def strip_fenced_code_blocks(text: str) -> str:
    return re.sub(FENCED_BLOCK_RE, "", text)


def assert_in_order(text: str, items: list[str], issues: list[str], label: str) -> None:
    cursor = -1
    for item in items:
        idx = text.find(item)
        if idx == -1:
            issues.append(f"Missing {label}: {item}")
            continue
        if idx < cursor:
            issues.append(f"Out-of-order {label}: {item}")
        cursor = idx


def split_step_blocks(text: str) -> list[str]:
    matches = list(STEP_HEADING_RE.finditer(text))
    blocks: list[str] = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        blocks.append(text[start:end])
    return blocks


def validate(path: Path) -> tuple[bool, list[str]]:
    if not path.exists():
        return False, [f"File not found: {path}"]

    text = path.read_text(encoding="utf-8")
    text_no_code = strip_fenced_code_blocks(text)
    issues: list[str] = []

    if not re.fullmatch(r"blueprint-.+\.md", path.name):
        issues.append("Filename should follow blueprint-<task-name>.md")

    assert_in_order(text_no_code, REQUIRED_TOP_HEADERS, issues, "top header")
    assert_in_order(text_no_code, REQUIRED_CONTEXT_SUBHEADERS, issues, "context section")

    assert_in_order(text_no_code, REQUIRED_IMPL_SUBHEADERS, issues, "implementation section")

    step_blocks = split_step_blocks(text_no_code)
    if len(step_blocks) < 2:
        issues.append("Require at least two workflow steps using '#### Step N:' headings")
    else:
        for idx, block in enumerate(step_blocks, start=1):
            for field in REQUIRED_STEP_FIELDS:
                if field not in block:
                    issues.append(f"Missing step field in Step {idx:02d}: {field}")

    if "### 상태 전이" not in text_no_code:
        issues.append("Missing workflow section: ### 상태 전이")

    if "### LLM 판단 vs 코드 처리 구분" not in text_no_code:
        issues.append("Missing workflow section: ### LLM 판단 vs 코드 처리 구분")

    if "skill-creator" not in text_no_code:
        issues.append("Missing required skill-creator usage rule")

    return len(issues) == 0, issues


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python validate_blueprint_doc.py <blueprint-md-path>")
        return 1

    ok, issues = validate(Path(sys.argv[1]))
    if ok:
        print("Blueprint document is structurally valid.")
        return 0

    print("Blueprint document validation failed:")
    for issue in issues:
        print(f"- {issue}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
