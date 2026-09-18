#!/usr/bin/env python3
"""Render the README demo GIFs from real command output.

Why this exists instead of a terminal-recording tool: `vhs` 0.12 does not produce a file in
this environment (it reports success and writes nothing), and a recorder would capture whatever
happened to be on screen. This runs the actual commands, captures their actual stdout, and draws
it into frames. Same input, same GIF, every time, and no tool in the loop that can silently
produce a blank result.

    python3 demos/make_gifs.py            # all three
    python3 demos/make_gifs.py compact    # one

Requires Pillow (system python3 has it) and the repository's own `lcc` on PATH.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "demos"

FONT_PATH = "/System/Library/Fonts/Menlo.ttc"
FONT_SIZE = 13

# Canvas and palette. Sized so the longest demo line fits without wrapping.
WIDTH, HEIGHT = 1040, 600
BAR_HEIGHT = 30
PAD = 14
LINE_H = 17
#: Lines shown per output block before the rest is elided. Enough to show the shape of an
#: output, small enough that a two-command demo fits with both commands in view.
OUTPUT_BLOCK_LINES = 13
BG = (30, 30, 46)
BAR = (24, 24, 37)
FG = (205, 214, 244)
DIM = (147, 153, 178)
PROMPT = (166, 227, 161)
ACCENT = (137, 180, 250)
WARN = (249, 226, 175)
DOTS = ((243, 139, 168), (249, 226, 175), (166, 227, 161))

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def font(size: int = FONT_SIZE) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, size)


def run(cmd: list[str]) -> str:
    """Run a real command and return its combined, ANSI-stripped output."""
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=180)
    return ANSI_RE.sub("", (proc.stdout or "") + (proc.stderr or "")).rstrip("\n")


def wrap(text: str, width_chars: int) -> list[str]:
    out: list[str] = []
    for line in text.split("\n"):
        if len(line) <= width_chars:
            out.append(line)
            continue
        current = ""
        for word in line.split(" "):
            candidate = f"{current} {word}".strip()
            if len(candidate) <= width_chars:
                current = candidate
            else:
                out.append(current)
                current = word
        if current:
            out.append(current)
    return out


def draw_terminal(history: list[tuple[str, str]], title: str) -> Image.Image:
    """One frame: a window bar, then the accumulated transcript.

    ``history`` entries are ``("prompt", command)`` or ``("out", text)``.
    """
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, WIDTH, BAR_HEIGHT], fill=BAR)
    for index, colour in enumerate(DOTS):
        x = PAD + index * 18
        draw.ellipse([x, 10, x + 10, 20], fill=colour)
    draw.text((WIDTH // 2, BAR_HEIGHT // 2), title, font=font(12), fill=DIM, anchor="mm")

    y = BAR_HEIGHT + PAD
    body_font = font()
    lines: list[tuple[str, str]] = []
    for kind, text in history:
        if kind == "prompt":
            # Commands wrap too, indented under the prompt, so a long invocation is never
            # sliced at the right edge. A clipped command is worse than a wrapped one.
            for index, part in enumerate(wrap(text, 116)):
                lines.append(("prompt" if index == 0 else "cont", part))
        else:
            wrapped = wrap(text, 118)
            # Each block shows its head; the point of the demo is the shape of the output,
            # not every line of it, and a shorter block keeps the commands in view.
            if len(wrapped) > OUTPUT_BLOCK_LINES:
                kept = wrapped[: OUTPUT_BLOCK_LINES]
                kept.append(f"  … {len(wrapped) - OUTPUT_BLOCK_LINES} more lines …")
                wrapped = kept
            for line in wrapped:
                lines.append(("out", line))

    budget = (HEIGHT - BAR_HEIGHT - 2 * PAD) // LINE_H
    if len(lines) > budget:
        # Elide the middle and keep the order. Hoisting the commands to the top was tried and
        # it reads as a transcript that never happened: the commands end up before outputs they
        # produced. Keeping head and tail preserves cause and effect.
        head_keep = max(1, budget // 2)
        tail_keep = max(1, budget - head_keep - 1)
        if head_keep + tail_keep >= len(lines):
            lines = lines[:budget]
        else:
            elided = len(lines) - head_keep - tail_keep
            marker = ("out", f"  … {elided} lines elided …")
            lines = [*lines[:head_keep], marker, *lines[len(lines) - tail_keep :]]

    for kind, text in lines:
        if kind == "prompt":
            draw.text((PAD, y), "$", font=body_font, fill=PROMPT)
            draw.text((PAD + 14, y), text, font=body_font, fill=FG)
        elif kind == "cont":
            draw.text((PAD + 14, y), text, font=body_font, fill=FG)
        else:
            colour = DIM
            if "warning:" in text or "cache_epoch_risk" in text:
                colour = WARN
            elif "Reduction" in text or "Token savings" in text or "Dropped" in text:
                colour = ACCENT
            draw.text((PAD, y), text, font=body_font, fill=colour)
        y += LINE_H
    return image


def frames_for(script: list[tuple[str, str | None]], title: str) -> list[tuple[Image.Image, int]]:
    """Turn ``[(command, output_or_None), ...]`` into (frame, duration_ms) pairs."""
    frames: list[tuple[Image.Image, int]] = []
    history: list[tuple[str, str]] = []
    for command, output in script:
        # Typing: reveal the command in thirds, then a beat before Enter.
        for cut in (len(command) // 3, 2 * len(command) // 3, len(command)):
            frames.append((draw_terminal([*history, ("prompt", command[:cut])], title), 45))
        frames.append((draw_terminal([*history, ("prompt", command)], title), 220))
        if output is not None:
            history.append(("prompt", command))
            history.append(("out", output))
            # The output lands all at once, with a short beat before it appears.
            frames.append((draw_terminal(history[:-1], title), 180))
            frames.append((draw_terminal(history, title), 2600))
        else:
            history.append(("prompt", command))
    return frames


def build(name: str, script: list[tuple[str, str | None]], title: str) -> None:
    frames = frames_for(script, title)
    images = [frame for frame, _ in frames]
    durations = [duration for _, duration in frames]
    dest = OUT / f"{name}.gif"
    images[0].save(
        dest,
        save_all=True,
        append_images=images[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    size_kb = dest.stat().st_size / 1024
    # Report what the file holds, not what went in: optimize=True merges identical frames, so
    # the saved count is lower than len(images) and the difference is not a bug to chase.
    with Image.open(dest) as saved:
        frame_count = getattr(saved, "n_frames", len(images))
    print(f"{dest.relative_to(ROOT)}  {frame_count} frames  {size_kb:.0f} kB")


def demo_compact() -> None:
    objective = "What is wrong with the booking operation?"
    script = [
        ("# 23 blocks from a real dossier: a stable prefix, tool output, logs, chatter", None),
        (
            f"lcc compact demos/compact-dossier.md -q '{objective}' "
            "--provider mechanical -o /tmp/lcc-demo.md -r /tmp/lcc-demo.json",
            run([
                "lcc", "compact", "demos/compact-dossier.md", "-q", objective,
                "--provider", "mechanical", "-o", "/tmp/lcc-demo.md", "-r", "/tmp/lcc-demo.json",
            ]),
        ),
        ("# Every decision is recorded, with the reason behind it", None),
        (
            "lcc explain /tmp/lcc-demo.json --source demos/compact-dossier.md "
            "--only drop --limit 3",
            run([
                "lcc", "explain", "/tmp/lcc-demo.json",
                "--source", "demos/compact-dossier.md", "--only", "drop", "--limit", "3",
            ]),
        ),
    ]
    build("compact", script, "lcc compact — relevance compaction, offline")


def demo_compile() -> None:
    script = [
        (
            "# A brief dumped from three places: repeated paragraphs, page markers, "
            "a signature",
            None,
        ),
        (
            "lcc optimize demos/messy-brief.md -q 'What should we change about the checkout?' "
            "--template claude_xml -o /tmp/lcc-compiled.md -r /tmp/lcc-compiled.json",
            run([
                "lcc", "optimize", "demos/messy-brief.md",
                "-q", "What should we change about the checkout?",
                "--template", "claude_xml",
                "-o", "/tmp/lcc-compiled.md", "-r", "/tmp/lcc-compiled.json",
            ]),
        ),
        (
            "# Nothing is summarised or rewritten. Redundant text is removed, and the "
            "report says what",
            run(["python3", "demos/cleaning_steps.py", "/tmp/lcc-compiled.json"]),
        ),
        ("# And the head of the compiled prompt",
         run(["head", "-n", "14", "/tmp/lcc-compiled.md"])),
    ]
    build("compile", script, "lcc optimize — raw brief to compiled prompt")


def demo_audio() -> None:
    script = [
        ("# What a Whisper capture actually looks like: fillers, [Music], a subtitle credit", None),
        (
            "head -n 9 demos/audio-transcript.txt",
            run(["head", "-n", "9", "demos/audio-transcript.txt"]),
        ),
        ("# lcc detects the transcript, cleans it, and compiles a prompt from it",
         run([
             "lcc", "intake", "demos/audio-transcript.txt",
             "-q", "What is the checkout plan?", "--template", "claude_xml",
             "-o", "/tmp/lcc-from-audio.md",
         ])),
        ("# The cleaned context that came out of the audio",
         run([
             "bash", "-c",
             "sed -n '/<context>/,/<\\/context>/p' /tmp/lcc-from-audio.md | head -12",
         ])),
    ]
    build("audio-to-prompt", script, "lcc intake — voice transcript to structured prompt")


DEMOS = {"compact": demo_compact, "compile": demo_compile, "audio": demo_audio}


def main() -> None:
    wanted = sys.argv[1:] or list(DEMOS)
    for name in wanted:
        if name not in DEMOS:
            raise SystemExit(f"unknown demo {name!r}; expected one of {', '.join(DEMOS)}")
        DEMOS[name]()


if __name__ == "__main__":
    main()
