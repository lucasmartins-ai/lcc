"""Transcribe the owner's voice memos locally for T candidates. Prints counts only, never text.

Pinned: whisper.cpp `whisper-cli`, ggml-large-v3-turbo + silero v5.1.2 VAD, pt, temperature 0, no
previous-text conditioning. Model hashes are checked before any run. Audio folder is read only.

usage: python transcribe_voice.py AUDIO_DIR [one_file_name]
"""

from __future__ import annotations

import collections
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

MODELS = Path.home() / ".cache" / "whisper.cpp"
PINNED = {
    "ggml-large-v3-turbo.bin": "1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69",
    "ggml-silero-v5.1.2.bin": "29940d98d42b91fbd05ce489f3ecf7c72f0a42f027e4875919a28fb4c04ea2cf",
}
OUT = Path.home() / ".lcc-private" / "intake-distill-v1" / "voice"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def probe_seconds(p: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(r.stdout.strip())


def repeat_ratio(words: list[str], n: int = 4) -> float:
    """Share of 4-grams taken by the most common one; whisper loops push this up."""
    grams = [tuple(words[i : i + n]) for i in range(len(words) - n + 1)]
    if not grams:
        return 0.0
    return collections.Counter(grams).most_common(1)[0][1] / len(grams)


def transcribe(audio: Path, tmp: Path) -> str:
    wav = tmp / "a.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-i",
            str(audio),
            "-ar",
            "16000",
            "-ac",
            "1",
            str(wav),
        ],
        check=True,
        stdin=subprocess.DEVNULL,
    )
    base = tmp / "t"
    base.with_suffix(".txt").unlink(missing_ok=True)  # never read the previous memo's output
    r = subprocess.run(
        [
            "whisper-cli",
            "-m",
            str(MODELS / "ggml-large-v3-turbo.bin"),
            "--vad",
            "-vm",
            str(MODELS / "ggml-silero-v5.1.2.bin"),
            "-l",
            "pt",
            "-tp",
            "0",
            "-mc",
            "0",
            "-np",
            "-otxt",
            "-of",
            str(base),
            "-f",
            str(wav),
        ],  # fmt: skip
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )
    if r.returncode != 0:
        raise RuntimeError(f"whisper-cli exit {r.returncode}, stderr {len(r.stderr)} bytes")
    text = (base.with_suffix(".txt")).read_text(encoding="utf-8")
    return " ".join(line.strip() for line in text.splitlines() if line.strip())


def write_private(path: Path, data: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(data)
    os.replace(tmp, path)


def main() -> None:
    src = Path(sys.argv[1])
    os.umask(0o077)  # whisper-cli's own output file is private too
    for name, want in PINNED.items():
        if sha256(MODELS / name) != want:
            raise SystemExit(f"refused: {name} hash does not match the pin")
    OUT.mkdir(parents=True, exist_ok=True, mode=0o700)
    files = sorted(src.glob("*.m4a")) if len(sys.argv) < 3 else [src / sys.argv[2]]
    manifest_path = OUT / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    with tempfile.TemporaryDirectory(dir=OUT) as t:
        for audio in files:
            key = sha256(audio)
            if key in manifest:  # ponytail: keyed by audio hash, so a rerun skips done files
                continue
            text = transcribe(audio, Path(t))
            write_private(OUT / f"{key}.txt", text)
            words = re.findall(r"\w+", text.lower())
            secs = probe_seconds(audio)
            manifest[key] = {
                "file": audio.name,
                "created": int(audio.stat().st_birthtime),
                "seconds": round(secs, 1),
                "words": len(words),
                "wpm": len(words) / (secs / 60) if secs else 0.0,  # unrounded: flags compare these
                "repeat4": repeat_ratio(words),
            }
            write_private(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=1))
            m = manifest[key]
            print(
                f"{len(manifest):3d} {m['seconds']:7.1f}s words {m['words']:5d} wpm {m['wpm']:6.1f}"
            )


if __name__ == "__main__":
    main()
