"""CI 게이트 — 코드 저장할 때마다 자동 실행되는 테스트.

py_compile(문법)만으로는 부족. 실제로 돌아가는지 검증한다.
훅에서 호출: python3 tests/ci_gate.py {파일경로}
종료코드 0 = PASS, 1 = FAIL (에러 메시지 출력)
"""
import importlib
import json
import os
import sys
import py_compile
import re


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAIL = False
ERRORS = []


def fail(msg):
    global FAIL
    FAIL = True
    ERRORS.append(msg)
    print(f"FAIL: {msg}")


def ok(msg):
    pass  # 성공은 조용히


# ─── 1. 문법 검사 ───

def test_syntax(filepath):
    try:
        py_compile.compile(filepath, doraise=True)
        ok(f"문법 OK: {filepath}")
    except py_compile.PyCompileError as e:
        fail(f"문법 에러: {e}")


# ─── 2. import 검사 (모듈이 실제로 로드되는지) ───

def test_import(filepath):
    """파일이 import 가능한지 검사. server.py는 FastAPI라 skip."""
    basename = os.path.basename(filepath)
    # server.py, slack_bot.py는 실행 시 외부 의존성 필요하므로 skip
    skip_files = ["server.py", "slack_bot.py"]
    if basename in skip_files:
        ok(f"import skip: {basename}")
        return

    # pipeline_v2 모듈은 import 테스트
    if "pipeline_v2" in filepath and basename != "__init__.py":
        module_name = filepath.replace(BASE_DIR + "/", "").replace("/", ".").replace(".py", "")
        try:
            # sys.path에 프로젝트 루트 추가
            if BASE_DIR not in sys.path:
                sys.path.insert(0, BASE_DIR)
            importlib.import_module(module_name)
            ok(f"import OK: {module_name}")
        except Exception as e:
            fail(f"import 실패 [{module_name}]: {e}")


# ─── 3. CLAUDE.md 규칙 위반 검사 ───

def test_rules(filepath):
    """CLAUDE.md에 명시된 금지 규칙 위반 검사."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return

    basename = os.path.basename(filepath)

    # bare except 금지
    bare_excepts = re.findall(r'^\s*except\s*:', content, re.MULTILINE)
    if bare_excepts:
        fail(f"bare except 발견 ({len(bare_excepts)}개): {basename} — except Exception as e: 사용 필수")

    # API 키 하드코딩 금지
    api_key_patterns = [
        r'sk-ant-api\w{20,}',
        r'sk-[a-zA-Z0-9]{20,}',
        r'AIzaSy[a-zA-Z0-9_-]{30,}',
    ]
    for pat in api_key_patterns:
        if re.search(pat, content):
            fail(f"API 키 하드코딩 의심: {basename} — .env 사용 필수")
            break

    # lock 없이 공유 상태 접근 (전역 dict 직접 수정)
    # 이건 false positive 많아서 경고만
    if "_state[" in content or "_state =" in content:
        if "lock" not in content.lower() and "_lock" not in content:
            # 경고만, fail 아님
            pass


# ─── 4. rule_validators 자체 테스트 ───

def test_validators():
    """규칙 검수기가 정상 동작하는지 기본 테스트."""
    try:
        if BASE_DIR not in sys.path:
            sys.path.insert(0, BASE_DIR)
        from src.pipeline_v2.rule_validators import (
            validate_shorts, validate_blog, validate_tiktok, validate_threads
        )

        # 빈 텍스트는 무조건 실패해야 함
        assert len(validate_shorts("")) > 0, "validate_shorts('') should fail"
        assert len(validate_blog("", "", "test")) > 0, "validate_blog empty should fail"
        assert len(validate_tiktok("")) > 0, "validate_tiktok('') should fail"
        assert len(validate_threads("")) > 0, "validate_threads('') should fail"

        # 정상 텍스트는 에러 수가 줄어야 함 (완전 통과는 아닐 수 있음)
        good_shorts = "진짜 이거 아셨나요? " + "좋은 내용입니다. " * 20 + "프로필 링크에서 확인하세요."
        shorts_errors = validate_shorts(good_shorts)
        # 적어도 빈 텍스트보다는 에러가 적어야 함
        assert len(shorts_errors) < len(validate_shorts("")), "validator should have fewer errors for good text"

        ok("rule_validators 테스트 PASS")
    except Exception as e:
        fail(f"rule_validators 테스트 실패: {e}")


# ─── 5. state_machine 테스트 ───

def test_state_machine():
    """상태 전이 규칙이 코드로 강제되는지 검증."""
    try:
        if BASE_DIR not in sys.path:
            sys.path.insert(0, BASE_DIR)
        from src.pipeline_v2.state_machine import ProjectState, ALLOWED_TRANSITIONS

        # 허용된 전이 확인
        assert ALLOWED_TRANSITIONS["draft"] == ["under_review"]
        assert "approved" in ALLOWED_TRANSITIONS["under_review"]
        assert "revision" in ALLOWED_TRANSITIONS["under_review"]

        # 건너뛰기 불가 확인
        assert "approved" not in ALLOWED_TRANSITIONS.get("draft", [])
        assert "published" not in ALLOWED_TRANSITIONS.get("approved", [])

        ok("state_machine 테스트 PASS")
    except Exception as e:
        fail(f"state_machine 테스트 실패: {e}")


# ─── MAIN ───

def main():
    global FAIL, ERRORS
    FAIL = False
    ERRORS = []

    if len(sys.argv) > 1:
        filepath = sys.argv[1]
        if filepath.endswith(".py"):
            test_syntax(filepath)
            test_rules(filepath)
            test_import(filepath)
    else:
        # 전체 테스트
        # Python 파일 전체 문법 검사
        for root, dirs, files in os.walk(BASE_DIR):
            # 건너뛸 디렉토리
            skip_dirs = [".git", "__pycache__", "node_modules", ".claude", "관련 파일"]
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for f in files:
                if f.endswith(".py"):
                    fp = os.path.join(root, f)
                    test_syntax(fp)
                    test_rules(fp)

        # 핵심 모듈 테스트
        test_validators()
        test_state_machine()

    if FAIL:
        print(f"\n{'='*40}")
        print(f"CI GATE FAIL: {len(ERRORS)}개 이슈")
        for e in ERRORS:
            print(f"  - {e}")

        # 피드백 루프: 실패를 CLAUDE.md 학습 루프에 자동 기록
        try:
            from feedback_loop import process_ci_failure
            for e in ERRORS:
                process_ci_failure(e)
        except Exception:
            pass  # feedback_loop 자체 에러는 무시

        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
