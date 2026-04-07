"""state_machine.py 단위 테스트"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.pipeline_v2.state_machine import ProjectState, ALLOWED_TRANSITIONS


class TestAllowedTransitions:
    def test_draft_can_go_to_under_review(self):
        assert "under_review" in ALLOWED_TRANSITIONS["draft"]

    def test_draft_cannot_skip_to_approved(self):
        assert "approved" not in ALLOWED_TRANSITIONS.get("draft", [])

    def test_draft_cannot_skip_to_published(self):
        assert "published" not in ALLOWED_TRANSITIONS.get("draft", [])

    def test_under_review_can_approve(self):
        assert "approved" in ALLOWED_TRANSITIONS["under_review"]

    def test_under_review_can_revision(self):
        assert "revision" in ALLOWED_TRANSITIONS["under_review"]

    def test_revision_goes_back_to_under_review(self):
        assert "under_review" in ALLOWED_TRANSITIONS["revision"]

    def test_revision_cannot_skip_to_approved(self):
        assert "approved" not in ALLOWED_TRANSITIONS.get("revision", [])

    def test_approved_goes_to_publish_ready(self):
        assert "publish_ready" in ALLOWED_TRANSITIONS["approved"]

    def test_no_backward_from_approved(self):
        allowed = ALLOWED_TRANSITIONS.get("approved", [])
        assert "draft" not in allowed
        assert "under_review" not in allowed


class TestProjectState:
    def test_create_initial_state(self):
        state = ProjectState.create("test-channel", "test-state-001")
        assert state.status["status"] == "draft"

    def test_valid_transition(self):
        state = ProjectState.create("test-channel", "test-state-002")
        state.transition("under_review")
        assert state.status["status"] == "under_review"

    def test_invalid_transition_raises(self):
        state = ProjectState.create("test-channel", "test-state-003")
        with pytest.raises(Exception):
            state.transition("approved")  # draft -> approved 불가
