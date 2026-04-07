"""tool_boundary.py 단위 테스트"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.pipeline_v2.tool_boundary import (
    check_permission, check_api_access, ToolBoundaryError, AGENT_PERMISSIONS, AGENT_API_ACCESS,
)


class TestCheckPermission:
    def test_researcher_read_allowed(self):
        assert check_permission("data-researcher", "read") is True

    def test_researcher_write_forbidden(self):
        with pytest.raises(ToolBoundaryError):
            check_permission("data-researcher", "write")

    def test_writer_write_allowed(self):
        assert check_permission("blog-writer", "write") is True

    def test_reviewer_write_forbidden(self):
        with pytest.raises(ToolBoundaryError):
            check_permission("blog-reviewer", "write")

    def test_pipeline_execute_allowed(self):
        assert check_permission("shorts-pipeline", "execute") is True

    def test_unknown_agent_raises(self):
        with pytest.raises(ToolBoundaryError, match="알 수 없는 에이전트"):
            check_permission("nonexistent-agent", "read")

    def test_reviewer_cannot_create_content(self):
        with pytest.raises(ToolBoundaryError):
            check_permission("blog-reviewer", "create_content")

    def test_strategist_cannot_publish(self):
        with pytest.raises(ToolBoundaryError):
            check_permission("shorts-strategist", "publish")

    def test_master_orchestrator_read_only(self):
        assert check_permission("master-orchestrator", "read") is True
        with pytest.raises(ToolBoundaryError):
            check_permission("master-orchestrator", "write")

    def test_content_lead_execute(self):
        assert check_permission("content-lead", "execute") is True


class TestCheckApiAccess:
    def test_analytics_lead_keywords_allowed(self):
        assert check_api_access("analytics-lead", "/api/keywords/expand") is True

    def test_analytics_lead_generate_forbidden(self):
        with pytest.raises(ToolBoundaryError):
            check_api_access("analytics-lead", "/api/blog/generate")

    def test_master_orchestrator_access_all(self):
        assert check_api_access("master-orchestrator", "/api/blog/generate") is True

    def test_unknown_agent_allowed(self):
        # 명시적 제한 없으면 허용
        assert check_api_access("unknown-agent", "/api/anything") is True


class TestAllChannelsCovered:
    CHANNELS = ["shorts", "blog", "cafe-seo", "cafe-viral", "jisikin",
                "youtube", "tiktok", "community", "powercontent", "threads"]

    def test_all_pipelines_registered(self):
        for ch in self.CHANNELS:
            assert f"{ch}-pipeline" in AGENT_PERMISSIONS

    def test_all_writers_registered(self):
        for ch in self.CHANNELS:
            assert f"{ch}-writer" in AGENT_PERMISSIONS

    def test_all_reviewers_registered(self):
        for ch in self.CHANNELS:
            assert f"{ch}-reviewer" in AGENT_PERMISSIONS

    def test_hierarchy_agents_registered(self):
        for agent in ["master-orchestrator", "content-lead", "analytics-lead", "ops-lead"]:
            assert agent in AGENT_PERMISSIONS
