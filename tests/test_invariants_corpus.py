"""Replay the versioned adversarial corpus through the seven invariants (``tests/invariants.py``).

Needs no dev extra, so every ``pytest`` run checks the corpus and the hash-seed stability.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from invariants import check_transcript, corpus_cases, corpus_digest, load_case


@pytest.fixture(autouse=True)
def _private_stash(tmp_path, monkeypatch):
    monkeypatch.setenv("LCC_STASH_DIR", str(tmp_path / "stash"))


@pytest.mark.parametrize("path", corpus_cases(), ids=lambda p: p.stem)
def test_invariants_hold_on_the_adversarial_corpus(path: Path) -> None:
    check_transcript(*load_case(path))


def test_placeholders_ignore_hash_seed(tmp_path: Path) -> None:
    script = Path(__file__).parent / "invariants.py"
    digests = set()
    for hash_seed in ("0", "1", "4242"):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed,
               "LCC_STASH_DIR": str(tmp_path / f"stash-{hash_seed}"),
               "PYTHONPATH": os.pathsep.join([str(Path(__file__).parents[1] / "src"),
                                              os.environ.get("PYTHONPATH", "")])}
        done = subprocess.run([sys.executable, str(script)], env=env, capture_output=True,
                              text=True, check=True, timeout=300)
        digests.add(done.stdout.strip())
    assert len(digests) == 1
    assert digests == {corpus_digest()}
