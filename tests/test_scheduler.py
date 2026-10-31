from __future__ import annotations

from datetime import datetime, time
from pathlib import Path

from shorts_bot.db import JobRepository
from shorts_bot.models import JobStatus, ShortPlan
from shorts_bot.scheduler import ContentScheduler, ScheduledSlot


def test_scheduler_slots_for_monday() -> None:
    scheduler = ContentScheduler()
    # 2026-11-02 is a Monday
    monday = datetime(2026, 11, 2, 6, 0)
    yt_slots = scheduler.get_slots_for_day("YouTube", monday)
    ig_slots = scheduler.get_slots_for_day("Instagram", monday)
    fb_slots = scheduler.get_slots_for_day("Facebook", monday)

    assert len(yt_slots) == 3
    # 7:30, 13:00, 20:30
    assert yt_slots[0].target_time.time() == time(7, 30)
    assert yt_slots[0].prep_time.time() == time(7, 0)  # 30m advance prep!

    assert len(ig_slots) == 2
    assert ig_slots[0].target_time.time() == time(8, 0)
    assert ig_slots[0].prep_time.time() == time(7, 30)

    assert len(fb_slots) == 2
    assert fb_slots[0].target_time.time() == time(9, 0)
    assert fb_slots[0].prep_time.time() == time(8, 30)


def test_scheduler_prep_due_30m_before() -> None:
    scheduler = ContentScheduler()
    # 2026-11-02 Monday at 7:10 AM -> 7:30 slot has prep_time at 7:00 AM
    current = datetime(2026, 11, 2, 7, 10)
    due, slot = scheduler.is_prep_due("YouTube", current)
    assert due is True
    assert slot.target_time.time() == time(7, 30)

    # At 6:45 AM, prep is not due yet
    earlier = datetime(2026, 11, 2, 6, 45)
    due_early, _ = scheduler.is_prep_due("YouTube", earlier)
    assert due_early is False


def test_scheduler_daily_limits(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "jobs.db")
    scheduler = ContentScheduler(daily_limits={"YouTube": 2})

    assert scheduler.can_upload_today(repository, "YouTube", "2026-11-02") is True

    # Simulate 2 uploads today
    job = repository.create(0, 0, "https://youtu.be/test1")
    repository.save_plans(job.id, [ShortPlan(0, 15, "T1", "D1", "C1"), ShortPlan(20, 15, "T2", "D2", "C2")])
    repository.update_clip(job.id, 1, youtube_video_id="yt1")
    repository.update_clip(job.id, 2, youtube_video_id="yt2")

    # Manually update created_at to 2026-11-02
    with repository._connect() as conn:
        conn.execute("UPDATE jobs SET created_at = '2026-11-02T10:00:00Z' WHERE id = ?", (job.id,))

    assert scheduler.get_daily_upload_count(repository, "YouTube", "2026-11-02") == 2
    assert scheduler.can_upload_today(repository, "YouTube", "2026-11-02") is False
