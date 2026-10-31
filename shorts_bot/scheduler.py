"""
Smart Platform Scheduler for YouTube Shorts, Instagram Reels, and Facebook Reels.

Implements the user's optimal day-of-week timing charts:
- Prepares and renders videos 30 minutes in advance.
- Enforces strict daily limits per platform so uploads are never blasted all at once.
- Distributes uploads evenly across active audience windows.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .db import JobRepository

logger = logging.getLogger(__name__)

# Daily safety limits to protect accounts from quota exhaustion and spam flags:
# - YouTube Data API: Free quota is 10,000 units/day. Video insert costs 1,600 units.
#   Max mathematical uploads is 6/day. Recommended safe schedule is 3/day.
# - Instagram Graph API: Official limit is 25 posts/24h. Safe optimal is 3/day.
# - Facebook Graph API: Page limit is 25-50 posts/24h. Safe optimal is 3/day.
DEFAULT_DAILY_LIMITS: dict[str, int] = {
    "YouTube": 3,
    "Instagram": 3,
    "Facebook": 3,
}

# Optimal posting time slots per platform per weekday (0 = Monday, 6 = Sunday)
# Based on the user's audience engagement schedules.
# Times are target upload hours/minutes (Local/IST or UTC-configured).
OPTIMAL_SCHEDULES: dict[str, dict[int, list[time]]] = {
    # YouTube Shorts (Image 2):
    # Mon-Thu: 6-9 AM, 12-2 PM, 7-10 PM
    # Fri: 6-9 AM, 12-2 PM, 8-11 PM
    # Sat-Sun: 7-10 AM, 12-3 PM, 8-11 PM
    "YouTube": {
        0: [time(7, 30), time(13, 0), time(20, 30)],  # Mon
        1: [time(7, 30), time(13, 0), time(20, 30)],  # Tue
        2: [time(7, 30), time(13, 0), time(20, 30)],  # Wed
        3: [time(7, 30), time(13, 0), time(20, 30)],  # Thu
        4: [time(7, 30), time(13, 0), time(21, 0)],   # Fri
        5: [time(8, 30), time(13, 30), time(21, 0)],  # Sat
        6: [time(8, 30), time(13, 30), time(21, 0)],  # Sun
    },
    # Instagram Reels (Image 1):
    # Mon: 7-9 AM, 7-10 PM
    # Tue: 7-9 AM, 6-9 PM
    # Wed: 11 AM-1 PM, 7-10 PM
    # Thu: 7-9 AM, 6-9 PM
    # Fri: 11 AM-1 PM, 7-10 PM
    # Sat: 9-11 AM, 6-9 PM
    # Sun: 9 AM-12 PM, 6-9 PM
    "Instagram": {
        0: [time(8, 0), time(20, 0)],   # Mon
        1: [time(8, 0), time(19, 30)],  # Tue
        2: [time(12, 0), time(20, 0)],  # Wed
        3: [time(8, 0), time(19, 30)],  # Thu
        4: [time(12, 0), time(20, 0)],  # Fri
        5: [time(10, 0), time(19, 30)], # Sat
        6: [time(10, 30), time(19, 30)],# Sun
    },
    # Facebook Reels (Image 1):
    # Mon: 8-10 AM, 7-9 PM
    # Tue: 8-10 AM, 6-9 PM
    # Wed: 11 AM-1 PM, 7-9 PM
    # Thu: 8-10 AM, 6-9 PM
    # Fri: 11 AM-1 PM, 7-10 PM
    # Sat: 9-11 AM, 6-9 PM
    # Sun: 9 AM-12 PM, 6-8 PM
    "Facebook": {
        0: [time(9, 0), time(20, 0)],   # Mon
        1: [time(9, 0), time(19, 30)],  # Tue
        2: [time(12, 0), time(20, 0)],  # Wed
        3: [time(9, 0), time(19, 30)],  # Thu
        4: [time(12, 0), time(20, 30)], # Fri
        5: [time(10, 0), time(19, 30)], # Sat
        6: [time(10, 30), time(19, 0)], # Sun
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
    Manages optimal upload scheduling, advance rendering (30m ahead),
    and daily rate limit tracking.
    """

    def __init__(
        self,
        daily_limits: dict[str, int] | None = None,
        advance_prep_minutes: int = 30,
        schedules: dict[str, dict[int, list[time]]] | None = None,
    ) -> None:
        self.daily_limits = dict(daily_limits or DEFAULT_DAILY_LIMITS)
        self.advance_prep_minutes = advance_prep_minutes
        self.schedules = schedules or OPTIMAL_SCHEDULES

    def get_slots_for_day(self, platform: str, target_date: datetime) -> list[ScheduledSlot]:
        """Returns all scheduled slots for the given date and platform."""
        platform_sched = self.schedules.get(platform, {})
        day_times = platform_sched.get(target_date.weekday(), [])
        slots: list[ScheduledSlot] = []

        day_name = target_date.strftime("%A")
        for t in day_times:
            slot_dt = target_date.replace(
                hour=t.hour, minute=t.minute, second=0, microsecond=0
            )
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
        """Finds the next upcoming upload slot for the platform."""
        now = current_time or datetime.now()
        for day_offset in range(8):
            check_date = now + timedelta(days=day_offset)
            slots = self.get_slots_for_day(platform, check_date)
            for slot in slots:
                if slot.target_time > now:
                    return slot

        # Fallback to tomorrow 12:00
        fallback_dt = (now + timedelta(days=1)).replace(hour=12, minute=0, second=0)
        return ScheduledSlot(
            platform=platform,
            target_time=fallback_dt,
            prep_time=fallback_dt - timedelta(minutes=self.advance_prep_minutes),
            day_name=fallback_dt.strftime("%A"),
        )

    def is_prep_due(
        self, platform: str, current_time: datetime | None = None, window_minutes: int = 15
    ) -> tuple[bool, ScheduledSlot]:
        """
        Returns True if we are inside the 30-minute preparation window before the next slot.
        """
        now = current_time or datetime.now()
        slot = self.get_next_slot(platform, now)
        # Prep is due if now >= slot.prep_time and now < slot.target_time
        due = slot.prep_time <= now < slot.target_time
        return due, slot

    def is_upload_window_open(
        self, platform: str, current_time: datetime | None = None, tolerance_minutes: int = 45
    ) -> tuple[bool, ScheduledSlot | None]:
        """
        Returns True if the current time matches an upload slot within tolerance.
        """
        now = current_time or datetime.now()
        slots_today = self.get_slots_for_day(platform, now)
        for slot in slots_today:
            diff = abs((now - slot.target_time).total_seconds()) / 60.0
            if diff <= tolerance_minutes:
                return True, slot
        return False, None

    def get_daily_upload_count(
        self, repository: JobRepository, platform: str, date_str: str | None = None
    ) -> int:
        """Returns how many videos were published to this platform today."""
        target_date = date_str or datetime.now(UTC).strftime("%Y-%m-%d")
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
            if row:
                return int(row["cnt"])
        return 0

    def can_upload_today(
        self, repository: JobRepository, platform: str, date_str: str | None = None
    ) -> bool:
        """Enforces daily rate limits so platforms are never spammed or quota exhausted."""
        limit = self.daily_limits.get(platform, 3)
        count = self.get_daily_upload_count(repository, platform, date_str)
        return count < limit
