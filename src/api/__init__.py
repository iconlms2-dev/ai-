"""FastAPI 앱 생성 및 라우터 등록"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def create_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from src.api import (
        cafe24, keywords, blog, cafe, viral, jisikin, youtube,
        tiktok, shorts, community, photo, ad, powercontent,
        schedule, batch, naver, threads, performance, status,
        prompt_test, static, inbox,
    )

    app.include_router(static.router)
    app.include_router(cafe24.router, prefix="/api/cafe24")
    app.include_router(keywords.router, prefix="/api/keywords")
    app.include_router(blog.router, prefix="/api/blog")
    app.include_router(cafe.router, prefix="/api/cafe")
    app.include_router(viral.router, prefix="/api/viral")
    app.include_router(jisikin.router, prefix="/api/jisikin")
    app.include_router(youtube.router, prefix="/api/youtube")
    app.include_router(tiktok.router, prefix="/api/tiktok")
    app.include_router(shorts.router, prefix="/api/shorts")
    app.include_router(community.router, prefix="/api/community")
    app.include_router(photo.router, prefix="/api/photo")
    app.include_router(ad.router, prefix="/api/ad")
    app.include_router(powercontent.router, prefix="/api/powercontent")
    app.include_router(schedule.router, prefix="/api/schedule")
    app.include_router(schedule.report_router, prefix="/api/report")
    app.include_router(schedule.scheduler_router, prefix="/api/scheduler")
    app.include_router(batch.router, prefix="/api/batch")
    app.include_router(naver.router, prefix="/api/naver")
    app.include_router(threads.router, prefix="/api/threads")
    app.include_router(performance.router, prefix="/api/performance")
    app.include_router(status.router, prefix="/api/status")
    app.include_router(prompt_test.router, prefix="/api/prompt-test")
    app.include_router(inbox.router, prefix="/api/inbox")

    @app.on_event("startup")
    async def _start_weekly_scheduler():
        await schedule.start_weekly_scheduler()

    @app.on_event("startup")
    async def _start_threads_scheduler():
        await threads.start_threads_scheduler()

    @app.on_event("startup")
    async def _restore_perf_schedule():
        await performance.restore_performance_schedule()

    return app
