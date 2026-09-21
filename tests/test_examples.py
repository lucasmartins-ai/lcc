"""Discoverability examples stay runnable offline (no key, no network, no Laya weights)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(script: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.pop("TYPESAFE_API_KEY", None)  # jev arm must honestly skip
    return subprocess.run(
        [sys.executable, str(ROOT / script)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(ROOT),
        env=env,
    )


def test_compact_providers_example_runs_offline():
    proc = _run("examples/compact_providers.py")
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    for cue in ("mechanical", "laya+mechanical_fallback", "judged",
                "budget:", "skipped: no TYPESAFE_API_KEY", "docs/LAYA.md"):
        assert cue in out, cue


def test_long_session_cache_example_runs_offline():
    proc = _run("examples/long_session_cache.py")
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "reused=1" in out  # sticky decision hit on the repeated noise block
    assert "prefix_untouched=True" in out
    assert '"ok": true' in out


def test_quickstart_exists_and_points_at_real_flags():
    doc = (ROOT / "docs" / "QUICKSTART.md").read_text(encoding="utf-8")
    for cue in ("--provider mechanical", "--provider laya", "--provider jev",
                "--decisions-cache", "--prefix-marker", "--append-to",
                "lcc explain", "docs/LAYA.md", "docs/CACHE_ALIGNMENT.md"):
        assert cue in doc, cue
