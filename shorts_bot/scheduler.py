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

# Daily limits to ensure at least 10 videos/day per platform while spacing them evenly:
DEFAULT_DAILY_LIMITS: dict[str, int] = {
    "YouTube": 10,
    "Instagram": 10,
    "Facebook": 10,
}

# Optimal posting time slots per platform per weekday (0 = Monday, 6 = Sunday)
# Minimum 10-12 distributed slots per day aligned with user's audience peak engagement windows:
# - Morning window (6:30 AM - 10:00 AM)
# - Afternoon window (11:30 AM - 3:00 PM)
# - Evening / Night peak window (6:00 PM - 11:00 PM)
OPTIMAL_SCHEDULES: dict[str, dict[int, list[time]]] = {
    # YouTube Shorts: 11-12 slots/day across Mon-Sun
    "YouTube": {
        0: [  # Mon
            time(6, 30), time(7, 30), time(8, 30),
            time(12, 0), time(13, 0), time(14, 0),
            time(18, 0), time(19, 0), time(20, 0), time(21, 0), time(22, 0)
        ],
        1: [  # Tue
            time(6, 30), time(7, 30), time(8, 30),
            time(12, 0), time(13, 0), time(14, 0),
            time(18, 0), time(19, 0), time(20, 0), time(21, 0), time(22, 0)
        ],
        2: [  # Wed
            time(6, 30), time(7, 30), time(8, 30),
            time(12, 0), time(13, 0), time(14, 0),
            time(18, 0), time(19, 0), time(20, 0), time(21, 0), time(22, 0)
        ],
        3: [  # Thu
            time(6, 30), time(7, 30), time(8, 30),
            time(12, 0), time(13, 0), time(14, 0),
            time(18, 0), time(19, 0), time(20, 0), time(21, 0), time(22, 0)
        ],
        4: [  # Fri
            time(6, 30), time(7, 30), time(8, 30),
            time(12, 0), time(13, 0), time(14, 0),
            time(18, 0), time(19, 0), time(20, 0), time(20, 45), time(21, 30), time(22, 15)
        ],
        5: [  # Sat
            time(7, 30), time(8, 30), time(9, 30),
            time(12, 0), time(13, 0), time(14, 0), time(15, 0),
            time(18, 0), time(19, 0), time(20, 0), time(21, 0), time(22, 0)
        ],
        6: [  # Sun
            time(7, 30), time(8, 30), time(9, 30),
            time(12, 0), time(13, 0), time(14, 0), time(15, 0),
            time(18, 0), time(19, 0), time(20, 0), time(21, 0), time(22, 0)
        ],
    },
    # Instagram Reels: 11-12 slots/day across Mon-Sun
    "Instagram": {
        0: [  # Mon: 7-9 AM, 7-10 PM (+ afternoon bridge)
            time(7, 0), time(7, 45), time(8, 30), time(9, 15),
            time(11, 45), time(12, 45), time(13, 45),
            time(18, 0), time(19, 0), time(19, 45), time(20, 30), time(21, 15)
        ],
        1: [  # Tue: 7-9 AM, 6-9 PM
            time(7, 0), time(7, 45), time(8, 30), time(9, 15),
            time(11, 45), time(12, 45), time(13, 45),
            time(18, 0), time(18, 45), time(19, 30), time(20, 15), time(21, 0)
        ],
        2: [  # Wed: 11 AM-1 PM, 7-10 PM
            time(8, 0), time(9, 0),
            time(11, 0), time(11, 45), time(12, 30), time(13, 15),
            time(17, 30), time(18, 30), time(19, 15), time(20, 0), time(20, 45), time(21, 30)
        ],
        3: [  # Thu: 7-9 AM, 6-9 PM
            time(7, 0), time(7, 45), time(8, 30), time(9, 15),
            time(11, 45), time(12, 45), time(13, 45),
            time(18, 0), time(18, 45), time(19, 30), time(20, 15), time(21, 0)
        ],
        4: [  # Fri: 11 AM-1 PM, 7-10 PM
            time(8, 0), time(9, 0),
            time(11, 0), time(11, 45), time(12, 30), time(13, 15),
            time(17, 30), time(18, 30), time(19, 15), time(20, 0), time(20, 45), time(21, 30)
        ],
        5: [  # Sat: 9-11 AM, 6-9 PM
            time(9, 0), time(9, 45), time(10, 30), time(11, 15),
            time(12, 30), time(13, 30), time(14, 30),
            time(18, 0), time(18, 45), time(19, 30), time(20, 15), time(21, 0)
        ],
        6: [  # Sun: 9 AM-12 PM, 6-9 PM
            time(9, 0), time(9, 45), time(10, 30), time(11, 15),
            time(12, 30), time(13, 30), time(14, 30),
            time(18, 0), time(18, 45), time(19, 30), time(20, 15), time(21, 0)
        ],
    },
    # Facebook Reels: 11-12 slots/day across Mon-Sun
    "Facebook": {
        0: [  # Mon: 8-10 AM, 7-9 PM
            time(8, 0), time(8, 45), time(9, 30), time(10, 15),
            time(12, 0), time(13, 0), time(14, 0),
            time(18, 0), time(18, 45), time(19, 30), time(20, 15), time(21, 0)
        ],
        1: [  # Tue: 8-10 AM, 6-9 PM
            time(8, 0), time(8, 45), time(9, 30), time(10, 15),
            time(12, 0), time(13, 0), time(14, 0),
            time(18, 0), time(18, 45), time(19, 30), time(20, 15), time(21, 0)
        ],
        2: [  # Wed: 11 AM-1 PM, 7-9 PM
            time(8, 30), time(9, 30),
            time(11, 0), time(11, 45), time(12, 30), time(13, 15),
            time(18, 0), time(18, 45), time(19, 30), time(20, 15), time(21, 0), time(21, 45)
        ],
        3: [  # Thu: 8-10 AM, 6-9 PM
            time(8, 0), time(8, 45), time(9, 30), time(10, 15),
            time(12, 0), time(13, 0), time(14, 0),
            time(18, 0), time(18, 45), time(19, 30), time(20, 15), time(21, 0)
        ],
        4: [  # Fri: 11 AM-1 PM, 7-10 PM
            time(8, 30), time(9, 30),
            time(11, 0), time(11, 45), time(12, 30), time(13, 15),
            time(18, 0), time(18, 45), time(19, 30), time(20, 15), time(21, 0), time(21, 45)
        ],
        5: [  # Sat: 9-11 AM, 6-9 PM
            time(9, 0), time(9, 45), time(10, 30), time(11, 15),
            time(12, 0), time(13, 0), time(14, 0),
            time(18, 0), time(18, 45), time(19, 30), time(20, 15), time(21, 0)
        ],
        6: [  # Sun: 9 AM-12 PM, 6-8 PM
            time(9, 0), time(9, 45), time(10, 30), time(11, 15),
            time(12, 0), time(13, 0), time(14, 0),
            time(18, 0), time(18, 45), time(19, 30), time(20, 0), time(20, 45)
        ],
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
        limit = self.daily_limits.get(platform, 10)
        count = self.get_daily_upload_count(repository, platform, date_str)
        return count < limit
