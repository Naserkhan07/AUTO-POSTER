from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from shorts_bot.captions import CaptionStyle, TimedWord, create_caption_file
from shorts_bot.gameplay import GameplayManager
from shorts_bot.media import MediaProcessor


class MediaSplitTestCase(unittest.TestCase):
    def test_split_screen_render_with_captions(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            processor = MediaProcessor(video_preset="ultrafast", video_layout="split_gameplay")

            # 1. Create dummy source videos using gameplay generator
            mgr = GameplayManager(base_dir=tmp_path / "gameplay")
            primary_src = tmp_path / "primary.mp4"
            mgr.generate_placeholder_clip(primary_src, category="gta5", duration=3.0)

            gp_clip = tmp_path / "gameplay" / "gta5" / "local_gta.mp4"
            gp_clip.parent.mkdir(parents=True, exist_ok=True)
            mgr.generate_placeholder_clip(gp_clip, category="gta5", duration=3.0)

            # 2. Get a gameplay clip
            selection = mgr.select_gameplay(clip_index=1, duration_needed=2.0)

            # 3. Create a caption file
            ass_file = tmp_path / "test.ass"
            words = [
                TimedWord(text="RUNNING", start=0.2, end=0.8),
                TimedWord(text="OLYMPICS", start=0.8, end=1.5),
            ]
            create_caption_file(ass_file, words, clip_start=0.0, clip_duration=2.0, style=CaptionStyle())

            # 4. Render short
            out_short = tmp_path / "rendered_short.mp4"
            processor.render_short(
                source=primary_src,
                output=out_short,
                start_seconds=0.0,
                duration_seconds=2.0,
                gameplay_video=selection.path,
                gameplay_start_seconds=selection.start_seconds,
                subtitles_path=ass_file,
            )

            self.assertTrue(out_short.exists())
            self.assertGreater(out_short.stat().st_size, 1000)

            # Check duration via probe
            dur = processor.probe_duration(out_short)
            self.assertGreater(dur, 1.5)


if __name__ == "__main__":
    unittest.main()

