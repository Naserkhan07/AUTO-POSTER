from __future__ import annotations

from datetime import datetime, time
from pathlib import Path

from shorts_bot.db import JobRepository
from shorts_bot.models import JobStatus, ShortPlan
from shorts_bot.scheduler import ContentScheduler, ScheduledSlot


def test_scheduler_slots_for_monday() -> None:
    scheduler = ContentScheduler()
    # 2026-11-02 is a Monday
    monday = datetime(2026, 11, 2, 5, 0)
    yt_slots = scheduler.get_slots_for_day("YouTube", monday)
    ig_slots = scheduler.get_slots_for_day("Instagram", monday)
    fb_slots = scheduler.get_slots_for_day("Facebook", monday)

    # YouTube: Minimum 10 slots/day (Monday has 11 slots)
    assert len(yt_slots) >= 10
    assert yt_slots[0].target_time.time() == time(6, 45)
    assert yt_slots[0].prep_time.time() == time(5, 45)  # 60m advance prep!

    # Instagram: 10 slots/day
    assert len(ig_slots) == 10
    assert ig_slots[0].target_time.time() == time(7, 20)
    assert ig_slots[0].prep_time.time() == time(6, 20)  # 60m advance prep!

    # Facebook: 10 slots/day
    assert len(fb_slots) == 10
    assert fb_slots[0].target_time.time() == time(8, 5)
    assert fb_slots[0].prep_time.time() == time(7, 5)  # 60m advance prep!


def test_scheduler_prep_due_60m_before() -> None:
    scheduler = ContentScheduler()
    # 2026-11-02 Monday: 6:45 AM slot has prep_time at 5:45 AM
    # At 6:00 AM (inside 60m prep window) -> Prep IS due!
    current = datetime(2026, 11, 2, 6, 0)
    due, slot = scheduler.is_prep_due("YouTube", current)
    assert due is True
    assert slot.target_time.time() == time(6, 45)

    # At 5:30 AM, prep is not due yet
    earlier = datetime(2026, 11, 2, 5, 30)
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


def test_scheduler_strict_slot_publishing(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "jobs.db")
    scheduler = ContentScheduler()

    # Monday 6:45 AM is a slot. Prep time is 5:45 AM.
    # Case 1: At 6:00 AM (Advance prep window, 45m before slot) -> Should NOT upload yet
    prep_time = datetime(2026, 11, 2, 6, 0)
    should_up, reason = scheduler.should_upload_now(repository, "YouTube", prep_time)
    assert should_up is False
    assert "Advance prep window active" in reason

    # Case 2: At 6:45 AM (Slot hits!) -> Should upload!
    slot_time = datetime(2026, 11, 2, 6, 45)
    should_up, reason = scheduler.should_upload_now(repository, "YouTube", slot_time)
    assert should_up is True
    assert "Scheduled slot active" in reason

    # Simulate upload happened at 6:46 AM
    repository.record_platform_upload("YouTube", 1, 1, "yt123", uploaded_at="2026-11-02T06:46:00Z")

    # Case 3: At 6:55 AM -> Slot already fulfilled! Should NOT upload again
    after_time = datetime(2026, 11, 2, 6, 55)
    should_up, reason = scheduler.should_upload_now(repository, "YouTube", after_time)
    assert should_up is False
    assert "already published" in reason or "Spacing interval active" in reason
