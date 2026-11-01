"""
Smart Platform Scheduler for YouTube Shorts, Instagram Reels, and Facebook Reels.

Schedule based on user-defined optimal audience posting windows (IST / Asia/Kolkata):

  YouTube Shorts  — 3 uploads/day  (1 per peak window: morning, afternoon, evening)
  Instagram Reels — 2 uploads/day  (1 per peak window: morning, evening)
  Facebook Reels  — 2 uploads/day  (1 per peak window: morning, evening)

Total: 7 uploads/day, equally divided across peak audience engagement hours.
Each platform has its own dedicated slot with at least 45 minutes of separation.
The automation wakes up 1 hour (60 minutes) before upload time to prepare/render the video,
uploads to that ONE specific platform when the slot hits, and then waits for the next slot.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .db import JobRepository

logger = logging.getLogger(__name__)

# Daily upload limits: 3 for YouTube, 2 for Instagram, 2 for Facebook
DEFAULT_DAILY_LIMITS: dict[str, int] = {
    "YouTube": 3,
    "Instagram": 2,
    "Facebook": 2,
}

# Optimal posting time slots per platform per weekday (0 = Monday … 6 = Sunday)
# All times are strictly in IST (Asia/Kolkata) and fall inside user-specified peak windows.
# Platforms never overlap so each run targets one specific platform.
OPTIMAL_SCHEDULES: dict[str, dict[int, list[time]]] = {
    # ── YouTube Shorts (3/day: Morning, Afternoon, Evening) ─────────────────
    # Mon–Thu : 6–9 AM (07:00) | 12–2 PM (13:00) | 7–10 PM (20:30/20:45)
    # Fri     : 6–9 AM (07:30) | 12–2 PM (13:15) | 8–11 PM (21:45)
    # Sat–Sun : 7–10 AM (08:00) | 12–3 PM (13:30) | 8–11 PM (21:00)
    "YouTube": {
        0: [time(7, 0), time(13, 0), time(20, 30)],    # Mon
        1: [time(7, 0), time(13, 0), time(20, 45)],    # Tue
        2: [time(7, 30), time(13, 15), time(20, 30)],  # Wed
        3: [time(7, 0), time(13, 0), time(20, 45)],    # Thu
        4: [time(7, 30), time(13, 15), time(21, 45)],  # Fri
        5: [time(8, 0), time(13, 30), time(21, 0)],    # Sat
        6: [time(8, 0), time(13, 30), time(21, 0)],    # Sun
    },

    # ── Instagram Reels (2/day: Morning, Evening) ───────────────────────────
    # Mon/Tue/Thu : 7–9 AM (08:00) | 6–9/7–10 PM (19:45/21:15)
    # Wed/Fri     : 11 AM–1 PM (11:30) | 7–10 PM (20:45/21:15)
    # Sat/Sun     : 9–11 AM/12 PM (09:30) | 6–9 PM (19:45)
    "Instagram": {
        0: [time(8, 0), time(21, 15)],    # Mon
        1: [time(8, 0), time(19, 45)],    # Tue
        2: [time(11, 30), time(21, 15)],  # Wed
        3: [time(8, 0), time(19, 45)],    # Thu
        4: [time(11, 30), time(20, 45)],  # Fri
        5: [time(9, 30), time(19, 45)],   # Sat
        6: [time(9, 30), time(19, 45)],   # Sun
    },

    # ── Facebook Reels / Posts (2/day: Morning, Evening) ────────────────────
    # Mon/Tue/Thu : 8–10 AM (09:00) | 6–9/7–9 PM (18:45/19:30)
    # Wed/Fri     : 11 AM–1 PM (12:15) | 7–9/7–10 PM (19:30/19:45)
    # Sat/Sun     : 9–11 AM/12 PM (10:15/10:45) | 6–8/6–9 PM (18:45)
    "Facebook": {
        0: [time(9, 0), time(19, 30)],    # Mon
        1: [time(9, 0), time(18, 45)],    # Tue
        2: [time(12, 15), time(19, 30)],  # Wed
        3: [time(9, 0), time(18, 45)],    # Thu
        4: [time(12, 15), time(19, 45)],  # Fri
        5: [time(10, 15), time(18, 45)],  # Sat
        6: [time(10, 45), time(18, 45)],  # Sun
    },
}


@dataclass(frozen=True, slots=True)
class ScheduledSlot:
    platform: str
    target_time: datetime
    prep_time: datetime
    day_name: str


class ContentScheduler:
    """
    Manages per-platform upload scheduling and 1-hour advance rendering.
    Enforces strict daily caps (YouTube: 3, Instagram: 2, Facebook: 2)
    and separate non-overlapping slots so each video targets one platform,
    then waits for the next platform's slot.
    """

    def __init__(
        self,
        daily_limits: dict[str, int] | None = None,
        advance_prep_minutes: int = 60,
        schedules: dict[str, dict[int, list[time]]] | None = None,
        timezone_str: str = "Asia/Kolkata",
    ) -> None:
        self.daily_limits = dict(daily_limits or DEFAULT_DAILY_LIMITS)
        self.advance_prep_minutes = advance_prep_minutes
        self.schedules = schedules or OPTIMAL_SCHEDULES
        self.timezone_str = timezone_str
        self.tz = self._resolve_timezone(timezone_str)

    @staticmethod
    def _resolve_timezone(tz_name: str) -> timezone:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(tz_name)  # type: ignore[return-value]
        except Exception:
            pass
        known = {
            "Asia/Kolkata": timezone(timedelta(hours=5, minutes=30)),
            "IST": timezone(timedelta(hours=5, minutes=30)),
            "UTC": timezone.utc,
        }
        if tz_name in known:
            return known[tz_name]
        m = re.match(r"^([+-])(\d{1,2}):?(\d{2})?$", tz_name.strip())
        if m:
            sign = 1 if m.group(1) == "+" else -1
            hrs = int(m.group(2))
            mins = int(m.group(3) or 0)
            return timezone(sign * timedelta(hours=hrs, minutes=mins))
        return timezone(timedelta(hours=5, minutes=30))

    def current_dt(self, override: datetime | None = None) -> datetime:
        """Returns the current wall-clock datetime in IST (naive)."""
        if override is not None:
            if override.tzinfo is not None:
                return override.astimezone(self.tz).replace(tzinfo=None)
            return override
        return datetime.now(self.tz).replace(tzinfo=None)

    def get_slots_for_day(self, platform: str, target_date: datetime) -> list[ScheduledSlot]:
        """Returns all scheduled slots for the given date and platform."""
        platform_sched = self.schedules.get(platform, {})
        day_times = platform_sched.get(target_date.weekday(), [])
        day_name = target_date.strftime("%A")
        slots: list[ScheduledSlot] = []
        for t in day_times:
            slot_dt = target_date.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
            prep_dt = slot_dt - timedelta(minutes=self.advance_prep_minutes)
            slots.append(
                ScheduledSlot(
                    platform=platform,
                    target_time=slot_dt,
                    prep_time=prep_dt,
                    day_name=day_name,
                )
            )
        return sorted(slots, key=lambda s: s.target_time)

    def get_next_slot(
        self, platform: str, current_time: datetime | None = None
    ) -> ScheduledSlot:
        """Returns the next upcoming upload slot for the platform."""
        now = self.current_dt(current_time)
        for day_offset in range(8):
            check_date = now + timedelta(days=day_offset)
            for slot in self.get_slots_for_day(platform, check_date):
                if slot.target_time > now:
                    return slot
        fallback_dt = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0)
        return ScheduledSlot(
            platform=platform,
            target_time=fallback_dt,
            prep_time=fallback_dt - timedelta(minutes=self.advance_prep_minutes),
            day_name=fallback_dt.strftime("%A"),
        )

    def is_prep_due(
        self, platform: str, current_time: datetime | None = None
    ) -> tuple[bool, ScheduledSlot]:
        """
        Returns (True, slot) if now is inside the 60-minute advance preparation window.
        Used by the pipeline to wake up 1 hour in advance and render video.
        """
        now = self.current_dt(current_time)
        slot = self.get_next_slot(platform, now)
        due = slot.prep_time <= now < slot.target_time
        return due, slot

    def is_prep_window_active(
        self, platform: str, current_time: datetime | None = None
    ) -> tuple[bool, ScheduledSlot | None]:
        """Alias for is_prep_due returning (bool, slot | None)."""
        due, slot = self.is_prep_due(platform, current_time)
        return due, slot if due else None

    def is_slot_active_for_publish(
        self,
        platform: str,
        current_time: datetime | None = None,
        window_minutes: int = 35,
    ) -> tuple[bool, ScheduledSlot | None]:
        """
        Returns (True, slot) if now matches an active upload slot window
        (opens at slot target_time - 2m and closes window_minutes later).
        """
        now = self.current_dt(current_time)
        slots_today = self.get_slots_for_day(platform, now)
        for slot in slots_today:
            start = slot.target_time - timedelta(minutes=2)
            end = slot.target_time + timedelta(minutes=window_minutes)
            if start <= now <= end:
                return True, slot
        return False, None

    def get_daily_upload_count(
        self,
        repository: "JobRepository",
        platform: str,
        date_str: str | None = None,
    ) -> int:
        """Returns how many videos were published to this platform today in IST."""
        if hasattr(repository, "get_platform_upload_count"):
            return repository.get_platform_upload_count(platform, date_str)
        now_ist = self.current_dt()
        target_date = date_str or now_ist.strftime("%Y-%m-%d")
        col_map = {
            "YouTube": "youtube_video_id",
            "Instagram": "instagram_media_id",
            "Facebook": "facebook_video_id",
        }
        col = col_map.get(platform)
        if not col:
            return 0
        with repository._connect() as conn:
            row = conn.execute(
                f"""
                SELECT COUNT(*) as cnt FROM job_clips c
                JOIN jobs j ON j.id = c.job_id
                WHERE c.{col} IS NOT NULL AND c.{col} != ''
                  AND (j.created_at LIKE ? OR j.updated_at LIKE ?)
                """,  # noqa: S608
                (f"{target_date}%", f"{target_date}%"),
            ).fetchone()
            return int(row["cnt"]) if row else 0

    def can_upload_today(
        self,
        repository: "JobRepository",
        platform: str,
        date_str: str | None = None,
    ) -> bool:
        limit = self.daily_limits.get(platform, 2)
        count = self.get_daily_upload_count(repository, platform, date_str)
        return count < limit

    def should_upload_now(
        self,
        repository: "JobRepository",
        platform: str,
        current_time: datetime | None = None,
    ) -> tuple[bool, str]:
        """
        Determines whether a video can be uploaded right now based on:
        1. Strict daily limit (YouTube: 3, Instagram: 2, Facebook: 2).
        2. Minimum spacing (35 minutes) between uploads.
        3. Strict scheduled slot window:
           - Waking 1 hour in advance: video is prepared and rendered, upload deferred until slot hits.
           - At scheduled slot time: video is published to that ONE specific platform!
           - Outside scheduled slot: waiting for next scheduled slot.
        4. Guard against re-uploading on the same slot.
        """
        now = self.current_dt(current_time)
        limit = self.daily_limits.get(platform, 2)
        date_str = now.strftime("%Y-%m-%d")
        count_today = self.get_daily_upload_count(repository, platform, date_str)

        # 1. Daily cap
        if count_today >= limit:
            return (
                False,
                f"Daily limit of {limit} uploads reached today ({count_today}/{limit}). Resumes tomorrow morning.",
            )

        # 2. Minimum spacing (35 min)
        if hasattr(repository, "get_last_platform_upload_time"):
            last = repository.get_last_platform_upload_time(platform)
            if last:
                if last.tzinfo is None:
                    last = last.replace(tzinfo=UTC)
                last_ist = last.astimezone(self.tz).replace(tzinfo=None)
                elapsed = (now - last_ist).total_seconds() / 60.0
                if elapsed < 35:
                    return (
                        False,
                        f"Spacing interval active ({int(elapsed)}m since last upload; 35m minimum spacing required).",
                    )

        # 3. Check if currently in an active scheduled slot's publish window
        is_active, active_slot = self.is_slot_active_for_publish(platform, now, window_minutes=35)

        if not is_active or active_slot is None:
            # Check if 1-hour advance preparation window is active
            is_prep, prep_slot = self.is_prep_due(platform, now)
            if is_prep:
                target_12h = prep_slot.target_time.strftime("%I:%M %p")
                return (
                    False,
                    f"Advance prep window active ({target_12h}). Video rendered 1 hour in advance; waiting for scheduled slot to publish.",
                )
            next_slot = self.get_next_slot(platform, now)
            next_12h = next_slot.target_time.strftime("%I:%M %p")
            prep_12h = next_slot.prep_time.strftime("%I:%M %p")
            return (
                False,
                f"Outside scheduled upload window. Next scheduled slot at {next_12h} (prep starts at {prep_12h}) [{count_today}/{limit} uploaded today].",
            )

        # 4. Guard: check if an upload already occurred for this slot
        if hasattr(repository, "get_last_platform_upload_time"):
            last = repository.get_last_platform_upload_time(platform)
            if last:
                if last.tzinfo is None:
                    last = last.replace(tzinfo=UTC)
                last_ist = last.astimezone(self.tz).replace(tzinfo=None)
                slot_start = active_slot.target_time - timedelta(minutes=5)
                if last_ist >= slot_start:
                    next_slot = self.get_next_slot(platform, now)
                    next_12h = next_slot.target_time.strftime("%I:%M %p")
                    return (
                        False,
                        f"Slot {active_slot.target_time.strftime('%I:%M %p')} already published. Waiting for next window at {next_12h}.",
                    )

        return (
            True,
            f"Scheduled slot active ({active_slot.target_time.strftime('%I:%M %p')}). Publishing video #{count_today + 1} of {limit} for today.",
        )
