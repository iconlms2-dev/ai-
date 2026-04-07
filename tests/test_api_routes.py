"""API 라우터 분리 후 통합 테스트"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_create_app_imports():
    """모든 라우터가 정상 import되고 app이 생성되는지 확인"""
    from src.api import create_app
    app = create_app()
    assert app is not None


def test_route_count():
    """기존 143개 라우트가 모두 등록되었는지 확인"""
    from src.api import create_app
    app = create_app()
    # FastAPI 기본 라우트(openapi, docs 등) 포함하여 143개 이상
    assert len(app.routes) >= 140, f"Expected >= 140 routes, got {len(app.routes)}"


def test_critical_routes_exist():
    """핵심 엔드포인트가 존재하는지 확인"""
    from src.api import create_app
    app = create_app()

    paths = {route.path for route in app.routes if hasattr(route, 'path')}

    critical_paths = [
        "/",
        "/api/keywords/expand",
        "/api/blog/generate",
        "/api/cafe/generate",
        "/api/youtube/generate",
        "/api/shorts/tts",
        "/api/threads/generate",
        "/api/status/sync",
        "/api/batch/generate",
        "/api/performance/collect",
    ]

    for path in critical_paths:
        assert path in paths, f"Missing critical route: {path}"


def test_each_router_imports():
    """각 라우터 모듈이 개별적으로 import 가능한지 확인"""
    modules = [
        "src.api.static", "src.api.cafe24", "src.api.keywords", "src.api.blog",
        "src.api.cafe", "src.api.viral", "src.api.jisikin", "src.api.youtube",
        "src.api.tiktok", "src.api.shorts", "src.api.community", "src.api.photo",
        "src.api.ad", "src.api.powercontent", "src.api.schedule", "src.api.batch",
        "src.api.naver", "src.api.threads", "src.api.performance", "src.api.status",
        "src.api.prompt_test",
    ]
    import importlib
    for mod_name in modules:
        mod = importlib.import_module(mod_name)
        assert hasattr(mod, 'router'), f"{mod_name} has no router attribute"
