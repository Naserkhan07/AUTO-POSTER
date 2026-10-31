"""Automated YouTube creator channel watcher (Channel Auto-Pilot).

Periodically polls RSS feeds for a list of configured YouTube channels,
identifies new uploads, and queues their watch URLs into links.txt so
the existing pipeline automatically downloads and processes them.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .db import JobRepository

logger = logging.getLogger(__name__)

_ATOM_NS = "http://www.w3.org/2005/Atom"
_YT_NS = "http://www.youtube.com/xml/schemas/2015"
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


@dataclass(frozen=True, slots=True)
class AutopilotChannel:
    name: str
    channel_id: str
    handle: str = ""


@dataclass(frozen=True, slots=True)
class AutopilotVideo:
    video_id: str
    title: str
    published_at: str
    link: str
    is_short: bool
    channel_name: str
    channel_id: str

    @property
    def watch_url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


def resolve_channel_id(identifier: str, timeout: float = 10.0) -> str | None:
    """Resolve a YouTube handle (e.g. '@MrBeast') or URL to its canonical UC... channel ID."""
    candidate = identifier.strip()
    if candidate.startswith("UC") and len(candidate) == 24:
        return candidate

    if not candidate.startswith("http"):
        if not candidate.startswith("@"):
            candidate = f"@{candidate}"
        url = f"https://www.youtube.com/{candidate}"
    else:
        url = candidate

    req = urllib.request.Request(url, headers=_DEFAULT_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as exc:
        logger.debug("Failed resolving channel handle %s: %s", identifier, exc)
        return None

    # Check og:url and canonical link
    match = re.search(
        r'<meta property="og:url" content="https?://www\.youtube\.com/channel/(UC[a-zA-Z0-9_-]{22})"',
        html,
    )
    if not match:
        match = re.search(
            r'<link rel="canonical" href="https?://www\.youtube\.com/channel/(UC[a-zA-Z0-9_-]{22})"',
            html,
        )
    if not match:
        match = re.search(r'"externalId":"(UC[a-zA-Z0-9_-]{22})"', html)
    if not match:
        match = re.search(r'"channelId":"(UC[a-zA-Z0-9_-]{22})"', html)

    return match.group(1) if match else None


class AutopilotService:
    def __init__(
        self,
        channels: list[AutopilotChannel],
        repository: JobRepository,
        poll_interval_minutes: int = 15,
        ignore_shorts: bool = True,
        queue_latest_on_start: bool = False,
        enabled: bool = True,
    ) -> None:
        self.channels = channels
        self.repository = repository
        self.poll_interval_minutes = poll_interval_minutes
        self.ignore_shorts = ignore_shorts
        self.queue_latest_on_start = queue_latest_on_start
        self.enabled = enabled

    @property
    def poll_interval_seconds(self) -> int:
        return max(60, self.poll_interval_minutes * 60)

    @classmethod
    def from_settings(cls, settings: Settings, repository: JobRepository) -> AutopilotService:
        channels: list[AutopilotChannel] = []
        for ch in settings.autopilot_channels:
            name = ch.get("name", "")
            cid = ch.get("channel_id", "")
            handle = ch.get("handle", "")
            if not cid and handle:
                resolved = resolve_channel_id(handle)
                if resolved:
                    cid = resolved
            if cid:
                channels.append(AutopilotChannel(name=name or cid, channel_id=cid, handle=handle))

        return cls(
            channels=channels,
            repository=repository,
            poll_interval_minutes=settings.autopilot_poll_minutes,
            ignore_shorts=settings.autopilot_ignore_shorts,
            queue_latest_on_start=settings.autopilot_queue_latest_on_start,
            enabled=settings.autopilot_enabled,
        )

    def _fetch_channel_videos_ytdlp(
        self, channel: AutopilotChannel, max_results: int = 5
    ) -> list[AutopilotVideo]:
        """Fetch latest channel videos using yt-dlp to bypass cloud datacenter IP blocks."""
        url = f"https://www.youtube.com/channel/{channel.channel_id}/videos"
        cmd = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--flat-playlist",
            "--playlist-end",
            str(max_results),
            "--dump-json",
            "--extractor-args",
            "youtube:player_client=android,ios,tv",
        ]
        cookie_file = None
        for cand in [os.environ.get("YTDLP_COOKIE_FILE"), "cookies.txt", "youtube-cookies.txt"]:
            if cand and Path(cand).exists():
                cookie_file = cand
                break
        if cookie_file:
            cmd.extend(["--cookies", str(cookie_file)])
        cmd.append(url)
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
            if res.returncode != 0:
                logger.warning("yt-dlp fallback failed for %s: %s", channel.name, res.stderr[:200])
                return []
            videos: list[AutopilotVideo] = []
            for line in res.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    vid = data.get("id")
                    title = data.get("title", "")
                    live_status = str(data.get("live_status") or "").lower()
                    if live_status in ("is_upcoming", "is_live", "post_live") or data.get("was_live"):
                        continue
                    if "live event" in title.lower() or "premieres in" in title.lower():
                        continue
                    if vid:
                        videos.append(
                            AutopilotVideo(
                                video_id=vid,
                                title=title,
                                published_at=str(data.get("upload_date") or ""),
                                link=f"https://www.youtube.com/watch?v={vid}",
                                is_short=False,
                                channel_name=channel.name,
                                channel_id=channel.channel_id,
                            )
                        )
                except Exception:
                    continue
            return videos
        except Exception as exc:
            logger.warning("yt-dlp execution error for %s: %s", channel.name, exc)
            return []

    def fetch_channel_videos(
        self, channel: AutopilotChannel, timeout: float = 15.0
    ) -> list[AutopilotVideo]:
        """Fetch the latest up to 15 entries from the channel's YouTube Atom RSS feed, falling back to yt-dlp."""
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel.channel_id}"
        req = urllib.request.Request(url, headers=_DEFAULT_HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content = resp.read()
        except Exception as exc:
            logger.info("RSS feed unavailable for %s (%s); trying yt-dlp fallback...", channel.name, exc)
            return self._fetch_channel_videos_ytdlp(channel)

        try:
            root = ET.fromstring(content)
        except ET.ParseError as exc:
            logger.info("XML parse failed for %s (%s); trying yt-dlp fallback...", channel.name, exc)
            return self._fetch_channel_videos_ytdlp(channel)

        ns = {"atom": _ATOM_NS, "yt": _YT_NS}
        videos: list[AutopilotVideo] = []
        for entry in root.findall("atom:entry", ns):
            vid_elem = entry.find("yt:videoId", ns)
            title_elem = entry.find("atom:title", ns)
            pub_elem = entry.find("atom:published", ns)
            link_elem = entry.find("atom:link", ns)

            if vid_elem is None or not vid_elem.text:
                continue

            video_id = vid_elem.text.strip()
            title = title_elem.text.strip() if (title_elem is not None and title_elem.text) else ""
            published = pub_elem.text.strip() if (pub_elem is not None and pub_elem.text) else ""
            link = link_elem.attrib.get("href", "") if link_elem is not None else ""
            is_short = "/shorts/" in link or "/shorts/" in entry.attrib.get("id", "")

            videos.append(
                AutopilotVideo(
                    video_id=video_id,
                    title=title,
                    published_at=published,
                    link=link or f"https://www.youtube.com/watch?v={video_id}",
                    is_short=is_short,
                    channel_name=channel.name,
                    channel_id=channel.channel_id,
                )
            )

        if not videos:
            return self._fetch_channel_videos_ytdlp(channel)

        return videos

    def is_video_present_in_file(self, video_id: str, file_path: Path) -> bool:
        if not file_path.exists():
            return False
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            return video_id in content
        except OSError:
            return False

    def is_video_known(
        self,
        video_id: str,
        links_file: Path | None = None,
        downloaded_log: Path | None = None,
    ) -> bool:
        """Check whether a video is already in SQLite, links.txt, or downloaded log."""
        if self.repository.is_video_queued_or_processed(video_id):
            return True
        if self.repository.is_autopilot_seen(video_id):
            return True
        if links_file and self.is_video_present_in_file(video_id, links_file):
            return True
        return bool(downloaded_log and self.is_video_present_in_file(video_id, downloaded_log))

    def sync_latest_videos(self, links_file: Path) -> list[AutopilotVideo]:
        """
        Updates links.txt with the single newest video from each monitored channel,
        removing older duplicate entries, and records them in SQLite so they are NEVER
        taken again.
        """
        latest_videos: list[AutopilotVideo] = []
        links_file.parent.mkdir(parents=True, exist_ok=True)

        for channel in self.channels:
            videos = self.fetch_channel_videos(channel)
            if not videos:
                continue

            videos = sorted(videos, key=lambda x: x.published_at or "", reverse=True)
            eligible = [v for v in videos if not (self.ignore_shorts and v.is_short)]
            if not eligible:
                continue

            top = eligible[0]
            latest_videos.append(top)

            # Mark top as queued (never take it again)
            self.repository.mark_autopilot_seen(
                top.video_id,
                top.channel_id,
                top.title,
                top.published_at,
                queued=True,
            )

            # Mark all older videos from this channel as seen (never take them)
            for older in videos:
                if older.video_id != top.video_id:
                    self.repository.mark_autopilot_seen(
                        older.video_id,
                        older.channel_id,
                        older.title,
                        older.published_at,
                        queued=False,
                    )

        # Write clean links.txt with the latest videos
        lines = [
            "# Add one authorized YouTube video URL per line below.",
            "# A URL is removed atomically as soon as that video has downloaded successfully.",
            "# Downloaded URLs are recorded in work/downloaded-links.log.",
        ]
        for v in latest_videos:
            lines.append(f"# [Autopilot: {v.channel_name}] {v.title}")
            lines.append(v.watch_url)

        links_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return latest_videos

    async def bootstrap_baseline(
        self,
        links_file: Path,
        downloaded_log: Path | None = None,
    ) -> int:
        """Ensure channels have seen baselines established on first run.

        If queue_latest_on_start is True, synchronizes links.txt with the latest video
        from each channel.
        """
        if self.queue_latest_on_start:
            latest = self.sync_latest_videos(links_file)
            return len(latest)

        queued_count = 0
        for channel in self.channels:
            videos = await asyncio.to_thread(self.fetch_channel_videos, channel)
            if not videos:
                continue
            for v in videos:
                self.repository.mark_autopilot_seen(
                    v.video_id, v.channel_id, v.title, v.published_at, queued=False
                )
        return queued_count

    async def check_for_new_videos(
        self,
        links_file: Path,
        downloaded_log: Path | None = None,
        allow_backfill: bool = False,
    ) -> list[AutopilotVideo]:
        """Poll all channels and return any newly published videos not yet seen or queued."""
        new_videos: list[AutopilotVideo] = []

        for channel in self.channels:
            videos = await asyncio.to_thread(self.fetch_channel_videos, channel)
            if not videos:
                continue

            videos = sorted(videos, key=lambda x: x.published_at or "", reverse=True)
            eligible = [v for v in videos if not (self.ignore_shorts and v.is_short)]
            if not eligible:
                continue

            if allow_backfill:
                for v in eligible:
                    if not self.is_video_known(v.video_id, links_file, downloaded_log):
                        new_videos.append(v)
            else:
                latest = eligible[0]
                if not self.is_video_known(latest.video_id, links_file, downloaded_log):
                    new_videos.append(latest)
                    # Mark older videos as seen so they are never queued
                    for older in eligible[1:]:
                        if not self.repository.is_autopilot_seen(older.video_id):
                            self.repository.mark_autopilot_seen(
                                older.video_id,
                                older.channel_id,
                                older.title,
                                older.published_at,
                                queued=False,
                            )

        return new_videos

    def queue_videos(self, videos: list[AutopilotVideo], links_file: Path) -> list[str]:
        """Append watch URLs of newly detected videos to links.txt and mark them in SQLite."""
        if not videos:
            return []

        urls_to_add: list[str] = []
        links_file.parent.mkdir(parents=True, exist_ok=True)
        existing_text = links_file.read_text(encoding="utf-8") if links_file.exists() else ""
        existing_lines = {line.strip() for line in existing_text.splitlines()}

        lines_to_append: list[str] = []
        for v in videos:
            url = v.watch_url
            if url not in existing_lines and url not in urls_to_add:
                urls_to_add.append(url)
                lines_to_append.append(f"# [Autopilot: {v.channel_name}] {v.title}\n{url}\n")
            self.repository.mark_autopilot_seen(
                v.video_id, v.channel_id, v.title, v.published_at, queued=True
            )

        if lines_to_append:
            prefix = "\n" if existing_text and not existing_text.endswith("\n") else ""
            with links_file.open("a", encoding="utf-8") as f:
                f.write(prefix + "".join(lines_to_append))

        return urls_to_add

    async def check_and_queue(
        self,
        links_file: Path,
        downloaded_log: Path | None = None,
        allow_backfill: bool = False,
    ) -> list[AutopilotVideo]:
        """Check all monitored channels and queue new videos into links.txt."""
        if not self.enabled or not self.channels:
            return []

        new_videos = await self.check_for_new_videos(
            links_file, downloaded_log, allow_backfill=allow_backfill
        )
        if new_videos:
            self.queue_videos(new_videos, links_file)
        return new_videos


def main() -> None:
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(errors="replace")

    parser = argparse.ArgumentParser(
        description="Channel Auto-Pilot: Monitor YouTube channels and queue new videos."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--check",
        action="store_true",
        help="Poll all configured channels right now and queue new uploads into links.txt",
    )
    group.add_argument(
        "--list",
        action="store_true",
        help="List all configured channels and their latest video titles",
    )
    group.add_argument(
        "--sync",
        action="store_true",
        help="Update links.txt with the single newest video from all creators, replacing old links",
    )
    group.add_argument(
        "--fetch-latest",
        action="store_true",
        help="Synchronize the single newest video from each channel into links.txt",
    )
    group.add_argument(
        "--backfill",
        action="store_true",
        help="Queue all available historical non-short videos from all channel feeds",
    )
    parser.add_argument(
        "--resolve",
        metavar="HANDLE",
        help="Resolve a channel handle (e.g. '@MrBeast') to its canonical channel ID",
    )
    args = parser.parse_args()

    if args.resolve:
        cid = resolve_channel_id(args.resolve)
        if cid:
            print(f"Resolved {args.resolve} -> {cid}")
        else:
            print(f"Could not resolve channel ID for {args.resolve}", file=sys.stderr)
            sys.exit(1)
        return

    settings = Settings.from_env()
    repository = JobRepository(settings.database_path)
    service = AutopilotService.from_settings(settings, repository)

    if not service.channels:
        print(
            "No channels configured under [autopilot] in channels.toml.",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.list:
        print(f"Configured Autopilot Channels ({len(service.channels)}):")
        for ch in service.channels:
            videos = service.fetch_channel_videos(ch)
            if videos:
                latest = videos[0]
                short_tag = " [SHORT]" if latest.is_short else ""
                print(f"- {ch.name} ({ch.channel_id})")
                print(f"    Latest: {latest.title}{short_tag} -> {latest.watch_url}")
            else:
                print(f"- {ch.name} ({ch.channel_id}) - no videos found")
        return

    if args.sync or args.fetch_latest:
        print("Synchronizing links.txt with the single newest video from each channel...")
        synced = service.sync_latest_videos(settings.links_file)
        print(f"Synchronized {len(synced)} newest video(s) into {settings.links_file}:")
        for v in synced:
            print(f"  + [{v.channel_name}] {v.title} -> {v.watch_url}")
        return

    # Default action or --check or --backfill:
    print(f"Checking {len(service.channels)} channels for new uploads...")
    new_videos = asyncio.run(
        service.check_and_queue(
            settings.links_file,
            settings.downloaded_links_log,
            allow_backfill=args.backfill,
        )
    )
    if new_videos:
        print(f"Detected and queued {len(new_videos)} new video(s):")
        for v in new_videos:
            print(f"  + [{v.channel_name}] {v.title} -> {v.watch_url}")
    else:
        print("All channels are up to date. No new videos.")


if __name__ == "__main__":
    main()
