"""rule_validators.py 단위 테스트"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.pipeline_v2.rule_validators import (
    validate_shorts, validate_blog, validate_tiktok, validate_threads,
)


class TestValidateShorts:
    def test_empty_text_fails(self):
        errors = validate_shorts("")
        assert len(errors) > 0

    def test_good_text_fewer_errors(self):
        good = "진짜 이거 아셨나요? " + "좋은 내용입니다. " * 20 + "프로필 링크에서 확인하세요."
        empty_errors = validate_shorts("")
        good_errors = validate_shorts(good)
        assert len(good_errors) < len(empty_errors)


class TestValidateBlog:
    def test_empty_fails(self):
        errors = validate_blog("", "", "test")
        assert len(errors) > 0


class TestValidateTiktok:
    def test_empty_fails(self):
        errors = validate_tiktok("")
        assert len(errors) > 0


class TestValidateThreads:
    def test_empty_fails(self):
        errors = validate_threads("")
        assert len(errors) > 0
