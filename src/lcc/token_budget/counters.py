"""Token counting with an exact (tiktoken) path and an honest heuristic fallback.

The exact path runs tiktoken inside a no-network guard (:func:`_no_network_guard`) so an
encoding can only be built from a *local* cache. If tiktoken would fetch encoding assets
over the network, the guard blocks the attempt and counting falls back to an approximate,
clearly labelled estimate. lcc therefore never performs network access during normal
operation, including indirectly through tiktoken (ADR 0005, ADR 0006, ADR 0008).
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Iterator
from typing import Any

from lcc.schemas import TokenCount, TokenCountMethod

try:  # tiktoken is optional; everything degrades gracefully without it (ADR 0005/0006/0008).
    import tiktoken

    _HAS_TIKTOKEN = True
except Exception:  # pragma: no cover - exercised only when tiktoken is absent
    tiktoken = None  # type: ignore[assignment]
    _HAS_TIKTOKEN = False

_DEFAULT_ENCODING = "cl100k_base"

#: Notes recorded on a ``TokenCount`` so a report or warning can explain an approximate
#: result honestly (ADR 0005/0008). Each names a distinct, non-overlapping cause.
_NOTE_TIKTOKEN_MISSING = "tiktoken is not installed; used the heuristic estimator."
_NOTE_NETWORK_BLOCKED = (
    "tiktoken would need to download encoding assets, which lcc blocks to stay offline; "
    "used the heuristic estimator. Pre-cache the tokenizer (for example, set "
    "TIKTOKEN_CACHE_DIR to a populated directory) to enable exact counts."
)


class TokenizerNetworkBlocked(RuntimeError):
    """Raised inside :func:`_no_network_guard` when a tokenizer attempts network access.

    tiktoken downloads encoding assets over HTTP when they are not in its local cache. lcc
    promises no network access during normal operation (ADR 0006/0008), so the guard turns
    any such attempt into this error and the counter degrades to an honest approximate count
    rather than performing a real download.
    """


_GUARD_LOCK = threading.RLock()
_GUARDED_THREADS: dict[int, int] = {}
_GUARD_SAVED_ATTRS: list[tuple[Any, str, bool, Any]] = []


@contextlib.contextmanager
def _no_network_guard() -> Iterator[None]:
    """Temporarily make outbound network calls fail closed for the duration of the block.

    Replaces the HTTP entry points tiktoken can use to fetch encoding assets -- ``requests``
    (its primary path; see ``tiktoken.load.read_file``) and, as a backstop for any other
    client, the socket ``connect`` / ``create_connection`` -- with functions that raise
    :class:`TokenizerNetworkBlocked` on the calling thread. Every patch is restored when all
    guarded threads exit, so nothing leaks outside this block; concurrent threads not performing
    token counting are not blocked (Issue #18, ADR 0006/0008).
    """
    import socket

    targets: list[tuple[Any, str]] = []
    try:
        import requests
        import requests.sessions

        targets.append((requests, "get"))  # tiktoken calls ``requests.get`` directly
        targets.append((requests.sessions.Session, "request"))  # underlies every request
    except Exception:  # pragma: no cover - requests not importable; nothing to patch there
        pass

    targets.append((socket.socket, "connect"))
    targets.append((socket, "create_connection"))

    current_tid = threading.get_ident()

    with _GUARD_LOCK:
        if not _GUARDED_THREADS:
            # First guarded thread: install process-wide hooks that inspect the caller thread.
            for owner, attr in targets:
                has_own = attr in vars(owner)
                original = getattr(owner, attr, None)
                _GUARD_SAVED_ATTRS.append((owner, attr, has_own, original))

                def _make_guarded(orig_func: Any) -> Any:
                    def _guarded(*args: Any, **kwargs: Any) -> Any:
                        with _GUARD_LOCK:
                            is_blocked = threading.get_ident() in _GUARDED_THREADS
                        if is_blocked:
                            raise TokenizerNetworkBlocked(
                                "network access is blocked during token counting"
                            )
                        if orig_func is not None:
                            return orig_func(*args, **kwargs)
                        raise RuntimeError(f"guarded attribute {attr} has no original implementation")

                    return _guarded

                setattr(owner, attr, _make_guarded(original))

        _GUARDED_THREADS[current_tid] = _GUARDED_THREADS.get(current_tid, 0) + 1

    try:
        yield
    finally:
        with _GUARD_LOCK:
            if current_tid in _GUARDED_THREADS:
                _GUARDED_THREADS[current_tid] -= 1
                if _GUARDED_THREADS[current_tid] <= 0:
                    del _GUARDED_THREADS[current_tid]

            if not _GUARDED_THREADS:
                # All guarded threads have exited; restore original methods.
                for owner, attr, has_own, original in reversed(_GUARD_SAVED_ATTRS):
                    if has_own:
                        setattr(owner, attr, original)
                    else:
                        with contextlib.suppress(AttributeError):  # pragma: no cover - defensive
                            delattr(owner, attr)
                _GUARD_SAVED_ATTRS.clear()


def approximate_token_count(text: str) -> int:
    """Estimate a token count without a tokenizer.

    Blends two common heuristics -- roughly 4 characters per token and roughly 0.75 words
    per token -- and averages them. This is a coarse fallback; expect about +/-20-30%
    error versus a real tokenizer. Returns 0 for empty or whitespace-only text.
    """
    if not text.strip():
        return 0
    char_estimate = len(text) / 4.0
    words = len(text.split())
    word_estimate = words / 0.75 if words else 0.0
    estimate = (char_estimate + word_estimate) / 2 if word_estimate else char_estimate
    return max(1, round(estimate))


def _tiktoken_version() -> str | None:
    if not _HAS_TIKTOKEN:
        return None
    try:
        from importlib.metadata import version

        return version("tiktoken")
    except Exception:
        return getattr(tiktoken, "__version__", None)


def tokenizer_identity(model: str | None = None) -> dict[str, Any]:
    """Formal tokenizer identity for reports and cache keys.

    Never implies equivalence across tokenizers: ``tokenizer_id`` binds the concrete
    encoding (or ``heuristic-v1``), and ``exact`` states whether counts from this
    identity are measurements or estimates. Callers must refuse to compare values
    across differing ``tokenizer_id`` without re-counting.
    """
    if not _HAS_TIKTOKEN:
        return {
            "tokenizer": "heuristic",
            "tokenizer_id": "heuristic-v1",
            "tokenizer_version": None,
            "exact": False,
        }
    # Resolve without network: probe which encoding would be used, but never fetch.
    encoding_name: str | None = None
    exact_for_model = False
    try:
        with _no_network_guard():
            if model:
                try:
                    enc = tiktoken.encoding_for_model(model)
                    encoding_name = enc.name
                    exact_for_model = True
                except KeyError:
                    encoding_name = _DEFAULT_ENCODING
            else:
                encoding_name = _DEFAULT_ENCODING
    except TokenizerNetworkBlocked:
        return {
            "tokenizer": "tiktoken-unavailable-offline",
            "tokenizer_id": "heuristic-v1",
            "tokenizer_version": _tiktoken_version(),
            "exact": False,
        }
    except Exception:
        return {
            "tokenizer": "heuristic",
            "tokenizer_id": "heuristic-v1",
            "tokenizer_version": _tiktoken_version(),
            "exact": False,
        }
    return {
        "tokenizer": "tiktoken",
        "tokenizer_id": encoding_name or _DEFAULT_ENCODING,
        "tokenizer_version": _tiktoken_version(),
        "exact": bool(exact_for_model and model),
    }


def tokenizer_identity_for_count(count: TokenCount) -> dict[str, Any]:
    """Identity bound to an actual ``TokenCount`` result (what was really used)."""
    if count.method == TokenCountMethod.EXACT:
        return {
            "tokenizer": count.counter,
            "tokenizer_id": count.encoding or "unknown",
            "tokenizer_version": _tiktoken_version(),
            "exact": True,
        }
    return {
        "tokenizer": count.counter,
        "tokenizer_id": count.encoding or "heuristic-v1",
        "tokenizer_version": _tiktoken_version(),
        "exact": False,
    }
def _resolve_encoding(model: str | None) -> tuple[Any, bool]:
    """Return ``(encoding, is_exact)`` for a model, falling back to the default encoding.

    Loading an encoding may touch the network when its assets are not cached locally; this
    function is always called inside :func:`_no_network_guard`, so such an attempt raises
    :class:`TokenizerNetworkBlocked` for the caller to convert into an approximate count.
    """
    if model:
        try:
            return tiktoken.encoding_for_model(model), True
        except KeyError:
            return tiktoken.get_encoding(_DEFAULT_ENCODING), False
    return tiktoken.get_encoding(_DEFAULT_ENCODING), False


def count_tokens(text: str, model: str | None = None, *, allow_exact: bool = True) -> TokenCount:
    """Count tokens in ``text``, preferring an exact tiktoken count for ``model``.

    The exact path runs entirely inside :func:`_no_network_guard`: if tiktoken can build the
    encoding from its local cache the count is exact; if it would need to download encoding
    assets the guard blocks the attempt and the count falls back to an honest heuristic.
    ``TokenCount.method`` always states whether the result is exact or approximate (ADR 0005),
    and approximate results carry a ``note`` explaining why (ADR 0008). The note distinguishes
    four causes: tiktoken not installed, the model/encoding being unknown, encoding assets
    unavailable offline, and any other tiktoken failure.
    """
    if not (allow_exact and _HAS_TIKTOKEN):
        note = None if _HAS_TIKTOKEN else _NOTE_TIKTOKEN_MISSING
        return TokenCount(
            approximate_token_count(text), TokenCountMethod.APPROXIMATE, "heuristic", None, note
        )

    try:
        with _no_network_guard():
            encoding, is_exact = _resolve_encoding(model)
        value = len(encoding.encode(text))
    except TokenizerNetworkBlocked:
        return TokenCount(
            approximate_token_count(text),
            TokenCountMethod.APPROXIMATE,
            "heuristic",
            None,
            note=_NOTE_NETWORK_BLOCKED,
        )
    except Exception as exc:  # defensive: any other tiktoken or encoding failure
        return TokenCount(
            approximate_token_count(text),
            TokenCountMethod.APPROXIMATE,
            "heuristic",
            None,
            note=f"tiktoken failed ({type(exc).__name__}); used the heuristic estimator.",
        )

    if is_exact:
        return TokenCount(value, TokenCountMethod.EXACT, "tiktoken", encoding.name)
    return TokenCount(
        value,
        TokenCountMethod.APPROXIMATE,
        "tiktoken",
        encoding.name,
        note=(
            f"Model {model!r} has no known tiktoken encoding; counted with "
            f"{encoding.name!r} as a fallback."
        ),
    )
