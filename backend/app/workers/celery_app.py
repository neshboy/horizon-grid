"""Celery application for background work: scheduled crawler runs, PDF/report
export rendering, and any lookup re-processing that outlives an HTTP request
lifecycle. The synchronous request-path lookup (SSE streaming) does NOT go
through Celery -- it runs in-process async so the UI gets live per-provider
updates; Celery is for fire-and-forget or scheduled jobs only.
"""
from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "ioc_intel_platform",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    beat_schedule={
        "crawl-osint-sources-hourly": {
            "task": "app.workers.tasks.run_osint_crawl",
            "schedule": 3600.0,
        },
    },
)
