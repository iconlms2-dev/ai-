"""APScheduler 통합 서비스.

AsyncIOScheduler 싱글턴 — FastAPI startup에서 1회 init.
모든 스케줄 job(weekly, threads, performance)이 이 인스턴스를 공유한다.
"""
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="Asia/Seoul")

_retry_counts: dict[str, int] = {}
MAX_RETRIES = 2


def _on_job_error(event):
    """job 실패 시 로깅. 재시도 대상 job은 next_run_time 재설정."""
    job_id = event.job_id
    exc = event.exception
    logger.error("[scheduler] job '%s' 실패: %s", job_id, exc)

    count = _retry_counts.get(job_id, 0) + 1
    _retry_counts[job_id] = count

    if count <= MAX_RETRIES:
        logger.info("[scheduler] job '%s' 재시도 %d/%d", job_id, count, MAX_RETRIES)
        try:
            job = scheduler.get_job(job_id)
            if job:
                from datetime import datetime, timedelta
                from zoneinfo import ZoneInfo
                tz = ZoneInfo("Asia/Seoul")
                job.modify(next_run_time=datetime.now(tz) + timedelta(seconds=30))
        except Exception as e:
            logger.error("[scheduler] 재시도 설정 실패: %s", e)
    else:
        logger.warning("[scheduler] job '%s' 재시도 %d회 초과 — 수동 확인 필요", job_id, MAX_RETRIES)


def _on_job_executed(event):
    """job 성공 시 재시도 카운터 리셋."""
    _retry_counts.pop(event.job_id, None)


def init_scheduler():
    """앱 startup에서 1회 호출. scheduler.start() + 리스너 등록."""
    scheduler.add_listener(_on_job_error, EVENT_JOB_ERROR)
    scheduler.add_listener(_on_job_executed, EVENT_JOB_EXECUTED)
    scheduler.start()
    logger.info("[scheduler] APScheduler 시작 (timezone=Asia/Seoul)")


def shutdown_scheduler():
    """앱 shutdown에서 호출."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("[scheduler] APScheduler 종료")
