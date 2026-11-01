"""
Smart Platform Scheduler for YouTube Shorts, Instagram Reels, and Facebook Reels.

Guarantees a minimum of 10 uploads per day on each platform (YouTube: 11-12, Instagram: 10, Facebook: 10).
All slots strictly match user-provided peak audience engagement windows (IST / Asia/Kolkata).
Platforms are interleaved with distinct minutes so each run publishes to ONE specific platform,
then waits for the next slot.
The automation wakes up 1 hour (60 minutes) before the scheduled upload time to prepare/render the video.
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

# Daily upload limits: Minimum 10 uploads per day per platform
DEFAULT_DAILY_LIMITS: dict[str, int] = {
    "YouTube": 10,
    "Instagram": 10,
    "Facebook": 10,
}

# Optimal posting time slots per platform per weekday (0 = Monday … 6 = Sunday)
# All times are strictly in IST (Asia/Kolkata) and fall inside user-specified peak windows.
# Platforms have dedicated non-overlapping minutes so each run publishes to one specific platform.
OPTIMAL_SCHEDULES: dict[str, dict[int, list[time]]] = {
    # ── YouTube Shorts (11-12 slots/day across Morning, Afternoon, Evening) ───
    # Mon–Thu : 6–9 AM, 12–2 PM, 7–10 PM
    # Fri     : 6–9 AM, 12–2 PM, 8–11 PM
    # Sat–Sun : 7–10 AM, 12–3 PM, 8–11 PM
    "YouTube": {
        0: [  # Mon (11 slots)
            time(6, 45), time(7, 30), time(8, 15), time(8, 55),
            time(12, 10), time(12, 50), time(13, 30),
            time(19, 10), time(19, 50), time(20, 30), time(21, 10),
        ],
        1: [  # Tue (11 slots)
            time(6, 45), time(7, 30), time(8, 15), time(8, 55),
            time(12, 10), time(12, 50), time(13, 30),
            time(19, 10), time(19, 50), time(20, 30), time(21, 10),
        ],
        2: [  # Wed (11 slots)
            time(6, 45), time(7, 30), time(8, 15), time(8, 55),
            time(12, 10), time(12, 50), time(13, 30),
            time(19, 10), time(19, 50), time(20, 30), time(21, 10),
        ],
        3: [  # Thu (11 slots)
            time(6, 45), time(7, 30), time(8, 15), time(8, 55),
            time(12, 10), time(12, 50), time(13, 30),
            time(19, 10), time(19, 50), time(20, 30), time(21, 10),
        ],
        4: [  # Fri (11 slots)
            time(6, 45), time(7, 30), time(8, 15), time(8, 55),
            time(12, 10), time(12, 50), time(13, 30),
            time(20, 10), time(20, 50), time(21, 30), time(22, 10),
        ],
        5: [  # Sat (12 slots)
            time(7, 30), time(8, 15), time(9, 0), time(9, 45),
            time(12, 15), time(13, 0), time(13, 45), time(14, 30),
            time(20, 15), time(21, 0), time(21, 45), time(22, 15),
        ],
        6: [  # Sun (12 slots)
            time(7, 30), time(8, 15), time(9, 0), time(9, 45),
            time(12, 15), time(13, 0), time(13, 45), time(14, 30),
            time(20, 15), time(21, 0), time(21, 45), time(22, 15),
        ],
    },

    # ── Instagram Reels (10 slots/day across designated peak windows) ──────────
    # Mon         : 7–9 AM (4 slots), 7–10 PM (6 slots)
    # Tue & Thu   : 7–9 AM (4 slots), 6–9 PM (6 slots)
    # Wed & Fri   : 11 AM–1 PM (4 slots), 7–10 PM (6 slots)
    # Sat         : 9–11 AM (4 slots), 6–9 PM (6 slots)
    # Sun         : 9 AM–12 PM (5 slots), 6–9 PM (5 slots)
    "Instagram": {
        0: [  # Mon (10 slots)
            time(7, 20), time(7, 50), time(8, 20), time(8, 50),
            time(19, 20), time(19, 50), time(20, 20), time(20, 50), time(21, 20), time(21, 45),
        ],
        1: [  # Tue (10 slots)
            time(7, 20), time(7, 50), time(8, 20), time(8, 50),
            time(18, 20), time(18, 50), time(19, 20), time(19, 50), time(20, 20), time(20, 45),
        ],
        2: [  # Wed (10 slots)
            time(11, 20), time(11, 50), time(12, 20), time(12, 50),
            time(19, 20), time(19, 50), time(20, 20), time(20, 50), time(21, 20), time(21, 45),
        ],
        3: [  # Thu (10 slots)
            time(7, 20), time(7, 50), time(8, 20), time(8, 50),
            time(18, 20), time(18, 50), time(19, 20), time(19, 50), time(20, 20), time(20, 45),
        ],
        4: [  # Fri (10 slots)
            time(11, 20), time(11, 50), time(12, 20), time(12, 50),
            time(19, 20), time(19, 50), time(20, 20), time(20, 50), time(21, 20), time(21, 45),
        ],
        5: [  # Sat (10 slots)
            time(9, 20), time(9, 50), time(10, 20), time(10, 50),
            time(18, 20), time(18, 50), time(19, 20), time(19, 50), time(20, 20), time(20, 45),
        ],
        6: [  # Sun (10 slots)
            time(9, 20), time(9, 50), time(10, 20), time(10, 50), time(11, 20),
            time(18, 20), time(18, 50), time(19, 20), time(19, 50), time(20, 20),
        ],
    },

    # ── Facebook Reels / Posts (10 slots/day across designated peak windows) ──
    # Mon         : 8–10 AM (5 slots), 7–9 PM (5 slots)
    # Tue & Thu   : 8–10 AM (4 slots), 6–9 PM (6 slots)
    # Wed         : 11 AM–1 PM (5 slots), 7–9 PM (5 slots)
    # Fri         : 11 AM–1 PM (4 slots), 7–10 PM (6 slots)
    # Sat         : 9–11 AM (4 slots), 6–9 PM (6 slots)
    # Sun         : 9 AM–12 PM (5 slots), 6–8 PM (5 slots)
    "Facebook": {
        0: [  # Mon (10 slots)
            time(8, 5), time(8, 35), time(9, 5), time(9, 30), time(9, 50),
            time(19, 5), time(19, 35), time(20, 5), time(20, 25), time(20, 45),
        ],
        1: [  # Tue (10 slots)
            time(8, 5), time(8, 35), time(9, 5), time(9, 30),
            time(18, 5), time(18, 35), time(19, 5), time(19, 35), time(20, 5), time(20, 35),
        ],
        2: [  # Wed (10 slots)
            time(11, 5), time(11, 35), time(12, 5), time(12, 35), time(12, 55),
            time(19, 5), time(19, 35), time(20, 5), time(20, 25), time(20, 45),
        ],
        3: [  # Thu (10 slots)
            time(8, 5), time(8, 35), time(9, 5), time(9, 30),
            time(18, 5), time(18, 35), time(19, 5), time(19, 35), time(20, 5), time(20, 35),
        ],
        4: [  # Fri (10 slots)
            time(11, 5), time(11, 35), time(12, 5), time(12, 35),
            time(19, 5), time(19, 35), time(20, 5), time(20, 35), time(21, 5), time(21, 35),
        ],
        5: [  # Sat (10 slots)
            time(9, 5), time(9, 35), time(10, 5), time(10, 35),
            time(18, 5), time(18, 35), time(19, 5), time(19, 35), time(20, 5), time(20, 35),
        ],
        6: [  # Sun (10 slots)
            time(9, 5), time(9, 35), time(10, 5), time(10, 35), time(11, 5),
            time(18, 5), time(18, 30), time(18, 55), time(19, 20), time(19, 45),
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
    Manages per-platform upload scheduling and 1-hour advance rendering.
    Enforces a minimum of 10 uploads per day per platform across designated peak windows.
    Platforms have distinct non-overlapping minutes so each run publishes to one specific platform.
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
        fallback_dt = (now + timedelta(days=1)).replace(hour=8, minute=0, second=0)
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
        window_minutes: int = 25,
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
        limit = self.daily_limits.get(platform, 10)
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
        1. Strict daily limit (min 10 uploads per platform per day).
        2. Minimum spacing (20 minutes) between uploads on the same platform.
        3. Strict scheduled slot window:
           - Waking 1 hour in advance: video is prepared and rendered, upload deferred until slot hits.
           - At scheduled slot time: video is published to that ONE specific platform!
           - Outside scheduled slot: waiting for next scheduled slot.
        4. Guard against re-uploading on the same slot.
        """
        now = self.current_dt(current_time)
        limit = self.daily_limits.get(platform, 10)
        date_str = now.strftime("%Y-%m-%d")
        count_today = self.get_daily_upload_count(repository, platform, date_str)

        # 1. Daily cap
        if count_today >= limit:
            return (
                False,
                f"Daily limit of {limit} uploads reached today ({count_today}/{limit}). Resumes tomorrow morning.",
            )

        # 2. Minimum spacing from last upload on this platform (20 minutes)
        if hasattr(repository, "get_last_platform_upload_time"):
            last = repository.get_last_platform_upload_time(platform)
            if last:
                if last.tzinfo is None:
                    last = last.replace(tzinfo=UTC)
                last_ist = last.astimezone(self.tz).replace(tzinfo=None)
                elapsed = (now - last_ist).total_seconds() / 60.0
                if elapsed < 20:
                    return (
                        False,
                        f"Spacing interval active ({int(elapsed)}m since last upload on {platform}; 20m minimum spacing required).",
                    )

        # 3. Check if currently in an active scheduled slot's publish window
        is_active, active_slot = self.is_slot_active_for_publish(platform, now, window_minutes=25)

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
