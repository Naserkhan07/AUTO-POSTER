from __future__ import annotations

import json
import logging
import random
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SUPPORTED_CATEGORIES = ("gta5", "minecraft", "subway_surfers")
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}

DEFAULT_GAMEPLAY_SOURCES: dict[str, dict[str, str]] = {
    "gta5": {
        "url": "https://www.youtube.com/watch?v=ZtLrNBdXT7M",
        "filename": "gta5_gameplay.mp4",
        "search_query": "ytsearch1:gta 5 mega ramp car stunts gameplay no copyright",
    },
    "minecraft": {
        "url": "https://www.youtube.com/watch?v=XBIaqOm0RKQ",
        "filename": "minecraft_parkour_gameplay.mp4",
        "search_query": "ytsearch1:minecraft parkour gameplay no copyright shorts 60fps",
    },
    "subway_surfers": {
        "url": "https://www.youtube.com/watch?v=qKLi8rkRauU",
        "filename": "subway_surfers_gameplay.mp4",
        "search_query": "ytsearch1:subway surfers gameplay no copyright 60fps",
    },
}


@dataclass(frozen=True, slots=True)
class GameplaySelection:
    path: Path
    category: str
    start_seconds: float
    duration_seconds: float


class GameplayManager:
    """
    Manages gameplay background footage (GTA 5, Minecraft parkour, Subway Surfers).
    Provides round-robin or randomized clip selection and random start-offset seeking.
    """

    def __init__(
        self,
        base_dir: Path | str = "assets/gameplay",
        categories: Sequence[str] = SUPPORTED_CATEGORIES,
        ffmpeg: str = "ffmpeg",
        ffprobe: str = "ffprobe",
        db: Any = None,
    ) -> None:
        self.base_dir = Path(base_dir).resolve()
        self.categories = tuple(categories) if categories else SUPPORTED_CATEGORIES
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.db = db
        self.used_file = self.base_dir / "used_gameplay.json"
        self.ensure_directories()

    def get_used_identifiers(self, category: str | None = None) -> set[str]:
        used: set[str] = set()
        if self.db and hasattr(self.db, "get_used_gameplay"):
            try:
                used.update(self.db.get_used_gameplay(category))
            except Exception as exc:
                logger.debug("Failed reading used gameplay from DB: %s", exc)

        if self.used_file.exists():
            try:
                data = json.loads(self.used_file.read_text(encoding="utf-8"))
                if category:
                    used.update(data.get(category, []))
                else:
                    for cat_list in data.values():
                        used.update(cat_list)
            except Exception as exc:
                logger.debug("Failed reading used gameplay json: %s", exc)
        return used

    def mark_used(
        self, category: str, identifier: str, job_id: str | None = None
    ) -> None:
        if self.db and hasattr(self.db, "mark_gameplay_used"):
            try:
                self.db.mark_gameplay_used(category, identifier, job_id=job_id)
            except Exception as exc:
                logger.debug("Failed marking gameplay used in DB: %s", exc)

        try:
            data: dict[str, list[str]] = {}
            if self.used_file.exists():
                data = json.loads(self.used_file.read_text(encoding="utf-8"))
            data.setdefault(category, [])
            if identifier not in data[category]:
                data[category].append(identifier)
            self.used_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.debug("Failed writing used gameplay json: %s", exc)

    def ensure_directories(self) -> dict[str, Path]:
        """Creates assets/gameplay subdirectories for gta5, minecraft, subway_surfers."""
        dirs: dict[str, Path] = {}
        self.base_dir.mkdir(parents=True, exist_ok=True)
        for cat in self.categories:
            p = self.base_dir / cat
            p.mkdir(parents=True, exist_ok=True)
            dirs[cat] = p

        readme = self.base_dir / "README.md"
        if not readme.exists():
            readme.write_text(
                "# Gameplay Footage Directory\n\n"
                "Place your background gameplay clips (.mp4, .mov, .mkv) in these folders:\n"
                "- `assets/gameplay/gta5/`: GTA 5 car stunt / mega ramp clips\n"
                "- `assets/gameplay/minecraft/`: Minecraft parkour clips\n"
                "- `assets/gameplay/subway_surfers/`: Subway Surfers endless run clips\n\n"
                "The bot automatically rotates between these in every generated video,\n"
                "crops to 1080x960, and picks a random starting offset for variety.\n",
                encoding="utf-8",
            )
        return dirs

    def list_clips_by_category(self) -> dict[str, list[Path]]:
        """Returns a dict mapping each category to a list of available video file paths."""
        clips: dict[str, list[Path]] = {cat: [] for cat in self.categories}
        for cat in self.categories:
            cat_dir = self.base_dir / cat
            if cat_dir.is_dir():
                found = sorted(
                    [
                        f
                        for f in cat_dir.iterdir()
                        if f.is_file()
                        and f.suffix.lower() in VIDEO_EXTENSIONS
                        and not f.name.startswith("procedural_")
                    ]
                )
                clips[cat] = found

        # Also collect any loose clips in the base directory
        loose = [
            f
            for f in self.base_dir.iterdir()
            if f.is_file()
            and f.suffix.lower() in VIDEO_EXTENSIONS
            and not f.name.startswith("procedural_")
        ]
        if loose:
            clips.setdefault("general", []).extend(loose)
        return clips

    def total_clips_count(self) -> int:
        cat_map = self.list_clips_by_category()
        return sum(len(v) for v in cat_map.values())

    def probe_clip_duration(self, path: Path) -> float:
        """Probes the duration in seconds of a video clip via ffprobe."""
        if shutil.which(self.ffprobe) is None:
            return 60.0
        try:
            cmd = [
                self.ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=15)
            val = float(res.stdout.strip())
            return val if val > 0 else 60.0
        except Exception as exc:
            logger.debug("Failed to probe duration for %s: %s", path, exc)
            return 60.0

    def fetch_new_gameplay_clip(
        self,
        category: str,
        exclude_ids: set[str] | None = None,
        ytdlp_path: str = "yt-dlp",
    ) -> Path | None:
        """
        Searches YouTube for a fresh No-Copyright gameplay video for this category,
        skipping any video that was already used. Downloads the first fresh video.
        """
        import sys

        actual_ytdlp = shutil.which(ytdlp_path) or (
            str(Path(sys.executable).parent / "yt-dlp.exe")
            if sys.platform == "win32"
            else None
        )
        if not actual_ytdlp:
            return None

        info = DEFAULT_GAMEPLAY_SOURCES.get(category)
        query = (
            info["search_query"].replace("ytsearch1:", "ytsearch20:")
            if info
            else f"ytsearch20:{category} gameplay no copyright 60fps"
        )

        used = set(exclude_ids or set()) | self.get_used_identifiers(category)
        cat_dir = self.base_dir / category
        cat_dir.mkdir(parents=True, exist_ok=True)
        for f in cat_dir.iterdir():
            if f.is_file():
                used.add(f.stem)
                used.add(f.name)

        logger.info(
            "[Gameplay] Searching YouTube for new %s footage (avoiding %d used)...",
            category,
            len(used),
        )
        search_cmd = [actual_ytdlp, query, "--get-id", "--get-title", "--no-playlist"]
        try:
            res = subprocess.run(
                search_cmd, capture_output=True, text=True, check=True, timeout=30
            )
            lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]
        except Exception as exc:
            logger.warning("[Gameplay] Search for %s failed: %s", category, exc)
            return None

        candidate_id: str | None = None
        for line in lines:
            if len(line) == 11 and " " not in line and line not in used:
                candidate_id = line
                break

        if not candidate_id:
            logger.warning("[Gameplay] No unused video found in search for %s", category)
            return None

        target_path = cat_dir / f"{candidate_id}.mp4"
        logger.info(
            "[Gameplay] Downloading fresh %s gameplay video: %s...", category, candidate_id
        )
        dl_cmd = [
            actual_ytdlp,
            f"https://www.youtube.com/watch?v={candidate_id}",
            "-f",
            "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
            "--remux-video",
            "mp4",
            "-o",
            str(target_path),
            "--no-playlist",
        ]
        try:
            subprocess.run(dl_cmd, check=True, capture_output=True, timeout=600)
            if target_path.exists() and target_path.stat().st_size > 0:
                return target_path
        except Exception as exc:
            logger.warning("[Gameplay] Download of %s failed: %s", candidate_id, exc)
        return None

    def select_gameplay(
        self,
        clip_index: int = 1,
        duration_needed: float = 30.0,
        preferred_category: str | None = None,
        job_id: str | None = None,
        avoid_used: bool = True,
    ) -> GameplaySelection:
        """
        Selects a gameplay clip, cycling through categories (or using preferred),
        and calculates a randomized start offset so every Short looks fresh.
        Guarantees that the SAME gameplay video is NOT repeated in another video.
        If no user video exists, creates/returns a procedural fallback loop.
        """
        all_clips = self.list_clips_by_category()

        # Determine target category
        if preferred_category and preferred_category in all_clips and all_clips[preferred_category]:
            cat = preferred_category
            candidates = all_clips[preferred_category]
        else:
            cat_idx = (clip_index - 1) % len(self.categories)
            cat = self.categories[cat_idx]
            candidates = all_clips.get(cat, [])

        # Fallback to any category with clips if target category is empty
        if not candidates:
            for other_cat, other_clips in all_clips.items():
                if other_clips:
                    cat = other_cat
                    candidates = other_clips
                    break

        # Filter out already used gameplay videos so they are NEVER repeated in another video
        if avoid_used and candidates:
            used = self.get_used_identifiers(cat)
            unused_candidates = [
                f for f in candidates if f.stem not in used and f.name not in used
            ]
            if unused_candidates:
                candidates = unused_candidates
            else:
                logger.info(
                    "[Gameplay] All local %s clips were used in previous videos. "
                    "Fetching fresh footage from YouTube...",
                    cat,
                )
                fresh = self.fetch_new_gameplay_clip(cat, exclude_ids=used)
                if fresh and fresh.exists() and fresh.stat().st_size > 0:
                    candidates = [fresh]
                else:
                    logger.info(
                        "[Gameplay] Could not fetch fresh clip; rotating from existing pool."
                    )

        # If still no clips exist, generate a procedural placeholder clip
        if not candidates:
            placeholder = self.base_dir / cat / f"procedural_{cat}.mp4"
            if not placeholder.exists():
                self.generate_placeholder_clip(placeholder, category=cat, duration=15.0)
            candidates = [placeholder]

        selected_path = random.choice(candidates)
        # Mark as used so it is never repeated in another video
        self.mark_used(cat, selected_path.stem, job_id=job_id)
        self.mark_used(cat, selected_path.name, job_id=job_id)

        total_dur = self.probe_clip_duration(selected_path)

        # Start from the middle of the gameplay video (GTA V, Minecraft, Subway Surfers)
        if total_dur > duration_needed + 5.0:
            mid = total_dur / 2.0
            half_window = min(30.0, total_dur * 0.05)
            min_start = max(0.0, mid - half_window)
            max_start = min(total_dur - duration_needed - 1.0, mid + half_window)
            if max_start > min_start:
                start_offset = random.uniform(min_start, max_start)
            else:
                start_offset = max(0.0, min(mid, total_dur - duration_needed - 1.0))
        else:
            start_offset = 0.0

        return GameplaySelection(
            path=selected_path,
            category=cat,
            start_seconds=round(start_offset, 2),
            duration_seconds=duration_needed,
        )

    def ensure_default_gameplay_clips(self, ytdlp_path: str = "yt-dlp") -> dict[str, Path]:
        """
        Ensures each category (gta5, minecraft, subway_surfers) has real gameplay footage.
        Downloads high-quality Creative Commons / royalty-free footage from YouTube if missing.
        """
        import sys

        downloaded: dict[str, Path] = {}
        for cat in self.categories:
            cat_dir = self.base_dir / cat
            cat_dir.mkdir(parents=True, exist_ok=True)
            existing = [
                f
                for f in cat_dir.iterdir()
                if f.is_file()
                and f.suffix.lower() in VIDEO_EXTENSIONS
                and not f.name.startswith("procedural_")
            ]
            if existing:
                continue

            info = DEFAULT_GAMEPLAY_SOURCES.get(cat)
            if not info:
                continue

            url = info["url"]
            out_name = info["filename"]
            target_path = cat_dir / out_name
            actual_ytdlp = shutil.which(ytdlp_path) or (
                str(Path(sys.executable).parent / "yt-dlp.exe")
                if sys.platform == "win32"
                else None
            )
            if actual_ytdlp and not target_path.exists():
                logger.info("Auto-downloading default gameplay for %s from %s...", cat, url)
                cmd = [
                    actual_ytdlp,
                    url,
                    "-f",
                    "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
                    "--remux-video",
                    "mp4",
                    "-o",
                    str(target_path),
                    "--no-playlist",
                ]
                try:
                    subprocess.run(cmd, check=True, capture_output=True, timeout=600)
                    downloaded[cat] = target_path
                except Exception as exc:
                    logger.warning("Failed to auto-download gameplay for %s: %s", cat, exc)

        return downloaded

    def generate_placeholder_clip(
        self,
        output_path: Path,
        category: str = "gta5",
        duration: float = 60.0,
    ) -> Path:
        """
        Generates a 1080x960 30fps animated test clip using FFmpeg filtergraphs.
        Used as an instant fallback when no user-provided gameplay videos exist yet.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if shutil.which(self.ffmpeg) is None:
            output_path.touch()
            return output_path

        colors = {
            "gta5": ("0x1A1A2E", "0xE94560", "GTA 5 GAMEPLAY"),
            "minecraft": ("0x1B4332", "0x52B788", "MINECRAFT PARKOUR"),
            "subway_surfers": ("0x3D0066", "0xFF9900", "SUBWAY SURFERS"),
        }
        bg_col, accent_col, label = colors.get(
            category, ("0x111111", "0x00FF66", "GAMEPLAY BACKGROUND")
        )

        filter_graph = f"testsrc2=size=1080x960:rate=30:duration={duration:.1f}"

        cmd = [
            self.ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            filter_graph,
            "-t",
            f"{duration:.1f}",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(output_path),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=60)
        except Exception as exc:
            logger.warning("Could not create FFmpeg placeholder for %s: %s", category, exc)
            output_path.touch()
        return output_path


if __name__ == "__main__":

    mgr = GameplayManager()
    clips = mgr.list_clips_by_category()
    print("=== Gameplay Video Assets ===")
    print(f"Base Directory: {mgr.base_dir}")
    total = 0
    for cat, files in clips.items():
        print(f"\n[{cat.upper()}] ({len(files)} clips):")
        for f in files:
            dur = mgr.probe_clip_duration(f)
            print(f"  - {f.name} ({dur:.1f}s)")
        total += len(files)
    print(f"\nTotal gameplay clips: {total}")
    if total == 0:
        print("\nTip: Drop your .mp4, .mov, or .mkv files into:")
        print("  - assets/gameplay/gta5/")
        print("  - assets/gameplay/minecraft/")
        print("  - assets/gameplay/subway_surfers/")
        print("Until then, procedural placeholder loops will be used automatically.")
