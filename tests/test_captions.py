from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from shorts_bot.captions import (
    CaptionStyle,
    TimedWord,
    build_ass_subtitles,
    chunk_words,
    create_caption_file,
    filter_and_offset_words,
    format_ass_time,
    parse_whisper_result,
)


class CaptionsTestCase(unittest.TestCase):
    def test_format_ass_time(self) -> None:
        self.assertEqual(format_ass_time(0.0), "0:00:00.00")
        self.assertEqual(format_ass_time(1.5), "0:00:01.50")
        self.assertEqual(format_ass_time(65.25), "0:01:05.25")
        self.assertEqual(format_ass_time(3661.12), "1:01:01.12")

    def test_parse_whisper_dict_words(self) -> None:
        data = {
            "words": [
                {"word": "I'll", "start": 0.1, "end": 0.4},
                {"word": "be", "start": 0.4, "end": 0.6},
                {"word": "running", "start": 0.6, "end": 1.1},
            ]
        }
        words = parse_whisper_result(data)
        self.assertEqual(len(words), 3)
        self.assertEqual(words[0].text, "I'll")
        self.assertAlmostEqual(words[2].end, 1.1)

    def test_parse_whisper_segments_interpolation(self) -> None:
        data = {
            "segments": [
                {
                    "start": 0.0,
                    "end": 2.0,
                    "text": "Running in Olympics",
                }
            ]
        }
        words = parse_whisper_result(data)
        self.assertEqual(len(words), 3)
        self.assertEqual(words[0].text, "Running")
        self.assertEqual(words[1].text, "in")
        self.assertEqual(words[2].text, "Olympics")
        self.assertAlmostEqual(words[0].start, 0.0)
        self.assertAlmostEqual(words[2].end, 2.0)

    def test_filter_and_offset_words(self) -> None:
        words = [
            TimedWord("before", 5.0, 8.0),
            TimedWord("first", 10.5, 11.0),
            TimedWord("second", 11.2, 12.0),
            TimedWord("after", 45.0, 48.0),
        ]
        # Clip from 10.0 to 40.0
        filtered = filter_and_offset_words(words, clip_start=10.0, clip_duration=30.0)
        self.assertEqual(len(filtered), 2)
        self.assertEqual(filtered[0].text, "first")
        self.assertAlmostEqual(filtered[0].start, 0.5)
        self.assertAlmostEqual(filtered[1].start, 1.2)

    def test_chunk_words(self) -> None:
        words = [TimedWord(f"w{i}", float(i), float(i) + 0.3) for i in range(7)]
        chunks = chunk_words(words, max_words_per_chunk=3)
        self.assertEqual(len(chunks), 3)
        self.assertEqual(len(chunks[0]), 3)
        self.assertEqual(len(chunks[1]), 3)
        self.assertEqual(len(chunks[2]), 1)

    def test_build_ass_subtitles_content(self) -> None:
        words = [
            TimedWord("I'll", 0.0, 0.4),
            TimedWord("be", 0.4, 0.7),
            TimedWord("running", 0.7, 1.2),
            TimedWord("in", 1.2, 1.5),
            TimedWord("Olympics", 1.5, 2.2),
        ]
        style = CaptionStyle(font_size=60)
        ass_content = build_ass_subtitles(words, clip_start=0.0, clip_duration=10.0, style=style)
        self.assertIn("[Script Info]", ass_content)
        self.assertIn("PlayResX: 1080", ass_content)
        self.assertIn("PlayResY: 1920", ass_content)
        self.assertIn("RUNNING", ass_content)
        self.assertIn("OLYMPICS", ass_content)
        # Check neon highlight color
        self.assertIn(r"\c&H0066FF00&", ass_content)

    def test_create_caption_file(self) -> None:
        with TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "captions.ass"
            words = [TimedWord("speed", 0.0, 1.0)]
            res = create_caption_file(out_file, words, clip_start=0.0, clip_duration=5.0)
            self.assertTrue(res.exists())
            self.assertGreater(res.stat().st_size, 50)

    def test_devanagari_hindi_to_roman_captions(self) -> None:
        hindi_data = {
            "words": [
                {"word": "नमस्ते", "start": 0.0, "end": 0.5},
                {"word": "दोस्तों", "start": 0.5, "end": 1.0},
            ]
        }
        words = parse_whisper_result(hindi_data)
        self.assertEqual(len(words), 2)
        self.assertEqual(words[0].text, "namaste")
        self.assertEqual(words[1].text, "doston")

        ass_content = build_ass_subtitles(words, clip_start=0.0, clip_duration=5.0)
        self.assertIn("NAMASTE", ass_content)
        self.assertIn("DOSTON", ass_content)
        # Verify no raw Devanagari Unicode characters exist in the output subtitles
        self.assertFalse(any("\u0900" <= ch <= "\u097f" for ch in ass_content))


if __name__ == "__main__":
    unittest.main()

