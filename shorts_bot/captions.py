from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Viral color palette (ASS format: &HAABBGGRR& where AA is alpha 00=opaque)
NEON_GREEN = "&H0066FF00&"   # Electric Lime/Green (#00FF66 in RGB)
NEON_YELLOW = "&H0000E6FF&"  # Vibrant Electric Yellow (#FFE600 in RGB)
NEON_CYAN = "&H00FFFF00&"    # Electric Cyan (#00FFFF in RGB)
COLOR_WHITE = "&H00FFFFFF&"  # Pure White (#FFFFFF in RGB)
COLOR_BLACK = "&H00000000&"  # Pure Black Outline

DEFAULT_HIGHLIGHT_COLORS = (NEON_GREEN, NEON_YELLOW, NEON_CYAN)

DEVANAGARI_VOWELS = {
    '\u0904': 'e', '\u0905': 'a', '\u0906': 'aa', '\u0907': 'i', '\u0908': 'ee',
    '\u0909': 'u', '\u090a': 'oo', '\u090b': 'ri', '\u090c': 'li', '\u090d': 'e',
    '\u090e': 'e', '\u090f': 'e', '\u0910': 'ai', '\u0911': 'o', '\u0912': 'o',
    '\u0913': 'o', '\u0914': 'au'
}
DEVANAGARI_MATRAS = {
    '\u093e': 'aa', '\u093f': 'i', '\u0940': 'ee', '\u0941': 'u',
    '\u0942': 'oo', '\u0943': 'ri', '\u0944': 'ri', '\u0945': 'e',
    '\u0946': 'e', '\u0947': 'e', '\u0948': 'ai', '\u0949': 'o',
    '\u094a': 'o', '\u094b': 'o', '\u094c': 'au'
}
DEVANAGARI_CONSONANTS = {
    '\u0915': 'k', '\u0916': 'kh', '\u0917': 'g', '\u0918': 'gh', '\u0919': 'ng',
    '\u091a': 'ch', '\u091b': 'chh', '\u091c': 'j', '\u091d': 'jh', '\u091e': 'ny',
    '\u091f': 't', '\u0920': 'th', '\u0921': 'd', '\u0922': 'dh', '\u0923': 'n',
    '\u0924': 't', '\u0925': 'th', '\u0926': 'd', '\u0927': 'dh', '\u0928': 'n',
    '\u0929': 'nn', '\u092a': 'p', '\u092b': 'ph', '\u092c': 'b', '\u092d': 'bh',
    '\u092e': 'm', '\u092f': 'y', '\u0930': 'r', '\u0931': 'rr', '\u0932': 'l',
    '\u0933': 'l', '\u0934': 'll', '\u0935': 'v', '\u0936': 'sh', '\u0937': 'sh',
    '\u0938': 's', '\u0939': 'h',
    '\u0958': 'q', '\u0959': 'kh', '\u095a': 'gh', '\u095b': 'z', '\u095c': 'r',
    '\u095d': 'rh', '\u095e': 'f', '\u095f': 'y'
}
VIRAMA = '\u094d'
NUKTA = '\u093c'
ANUSVARA = '\u0902'
CHANDRABINDU = '\u0901'
VISARGA = '\u0903'


def devanagari_to_roman(text: str) -> str:
    """
    Transliterates Hindi text written in Devanagari script into readable Roman Hindi (Hinglish).
    Leaves English and other scripts unchanged so they render with their original characters.
    """
    if not text or not any('\u0900' <= ch <= '\u097f' for ch in text):
        return text

    res: list[str] = []
    i = 0
    n = len(text)
    word_delims = set(' \t\n\r.,!?;:"\'()[]{}<>-–—/\\|')

    while i < n:
        ch = text[i]
        next_ch = text[i + 1] if i + 1 < n else ''

        if next_ch == NUKTA:
            nukta_map = {
                '\u0915': 'q', '\u0916': 'kh', '\u0917': 'gh',
                '\u091c': 'z', '\u0921': 'r', '\u0922': 'rh', '\u092b': 'f'
            }
            base = nukta_map.get(ch, DEVANAGARI_CONSONANTS.get(ch, ch))
            i += 2
            if i < n and text[i] == VIRAMA:
                res.append(base)
                i += 1
            elif i < n and text[i] in DEVANAGARI_MATRAS:
                res.append(base + DEVANAGARI_MATRAS[text[i]])
                i += 1
            else:
                is_word_end = (i >= n or text[i] in word_delims)
                res.append(base if is_word_end else base + 'a')
            continue

        if ch in DEVANAGARI_VOWELS:
            res.append(DEVANAGARI_VOWELS[ch])
            i += 1
        elif ch in DEVANAGARI_CONSONANTS:
            base = DEVANAGARI_CONSONANTS[ch]
            i += 1
            if i < n and text[i] == VIRAMA:
                res.append(base)
                i += 1
            elif i < n and text[i] in DEVANAGARI_MATRAS:
                res.append(base + DEVANAGARI_MATRAS[text[i]])
                i += 1
            else:
                is_word_end = (i >= n or text[i] in word_delims)
                res.append(base if is_word_end else base + 'a')
        elif ch in DEVANAGARI_MATRAS:
            res.append(DEVANAGARI_MATRAS[ch])
            i += 1
        elif ch in (ANUSVARA, CHANDRABINDU):
            res.append('n')
            i += 1
        elif ch == VISARGA:
            res.append('h')
            i += 1
        elif ch == VIRAMA:
            i += 1
        elif ch in ('\u0964', '\u0965'):
            res.append('.')
            i += 1
        else:
            res.append(ch)
            i += 1

    return ''.join(res)


@dataclass(frozen=True, slots=True)
class TimedWord:
    text: str
    start: float
    end: float


@dataclass(frozen=True, slots=True)
class TimedSegment:
    start: float
    end: float
    text: str
    words: tuple[TimedWord, ...] = ()


@dataclass(frozen=True, slots=True)
class CaptionStyle:
    font_name: str = "Arial"
    font_size: int = 64
    primary_color: str = COLOR_WHITE
    outline_color: str = COLOR_BLACK
    outline_width: int = 5
    shadow_depth: int = 2
    alignment: int = 5  # 5 = Center of screen (y = 960 in 1080x1920)
    margin_v: int = 0
    margin_l: int = 60
    margin_r: int = 60
    highlight_colors: tuple[str, ...] = DEFAULT_HIGHLIGHT_COLORS
    max_words_per_line: int = 3
    max_lines_per_chunk: int = 2


def format_ass_time(seconds: float) -> str:
    """Formats seconds into ASS timestamp format: H:MM:SS.cs"""
    clamped = max(0.0, float(seconds))
    hours = int(clamped // 3600)
    minutes = int((clamped % 3600) // 60)
    secs = int(clamped % 60)
    centis = int(round((clamped - int(clamped)) * 100))
    if centis >= 100:
        secs += 1
        centis = 0
    if secs >= 60:
        minutes += 1
        secs = 0
    if minutes >= 60:
        hours += 1
        minutes = 0
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def parse_whisper_result(
    transcription_data: dict[str, Any] | list[dict[str, Any]] | str,
) -> list[TimedWord]:
    """
    Extracts a flat list of TimedWord from Whisper verbose_json results or transcript string.
    Supports:
    - Groq/OpenAI Whisper dict with 'words' key
    - Groq/OpenAI Whisper dict with 'segments' containing 'words' or just segment text
    - Raw transcript string with timestamps '[0.00-2.50] Hello world'
    """
    words: list[TimedWord] = []

    if isinstance(transcription_data, dict):
        # 1. Direct word list
        raw_words = transcription_data.get("words")
        if isinstance(raw_words, list) and raw_words:
            for item in raw_words:
                text = devanagari_to_roman(str(item.get("word", "")).strip())
                if text:
                    start = float(item.get("start", 0.0) or 0.0)
                    end = float(item.get("end", start + 0.3) or (start + 0.3))
                    words.append(TimedWord(text=text, start=start, end=max(start + 0.05, end)))
            if words:
                return words

        # 2. Segments list
        segments = transcription_data.get("segments")
        if isinstance(segments, list) and segments:
            for seg in segments:
                seg_words = seg.get("words")
                if isinstance(seg_words, list) and seg_words:
                    for item in seg_words:
                        text = devanagari_to_roman(str(item.get("word", "")).strip())
                        if text:
                            start = float(item.get("start", 0.0) or 0.0)
                            end = float(item.get("end", start + 0.3) or (start + 0.3))
                            end_time = max(start + 0.05, end)
                            words.append(TimedWord(text=text, start=start, end=end_time))
                else:
                    # Interpolate segment text across segment duration
                    seg_start = float(seg.get("start", 0.0) or 0.0)
                    seg_end = float(seg.get("end", seg_start + 1.0) or (seg_start + 1.0))
                    text = devanagari_to_roman(str(seg.get("text", "")).strip())
                    tokens = [w for w in text.split() if w]
                    if tokens:
                        total_dur = max(0.2, seg_end - seg_start)
                        word_dur = total_dur / len(tokens)
                        for i, token in enumerate(tokens):
                            w_start = seg_start + (i * word_dur)
                            w_end = w_start + word_dur
                            words.append(TimedWord(text=token, start=w_start, end=w_end))
            if words:
                return words

        # 3. Fallback to text key
        raw_text = devanagari_to_roman(str(transcription_data.get("text", "")).strip())
        if raw_text:
            return _parse_raw_text(raw_text)

    elif isinstance(transcription_data, list):
        for item in transcription_data:
            if isinstance(item, dict):
                w_list = parse_whisper_result(item)
                words.extend(w_list)
        return words

    elif isinstance(transcription_data, str):
        return _parse_raw_text(transcription_data)

    return words


def _parse_raw_text(text: str) -> list[TimedWord]:
    """Parses timestamped text lines like '[1.20-3.45] text' or plain text."""
    words: list[TimedWord] = []
    lines = text.strip().splitlines()
    timestamp_pattern = re.compile(r"^\[(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)\]\s*(.*)$")

    current_time = 0.0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        m = timestamp_pattern.match(line)
        if m:
            start_s = float(m.group(1))
            end_s = float(m.group(2))
            content = devanagari_to_roman(m.group(3).strip())
            tokens = [devanagari_to_roman(t) for t in content.split() if t]
            if tokens:
                duration = max(0.2, end_s - start_s)
                step = duration / len(tokens)
                for i, token in enumerate(tokens):
                    words.append(
                        TimedWord(
                            text=token,
                            start=start_s + (i * step),
                            end=start_s + ((i + 1) * step),
                        )
                    )
            current_time = end_s
        else:
            tokens = [devanagari_to_roman(t) for t in line.split() if t]
            for token in tokens:
                words.append(TimedWord(text=token, start=current_time, end=current_time + 0.35))
                current_time += 0.35
    return words


def filter_and_offset_words(
    words: Sequence[TimedWord],
    clip_start: float,
    clip_duration: float,
) -> list[TimedWord]:
    """
    Extracts words that fall within [clip_start, clip_start + clip_duration]
    and re-indexes their timestamps relative to the start of the short (0.0).
    """
    clip_end = clip_start + clip_duration
    result: list[TimedWord] = []
    for w in words:
        if w.end <= clip_start or w.start >= clip_end:
            continue
        # Clip word boundaries to clip bounds
        rel_start = max(0.0, w.start - clip_start)
        rel_end = min(clip_duration, w.end - clip_start)
        if rel_end > rel_start:
            result.append(TimedWord(text=w.text, start=rel_start, end=rel_end))
    return result


def chunk_words(
    words: Sequence[TimedWord],
    max_words_per_chunk: int = 4,
    max_gap_seconds: float = 0.8,
) -> list[list[TimedWord]]:
    """
    Groups words into short, punchy display chunks.
    Starts a new chunk if:
    - Maximum word count reached (e.g. 3-4 words for fast retention)
    - Significant pause detected between spoken words (> max_gap_seconds)
    """
    if not words:
        return []

    chunks: list[list[TimedWord]] = []
    current_chunk: list[TimedWord] = []

    for w in words:
        if not current_chunk:
            current_chunk.append(w)
            continue

        prev_w = current_chunk[-1]
        gap = w.start - prev_w.end

        if len(current_chunk) >= max_words_per_chunk or gap >= max_gap_seconds:
            chunks.append(current_chunk)
            current_chunk = [w]
        else:
            current_chunk.append(w)

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def build_ass_subtitles(
    words: Sequence[TimedWord],
    clip_start: float = 0.0,
    clip_duration: float = 60.0,
    style: CaptionStyle | None = None,
) -> str:
    """
    Generates ASS subtitle content with viral glowing word highlights matching
    the reference image style.
    """
    if style is None:
        style = CaptionStyle()

    # Offset words relative to short clip start
    clip_words = filter_and_offset_words(words, clip_start=clip_start, clip_duration=clip_duration)
    if not clip_words:
        return ""

    chunks = chunk_words(
        clip_words,
        max_words_per_chunk=style.max_words_per_line * style.max_lines_per_chunk,
    )

    lines: list[str] = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        (
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
            "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
            "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
        ),
        (
            f"Style: Default,{style.font_name},{style.font_size},{style.primary_color},"
            f"&H000000FF,{style.outline_color},&H80000000,1,0,0,0,100,100,1.5,0,1,"
            f"{style.outline_width},{style.shadow_depth},{style.alignment},"
            f"{style.margin_l},{style.margin_r},{style.margin_v},1"
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    color_idx = 0
    num_colors = len(style.highlight_colors) if style.highlight_colors else 1

    for chunk in chunks:
        if not chunk:
            continue
        # Chunk overall duration
        chunk_start = chunk[0].start
        chunk_end = max(chunk_start + 0.3, chunk[-1].end)

        # Build clean uppercase lines for the chunk (e.g. 2 lines of max_words_per_line)
        chunk_texts = [devanagari_to_roman(w.text).upper() for w in chunk]

        # For dynamic karaoke highlighting: emit an event for each active word interval
        # while keeping the full phrase visible!
        for i, active_w in enumerate(chunk):
            w_start = active_w.start
            # Last word holds until chunk_end
            w_end = chunk[i + 1].start if (i + 1 < len(chunk)) else chunk_end
            if w_end <= w_start:
                w_end = w_start + 0.2

            highlight_col = (
                style.highlight_colors[color_idx % num_colors]
                if style.highlight_colors
                else NEON_GREEN
            )
            color_idx += 1

            # Build line text with formatting
            # Break into 2 lines if count exceeds max_words_per_line
            formatted_words: list[str] = []
            for j, _ in enumerate(chunk):
                w_clean = chunk_texts[j]
                if j == i:
                    # Highlighted active word!
                    formatted_words.append(f"{{\\c{highlight_col}}}{w_clean}{{\\c{style.primary_color}}}")
                else:
                    formatted_words.append(w_clean)

            if len(formatted_words) > style.max_words_per_line:
                split_at = style.max_words_per_line
                line1 = " ".join(formatted_words[:split_at])
                line2 = " ".join(formatted_words[split_at:])
                display_text = f"{{\\c{style.primary_color}}}{line1}\\N{line2}"
            else:
                display_text = f"{{\\c{style.primary_color}}}" + " ".join(formatted_words)

            start_str = format_ass_time(w_start)
            end_str = format_ass_time(w_end)
            lines.append(
                f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{display_text}"
            )

    return "\n".join(lines) + "\n"


def create_caption_file(
    output_path: Path,
    words: Sequence[TimedWord],
    clip_start: float = 0.0,
    clip_duration: float = 60.0,
    style: CaptionStyle | None = None,
) -> Path:
    """Generates and writes the ASS subtitle file to disk."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = build_ass_subtitles(
        words=words,
        clip_start=clip_start,
        clip_duration=clip_duration,
        style=style,
    )
    output_path.write_text(content, encoding="utf-8")
    return output_path

