from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .errors import ConfigurationError, MediaError


class MediaProcessor:
    def __init__(
        self,
        ffmpeg: str = "ffmpeg",
        ffprobe: str = "ffprobe",
        video_layout: str = "fit_black",
        allow_upscale: bool = False,
        video_crf: int = 18,
        video_preset: str = "slow",
    ) -> None:
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.video_layout = video_layout
        self.allow_upscale = allow_upscale
        self.video_crf = video_crf
        self.video_preset = video_preset

    def check_tools(self) -> None:
        missing = [tool for tool in (self.ffmpeg, self.ffprobe) if shutil.which(tool) is None]
        if missing:
            raise ConfigurationError(
                f"Missing media tools: {', '.join(missing)}. Install FFmpeg and ffprobe."
            )

    def probe_duration(self, path: Path) -> float:
        result = self._run(
            [
                self.ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ]
        )
        try:
            return float(json.loads(result.stdout)["format"]["duration"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MediaError(f"Could not read media duration for {path.name}.") from exc

    def extract_audio(self, source: Path, output: Path) -> Path:
        output.parent.mkdir(parents=True, exist_ok=True)
        # Use 16k mono mp3 to guarantee audio stays well below Groq Whisper's 25MB limit
        self._run(
            [
                self.ffmpeg,
                "-y",
                "-i",
                str(source),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "16k",
                str(output),
            ],
            timeout=1800,
        )
        return output

    def render_short(
        self,
        source: Path,
        output: Path,
        start_seconds: float,
        duration_seconds: float,
        gameplay_video: Path | None = None,
        gameplay_start_seconds: float = 0.0,
        subtitles_path: Path | None = None,
    ) -> Path:
        output.parent.mkdir(parents=True, exist_ok=True)
        sub_escaped = (
            subtitles_path.resolve().as_posix().replace(":", r"\:")
            if subtitles_path and subtitles_path.exists()
            else None
        )

        use_gameplay = (self.video_layout == "split_gameplay") or (gameplay_video is not None)
        if use_gameplay and gameplay_video is not None:
            command = [
                self.ffmpeg,
                "-y",
                "-ss",
                f"{start_seconds:.3f}",
                "-i",
                str(source),
                "-ss",
                f"{gameplay_start_seconds:.3f}",
                "-stream_loop",
                "-1",
                "-i",
                str(gameplay_video),
                "-t",
                f"{duration_seconds:.3f}",
                "-sws_flags",
                "lanczos",
            ]
            top_filter = (
                "[0:v]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960,setsar=1[top]"
            )
            bottom_filter = (
                "[1:v]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960,setsar=1[bottom]"
            )
            stack_filter = "[top][bottom]vstack=inputs=2[stacked]"
            divider_filter = (
                "[stacked]drawbox=y=958:color=black:width=iw:height=4:t=fill[split_base]"
            )
            if sub_escaped:
                sub_filter = f"[split_base]ass='{sub_escaped}'[v]"
                filter_complex = (
                    f"{top_filter};{bottom_filter};{stack_filter};{divider_filter};{sub_filter}"
                )
            else:
                tail = "[split_base]null[v]"
                filter_complex = (
                    f"{top_filter};{bottom_filter};{stack_filter};{divider_filter};{tail}"
                )

            command.extend(
                [
                    "-filter_complex",
                    filter_complex,
                    "-map",
                    "[v]",
                    "-map",
                    "0:a?",
                ]
            )
        else:
            command = [
                self.ffmpeg,
                "-y",
                "-ss",
                f"{start_seconds:.3f}",
                "-i",
                str(source),
                "-t",
                f"{duration_seconds:.3f}",
                "-sws_flags",
                "lanczos",
            ]
            if self.video_layout == "blurred_background":
                if sub_escaped:
                    video_filter = (
                        "[0:v]split=2[bg][fg];"
                        "[bg]scale=1080:1920:force_original_aspect_ratio=increase,"
                        "crop=1080:1920,boxblur=30:2[blurred];"
                        "[fg]scale=1080:1920:force_original_aspect_ratio=decrease[front];"
                        f"[blurred][front]overlay=(W-w)/2:(H-h)/2,setsar=1[base];"
                        f"[base]ass='{sub_escaped}'[v]"
                    )
                else:
                    video_filter = (
                        "[0:v]split=2[bg][fg];"
                        "[bg]scale=1080:1920:force_original_aspect_ratio=increase,"
                        "crop=1080:1920,boxblur=30:2[blurred];"
                        "[fg]scale=1080:1920:force_original_aspect_ratio=decrease[front];"
                        "[blurred][front]overlay=(W-w)/2:(H-h)/2,setsar=1[v]"
                    )
                command.extend(
                    [
                        "-filter_complex",
                        video_filter,
                        "-map",
                        "[v]",
                        "-map",
                        "0:a?",
                    ]
                )
            elif self.video_layout == "fit_black":
                if self.allow_upscale:
                    scale_filter = (
                        "scale=1080:1920:force_original_aspect_ratio=decrease:force_divisible_by=2"
                    )
                else:
                    scale_filter = (
                        "scale='min(iw,1080)':'min(ih,1920)':"
                        "force_original_aspect_ratio=decrease:force_divisible_by=2"
                    )
                video_filter = f"{scale_filter},pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,setsar=1"
                if sub_escaped:
                    video_filter += f",ass='{sub_escaped}'"
                command.extend(
                    [
                        "-map",
                        "0:v:0",
                        "-map",
                        "0:a?",
                        "-vf",
                        video_filter,
                    ]
                )
            else:
                if self.allow_upscale:
                    video_filter = (
                        "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1"
                    )
                else:
                    # Crop the largest native-resolution 9:16 region without inventing pixels.
                    # H.264 requires even dimensions, hence truncation to a multiple of two.
                    video_filter = (
                        "crop='trunc(min(iw,ih*9/16)/2)*2':'trunc(min(ih,iw*16/9)/2)*2',setsar=1"
                    )
                if sub_escaped:
                    video_filter += f",ass='{sub_escaped}'"
                command.extend(
                    [
                        "-map",
                        "0:v:0",
                        "-map",
                        "0:a?",
                        "-vf",
                        video_filter,
                    ]
                )
        command.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                self.video_preset,
                "-crf",
                str(self.video_crf),
                "-profile:v",
                "high",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                str(output),
            ]
        )
        self._run(command, timeout=1800)
        if not output.exists() or output.stat().st_size == 0:
            raise MediaError("FFmpeg did not create the Short.")
        return output

    def generate_thumbnail(self, video: Path, output: Path, at_seconds: float) -> Path:
        output.parent.mkdir(parents=True, exist_ok=True)
        command = [
            self.ffmpeg,
            "-y",
            "-ss",
            f"{max(0, at_seconds):.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
        ]
        if self.video_layout == "blurred_background":
            thumbnail_filter = (
                "[0:v]split=2[bg][fg];"
                "[bg]scale=1280:720:force_original_aspect_ratio=increase,"
                "crop=1280:720,boxblur=20:2[blurred];"
                "[fg]scale=1280:720:force_original_aspect_ratio=decrease[front];"
                "[blurred][front]overlay=(W-w)/2:(H-h)/2"
            )
            command.extend(["-filter_complex", thumbnail_filter])
        elif self.video_layout in {"fit_black", "split_gameplay"}:
            thumbnail_filter = (
                "scale=1280:720:force_original_aspect_ratio=decrease,"
                "pad=1280:720:(ow-iw)/2:(oh-ih)/2:black"
            )
            command.extend(["-vf", thumbnail_filter])
        else:
            thumbnail_filter = "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720"
            command.extend(["-vf", thumbnail_filter])
        command.extend(["-q:v", "3", str(output)])
        self._run(command, timeout=180)
        if not output.exists() or output.stat().st_size == 0:
            raise MediaError("FFmpeg did not create the thumbnail.")
        return output

    @staticmethod
    def _run(command: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            raise ConfigurationError(f"Required command {command[0]!r} was not found.") from exc
        except subprocess.TimeoutExpired as exc:
            raise MediaError(f"Media command timed out after {timeout} seconds.") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "Unknown FFmpeg error").strip()[-1500:]
            raise MediaError(f"Media processing failed: {detail}") from exc
