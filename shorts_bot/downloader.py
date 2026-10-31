from __future__ import annotations

import asyncio
import re
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp

from .errors import DownloadError
from .models import SourceVideo

_URL_PATTERN = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
_ALLOWED_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}


def is_youtube_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and (parsed.hostname or "").lower() in _ALLOWED_HOSTS


def extract_youtube_urls(text: str) -> list[str]:
    urls: list[str] = []
    for match in _URL_PATTERN.findall(text):
        candidate = match.rstrip(".,;:!?)]}'\"")
        if is_youtube_url(candidate) and candidate not in urls:
            urls.append(candidate)
    return urls


class VideoDownloader:
    def __init__(
        self,
        cookies_from_browser: str = "",
        browser_profile: str = "",
        cookie_file: Path | None = None,
    ) -> None:
        self.cookies_from_browser = cookies_from_browser
        self.browser_profile = browser_profile
        self.cookie_file = cookie_file

    async def download(self, url: str, destination: Path) -> SourceVideo:
        if not is_youtube_url(url):
            raise DownloadError("Only individual youtube.com or youtu.be URLs are accepted.")
        return await asyncio.to_thread(self._download_sync, url, destination)

    @staticmethod
    def _retry_delay(
        attempt: int = 1,
        *,
        n: int | None = None,
        **_: object,
    ) -> int:
        """Use bounded backoff across old and current yt-dlp callback signatures."""
        retry_number = n if n is not None else attempt
        return min(2 ** max(0, retry_number - 1), 20)

    @classmethod
    def _download_options(
        cls,
        output_template: str,
        cookies_from_browser: str = "",
        browser_profile: str = "",
        cookie_file: Path | None = None,
    ) -> dict[str, object]:
        options: dict[str, object] = {
            # Exact Python API equivalent of: yt-dlp -f "bestvideo+bestaudio" URL
            # The streams are remuxed into MKV without re-encoding the downloaded source.
            "format": "bestvideo+bestaudio",
            "outtmpl": output_template,
            "merge_output_format": "mkv",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "restrictfilenames": True,
            "overwrites": True,
            "writeinfojson": True,
            # Windows networks and some ISPs intermittently reset YouTube CDN streams.
            # Resume partial files, force IPv4, use small HTTP chunks, and back off.
            "continuedl": True,
            "source_address": "0.0.0.0",
            "socket_timeout": 30,
            "http_chunk_size": 10 * 1024 * 1024,
            "concurrent_fragment_downloads": 1,
            # Current YouTube extraction requires a full JS runtime for player challenges.
            # The project's yt-dlp[deno] dependency installs this runtime in the venv.
            "js_runtimes": {"deno": {}},
            "retries": 10,
            "fragment_retries": 10,
            "extractor_retries": 5,
            "file_access_retries": 5,
            "retry_sleep_functions": {
                "http": cls._retry_delay,
                "fragment": cls._retry_delay,
                "extractor": cls._retry_delay,
            },
        }
        # If the BGUtil PO Token Provider is active on localhost:4416, register it with yt-dlp
        import socket
        pot_active = False
        try:
            with socket.create_connection(("127.0.0.1", 4416), timeout=0.2):
                pot_active = True
        except OSError:
            pot_active = False

        if pot_active:
            options["extractor_args"] = {
                "youtubepot-bgutilhttp": {"base_url": "http://127.0.0.1:4416"},
                "youtube": {"player_client": ["android", "tv"]},
            }

        if cookie_file:
            # A Netscape-format export avoids Windows Chromium DPAPI/app-bound encryption.
            # Never combine it with browser extraction, which would still trigger decryption.
            options["cookiefile"] = str(cookie_file)
        elif cookies_from_browser:
            options["cookiesfrombrowser"] = (
                cookies_from_browser,
                browser_profile or None,
                None,
                None,
            )
        return options

    @staticmethod
    def _extract_info(url: str, options: dict[str, object]) -> dict[str, object]:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=True)
        if not isinstance(info, dict):
            raise DownloadError("YouTube returned no video metadata.")
        return info

    def _download_error_detail(self, detail: str) -> str:
        normalized = detail.casefold()
        if "failed to decrypt with dpapi" in normalized:
            return (
                "Chrome cookies use Windows app-bound encryption and cannot be read directly. "
                "Export YouTube cookies in Netscape format, set "
                "YTDLP_COOKIE_FILE=youtube-cookies.txt, and clear "
                "YTDLP_COOKIES_FROM_BROWSER."
            )
        if "sign in to confirm" in normalized:
            if self.cookies_from_browser:
                return (
                    f"YouTube rejected cookies from {self.cookies_from_browser}. "
                    "Confirm that you are signed in to YouTube in that browser, "
                    "close the browser, and retry."
                )
            return (
                "YouTube requires signed-in cookies. Refresh the Netscape-format "
                "youtube-cookies.txt export and retry."
            )
        if "requested format is not available" in normalized:
            return (
                "YouTube did not expose separate best-video and best-audio streams. "
                "Update yt-dlp and yt-dlp-ejs, then refresh youtube-cookies.txt."
            )
        return detail

    @staticmethod
    def _probe_duration_safe(path: Path) -> float:
        import subprocess
        try:
            probe = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(path),
                ],
                capture_output=True, text=True, check=True,
            )
            return float(probe.stdout.strip())
        except Exception:
            return 60.0

    def _download_pytubefix(self, url: str, destination: Path) -> SourceVideo:
        import subprocess
        from pytubefix import YouTube

        destination.mkdir(parents=True, exist_ok=True)
        # Prioritize ANDROID and TV clients which bypass web botguard challenges
        for client in ("ANDROID", "TV", "MWEB", "WEB"):
            try:
                yt = YouTube(url, client=client)
                title = yt.title or "Untitled video"
                duration = float(yt.length or 0)
                uploader = yt.author or "Unknown creator"
                vid_id = yt.video_id or "unknown"

                video_stream = (
                    yt.streams.filter(only_video=True, file_extension="mp4")
                    .order_by("resolution")
                    .desc()
                    .first()
                    or yt.streams.filter(only_video=True).order_by("resolution").desc().first()
                )
                audio_stream = yt.streams.filter(only_audio=True).order_by("abr").desc().first()

                # Attempt separate adaptive streams first
                if video_stream and audio_stream:
                    try:
                        v_temp = destination / "temp_video.mp4"
                        a_temp = destination / f"temp_audio.{audio_stream.subtype}"
                        video_stream.download(output_path=str(destination), filename=v_temp.name)
                        audio_stream.download(output_path=str(destination), filename=a_temp.name)

                        merged_path = destination / "source.mkv"
                        cmd = [
                            "ffmpeg", "-y",
                            "-i", str(v_temp),
                            "-i", str(a_temp),
                            "-c", "copy",
                            "-shortest",
                            str(merged_path),
                        ]
                        subprocess.run(cmd, check=True, capture_output=True)

                        v_temp.unlink(missing_ok=True)
                        a_temp.unlink(missing_ok=True)

                        if duration <= 0:
                            duration = self._probe_duration_safe(merged_path)

                        return SourceVideo(
                            path=merged_path,
                            source_url=url,
                            video_id=vid_id,
                            title=title,
                            uploader=uploader,
                            duration_seconds=duration,
                        )
                    except Exception:
                        pass

                # If adaptive streams fail (e.g. SABR PoToken requirement), use progressive stream
                prog = yt.streams.filter(progressive=True).order_by("resolution").desc().first()
                if prog:
                    out_path = destination / f"source.{prog.subtype}"
                    prog.download(output_path=str(destination), filename=out_path.name)
                    if duration <= 0:
                        duration = self._probe_duration_safe(out_path)
                    return SourceVideo(
                        path=out_path,
                        source_url=url,
                        video_id=vid_id,
                        title=title,
                        uploader=uploader,
                        duration_seconds=duration,
                    )
            except Exception:
                continue

        raise DownloadError("YouTube download failed with both yt-dlp and pytubefix.")

    def _download_sync(self, url: str, destination: Path) -> SourceVideo:
        destination.mkdir(parents=True, exist_ok=True)
        output_template = str(destination / "source.%(ext)s")
        options = self._download_options(
            output_template,
            self.cookies_from_browser,
            self.browser_profile,
            self.cookie_file,
        )
        authenticated = "cookiefile" in options or "cookiesfrombrowser" in options
        try:
            info = self._extract_info(url, options)
        except yt_dlp.utils.DownloadError as exc:
            detail = str(exc)
            if "sign in to confirm" in detail.casefold() or "bot" in detail.casefold():
                # Cloud datacenter IPs are blocked by default web client or rejected cookies.
                # 1. Try clean options without cookies (in case cookies are expired/flagged)
                clean_options = dict(options)
                clean_options.pop("cookiefile", None)
                clean_options.pop("cookiesfrombrowser", None)
                clean_options["format"] = "bestvideo+bestaudio/best"
                clean_extractor_args: dict[str, Any] = {
                    "youtube": {"player_client": ["android", "tv"]},
                }
                import socket
                try:
                    with socket.create_connection(("127.0.0.1", 4416), timeout=0.2):
                        clean_extractor_args["youtubepot-bgutilhttp"] = {"base_url": "http://127.0.0.1:4416"}
                except OSError:
                    pass
                clean_options["extractor_args"] = clean_extractor_args
                try:
                    info = self._extract_info(url, clean_options)
                except Exception:
                    # 2. Try pytubefix fallback with ANDROID/TV progressive extraction
                    try:
                        return self._download_pytubefix(url, destination)
                    except Exception:
                        raise DownloadError(
                            f"YouTube download failed: {self._download_error_detail(detail)}"
                        ) from exc
            elif "live event will begin" in detail.casefold() or "premieres in" in detail.casefold():
                raise DownloadError(f"Scheduled livestream/premiere cannot be downloaded: {detail}")
            elif "video is unavailable" in detail.casefold() or "this video is unavailable" in detail.casefold() or "private video" in detail.casefold():
                raise DownloadError(f"Video is unavailable or private on YouTube: {detail}")
            elif "requested format is not available" in detail.casefold() and authenticated:
                # Account cookies can occasionally be assigned a YouTube client experiment that
                # exposes only SABR/image formats. Retry the exact same bestvideo+bestaudio
                # selector without authentication; this often restores normal public streams.
                public_options = dict(options)
                public_options.pop("cookiefile", None)
                public_options.pop("cookiesfrombrowser", None)
                try:
                    info = self._extract_info(url, public_options)
                except yt_dlp.utils.DownloadError as public_exc:
                    # A public default client can expose a format URL that later returns 403
                    # when YouTube requires a GVS Proof-of-Origin token. Force mweb/web_safari
                    # so the installed WebPoClient provider is asked to mint that token.
                    token_options = dict(public_options)
                    token_options["extractor_args"] = {
                        "youtube": {"player_client": ["mweb", "web_safari"]}
                    }
                    try:
                        info = self._extract_info(url, token_options)
                    except yt_dlp.utils.DownloadError as token_exc:
                        # Fallback to pytubefix Android progressive stream
                        try:
                            return self._download_pytubefix(url, destination)
                        except Exception:
                            public_detail = self._download_error_detail(str(public_exc))
                            token_detail = self._download_error_detail(str(token_exc))
                            raise DownloadError(
                                "YouTube exposed no separate bestvideo+bestaudio streams with the "
                                "configured cookies, and both public retries failed. Confirm the WPC "
                                "PO Token Provider is active and keep its temporary Chrome window "
                                f"open. Default public retry: {public_detail}. "
                                f"PO-token client retry: {token_detail}"
                            ) from token_exc
            elif "403" in detail.casefold() or "forbidden" in detail.casefold() or "unable to download video data" in detail.casefold():
                # 403 Forbidden on CDN stream fragments -> Fallback to pytubefix
                try:
                    return self._download_pytubefix(url, destination)
                except Exception:
                    raise DownloadError(
                        f"YouTube download failed: {self._download_error_detail(detail)}"
                    ) from exc
            else:
                raise DownloadError(
                    f"YouTube download failed: {self._download_error_detail(detail)}"
                ) from exc
        except Exception as exc:
            raise DownloadError(f"Unexpected downloader error: {exc}") from exc

        candidates = [
            path
            for path in destination.glob("source.*")
            if path.is_file() and path.suffix not in {".json", ".part", ".ytdl"}
        ]
        if not candidates:
            raise DownloadError("The downloader finished but no video file was created.")
        source_path = max(candidates, key=lambda path: path.stat().st_size)
        duration = float(info.get("duration") or 0)
        if duration <= 0:
            raise DownloadError("Could not determine the source video's duration.")
        if duration < 20:
            raise DownloadError("The source video is shorter than the minimum 20-second Short.")

        return SourceVideo(
            path=source_path,
            source_url=str(info.get("webpage_url") or url),
            video_id=str(info.get("id") or "unknown"),
            title=str(info.get("title") or "Untitled video"),
            uploader=str(info.get("uploader") or info.get("channel") or "Unknown creator"),
            duration_seconds=duration,
        )
