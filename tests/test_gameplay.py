from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from shorts_bot.gameplay import GameplayManager


class GameplayManagerTestCase(unittest.TestCase):
    def test_ensure_directories(self) -> None:
        with TemporaryDirectory() as tmpdir:
            mgr = GameplayManager(base_dir=tmpdir)
            p = Path(tmpdir)
            self.assertTrue((p / "gta5").is_dir())
            self.assertTrue((p / "minecraft").is_dir())
            self.assertTrue((p / "subway_surfers").is_dir())
            self.assertTrue((p / "README.md").is_file())

    def test_list_clips_by_category(self) -> None:
        with TemporaryDirectory() as tmpdir:
            mgr = GameplayManager(base_dir=tmpdir)
            p = Path(tmpdir)
            (p / "gta5" / "gta_01.mp4").touch()
            (p / "minecraft" / "mc_parkour.mov").touch()

            clips = mgr.list_clips_by_category()
            self.assertEqual(len(clips["gta5"]), 1)
            self.assertEqual(len(clips["minecraft"]), 1)
            self.assertEqual(len(clips["subway_surfers"]), 0)

    def test_select_gameplay_rotation(self) -> None:
        with TemporaryDirectory() as tmpdir:
            mgr = GameplayManager(base_dir=tmpdir)
            p = Path(tmpdir)
            (p / "gta5" / "gta.mp4").touch()
            (p / "gta5" / "gta2.mp4").touch()
            (p / "minecraft" / "mc.mp4").touch()
            (p / "subway_surfers" / "ss.mp4").touch()

            # clip 1 -> gta5
            s1 = mgr.select_gameplay(clip_index=1, duration_needed=10.0)
            self.assertEqual(s1.category, "gta5")

            # clip 2 -> minecraft
            s2 = mgr.select_gameplay(clip_index=2, duration_needed=10.0)
            self.assertEqual(s2.category, "minecraft")

            # clip 3 -> subway_surfers
            s3 = mgr.select_gameplay(clip_index=3, duration_needed=10.0)
            self.assertEqual(s3.category, "subway_surfers")

            # clip 4 -> loops back to gta5
            s4 = mgr.select_gameplay(clip_index=4, duration_needed=10.0)
            self.assertEqual(s4.category, "gta5")

    def test_never_repeats_same_gameplay_video(self) -> None:
        with TemporaryDirectory() as tmpdir:
            mgr = GameplayManager(base_dir=tmpdir)
            p = Path(tmpdir)
            (p / "gta5" / "gta_first.mp4").touch()
            (p / "gta5" / "gta_second.mp4").touch()

            # First selection
            first = mgr.select_gameplay(clip_index=1, duration_needed=10.0, preferred_category="gta5")
            self.assertIn(first.path.name, ["gta_first.mp4", "gta_second.mp4"])

            # Second selection MUST NOT be the same video!
            second = mgr.select_gameplay(clip_index=2, duration_needed=10.0, preferred_category="gta5")
            self.assertNotEqual(first.path.name, second.path.name)


if __name__ == "__main__":
    unittest.main()

