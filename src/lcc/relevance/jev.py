"""Opt-in TypeSafe System One ("Jev") client for relevance compaction (ADR 0013).

This module is the only place in ``lcc.relevance`` that may touch the network, and it is
only reachable when the caller explicitly opts in (``--provider jev``/``auto`` or
``enable_relevance=True``). It uses the standard library only, mirrors the shared TypeSafe
ledger schema used by the LookADev tool fleet, and fails closed: every error path raises a
typed error so the compactor can fall back to a safer behavior.

Key resolution order:
1. ``TYPESAFE_API_KEY`` environment variable
2. ``~/.config/lcc/typesafe.key`` (single line, chmod-friendly)
3. ``<LOOKAORCHESTRATOR>/.env`` (``LCC_LOOKAORCHESTRATOR_DIR`` or ~/Downloads/LOOKAORCHESTRATOR)
4. macOS Keychain (``security find-generic-password -s typesafe -w``)

Kill switch: setting ``LCC_DISABLE_NETWORK=1`` makes ``JevClient.from_env`` return ``None``
without any network activity.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
DEFAULT_FEATURE = "lcc_compact"
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504, 529})
#: TypeSafe System One context window — mirrors ``provider.JevProvider.context_limit``.
#: Above it the API answers ``400 max_tokens_exceeded``. Accepted up to 31.136 input_tokens
#: (measured, ledger 17-21/09); a 123.741-char JSON state was refused there 38 times on 21/09
#: and the API returns no count for what it refuses. Calibrated by 6 API measurements in
#: 2 runs plus 1 live refusal (2026-09-22, resolved ``jev-1.13.0``): ``api = 249 +
#: 0.98 * local`` (prose-JSON, worst slope) and ``api = 437 + 0.90 * local`` (second run
#: combined) — the API never counted more than tiktoken on the payload, so refusing at
#: 32.768 LOCAL tokens lets no over-window request leave (worst fit still projects 32.361
#: at the refusal point). The cost is the band we refuse that the API would take: 1-10% of
#: the window across the three fits. Re-probe
#: ``benchmarks/research/calibrate_preflight_tokens.py`` if TypeSafe changes tokenizer or
#: cap: a slope above 1.0 would invert the safety direction.
JEV_CONTEXT_LIMIT_TOKENS = 32768
#: Undercount of the chars/4 heuristic on JSON-heavy states, as measured in
#: ``transcript._budget_tokens``: without a tokenizer, inflate rather than trust it.
_APPROXIMATE_SAFETY_FACTOR = 1.45


class JevError(RuntimeError):
    """Base error for Jev client failures."""


class JevUnavailableError(JevError):
    """No API key, disabled network, or no reachable endpoint configuration."""


class JevRequestError(JevError):
    """The API answered with a non-retryable error or kept failing after retries."""


class JevMalformedResponseError(JevRequestError):
    """The API answered 200 but the payload was not a usable System One response."""


class JevStateTooLargeError(JevRequestError):
    """The request is over the System One context window.

    Raised *before* the HTTP call: a state the local counter already sees as too big
    would only burn a round trip to be refused with ``400 max_tokens_exceeded``, and
    every caller already fails safe on ``JevError``. Not retryable — retrying the same
    payload cannot make it smaller.
    """


def parse_noul_answer(answer: Any) -> tuple[float | None, float | None, str | None]:
    """Validate one ``noul`` answer. Returns ``(score, confidence, problem)``.

    ``problem`` is None on success; otherwise one of ``missing``, ``wrong_type``,
    ``out_of_range``, ``confidence_missing``, ``confidence_out_of_range``. Scores and
    confidences outside [0, 1] are rejected — a judge that returns 1.7 is not judging
    the 0-1 question it was asked, and the caller must fall back, not clamp.
    """
    if not isinstance(answer, dict):
        return None, None, "missing"
    noul = answer.get("noul")
    if isinstance(noul, bool) or not isinstance(noul, (int, float)):
        return None, None, "missing"
    score = float(noul)
    if not 0.0 <= score <= 1.0:
        return None, None, "out_of_range"
    confidence = answer.get("confidence", None)
    if confidence is None:
        return score, None, "confidence_missing"
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return score, None, "confidence_missing"
    conf = float(confidence)
    if not 0.0 <= conf <= 1.0:
        return score, None, "confidence_out_of_range"
    return score, conf, None


def _lookaorchestrator_dir() -> Path:
    override = os.environ.get("LCC_LOOKAORCHESTRATOR_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / "Downloads" / "LOOKAORCHESTRATOR"


def default_ledger_path() -> Path | None:
    """Shared Jev ledger path when a familiar location exists; ``None`` disables logging."""
    explicit = os.environ.get("LCC_TS_LEDGER")
    if explicit is not None:
        return Path(explicit).expanduser()
    candidate = _lookaorchestrator_dir() / "logs" / "typesafe" / "jev.jsonl"
    if candidate.parent.is_dir():
        return candidate
    return None


def _key_from_env_file(path: Path) -> str | None:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"\s*TYPESAFE_API_KEY\s*=\s*(.*)\s*$", line)
            if match:
                value = match.group(1).strip().strip('"').strip("'")
                if value:
                    return value
    except OSError:
        return None
    return None


def _key_from_keychain() -> str | None:
    if sys.platform != "darwin":
        return None
    for service in ("typesafe", "TYPESAFE_API_KEY"):
        try:
            result = subprocess.run(
                ["security", "find-generic-password", "-s", service, "-w"],
                capture_output=True,
                text=True,
                timeout=3,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        value = (result.stdout or "").strip()
        if result.returncode == 0 and value:
            return value
    return None


def resolve_typesafe_key() -> str | None:
    """Resolve the TypeSafe API key from env, config file, repo .env, then Keychain."""
    value = (os.environ.get("TYPESAFE_API_KEY") or "").strip()
    if value:
        return value
    key_env = os.environ.get("LCC_TYPESAFE_KEY_FILE", "~/.config/lcc/typesafe.key")
    key_file = Path(key_env).expanduser()
    if key_file.is_file():
        content = key_file.read_text(encoding="utf-8").strip()
        if content:
            return content
    env_file = _lookaorchestrator_dir() / ".env"
    if env_file.is_file():
        from_file = _key_from_env_file(env_file)
        if from_file:
            return from_file
    return _key_from_keychain()


def _iso_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


def _request_tokens(payload: dict[str, Any]) -> tuple[int, str]:
    """Token count of the whole request as the API will see it, as ``(tokens, method)``.

    Prefers the real tokenizer (tiktoken, when installed): on JSON-heavy states the
    chars/4 heuristic undercounts by roughly a third, which is exactly how a 123.741-char
    state reached the API on 21/09 and came back ``400 max_tokens_exceeded`` 38 times.
    Without a tokenizer, inflate the blended estimate by the measured factor instead of
    trusting it — a false refusal costs one mechanical fallback, a false allowance costs
    a wasted round trip plus a 400. ``lcc.token_budget`` has no dependency on
    ``lcc.relevance``, so this import cannot cycle.
    """
    text = json.dumps(payload, ensure_ascii=False, default=str)
    try:
        from lcc.schemas import TokenCountMethod
        from lcc.token_budget import count_tokens
        from lcc.token_budget.counters import approximate_token_count
    except Exception:  # tokenizer stack unavailable: last-resort chars/4 estimate
        return int(len(text) / 4 * _APPROXIMATE_SAFETY_FACTOR), "chars/4"
    try:
        counted = count_tokens(text, "gpt-4.1")
        if counted.method is TokenCountMethod.EXACT:
            return int(counted.value), "exact"
    except Exception:
        pass
    return int(approximate_token_count(text) * _APPROXIMATE_SAFETY_FACTOR), "approx"


class JevClient:
    """Minimal System One client with retry/backoff and shared-ledger logging."""

    def __init__(
        self,
        api_key: str,
        *,
        endpoint: str = DEFAULT_ENDPOINT,
        model: str = DEFAULT_MODEL,
        timeout: float = 45.0,
        attempts: int = 3,
        ledger_path: Path | None = None,
        feature: str = DEFAULT_FEATURE,
        opener: Any | None = None,
    ) -> None:
        if not api_key:
            raise JevUnavailableError("empty TypeSafe API key")
        self.api_key = api_key
        self.endpoint = endpoint
        self.model = model
        self.timeout = timeout
        self.attempts = max(1, attempts)
        self.ledger_path = ledger_path
        self.feature = feature
        self._opener = opener  # test seam: callable(urlopen_request, timeout=...) -> response
        #: Resolved model version from the last successful response (``model`` field when
        #: the API echoes it, else the requested model). Recorded by benchmarks so a moving
        #: alias like ``jev-latest`` never appears as the only model identifier.
        self.last_resolved_model: str = model

    @classmethod
    def from_env(cls, **kwargs: Any) -> JevClient | None:
        """Build a client from the environment, or return ``None`` when unavailable."""
        if os.environ.get("LCC_DISABLE_NETWORK") == "1":
            return None
        key = resolve_typesafe_key()
        if not key:
            return None
        endpoint = os.environ.get("TYPESAFE_ENDPOINT", DEFAULT_ENDPOINT)
        model = os.environ.get("TYPESAFE_MODEL", DEFAULT_MODEL)
        return cls(key, endpoint=endpoint, model=model, **kwargs)

    # -- ledger ---------------------------------------------------------------
    def _ledger_append(self, entry: dict[str, Any]) -> None:
        if self.ledger_path is None:
            return
        with contextlib.suppress(OSError):  # ledger logging must never break compaction
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.ledger_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # -- transport ------------------------------------------------------------
    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        opener = self._opener or urllib.request.urlopen
        if self._opener is None:
            # uv-built interpreters ship an empty CA store: without an explicit
            # bundle urlopen raises CERTIFICATE_VERIFY_FAILED whenever SSL_CERT_FILE
            # is not exported (cron/agent shells), which took every remote pass down.
            with opener(request, timeout=self.timeout, context=_ssl_context()) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8"))
        with opener(request, timeout=self.timeout) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))

    def evaluate(self, state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
        """Call System One; retries transient failures; logs every attempt to the ledger."""
        payload = {"model": self.model, "state": state, "questions": questions}
        state_chars = len(json.dumps(state, ensure_ascii=False))
        # Pre-flight: refuse locally what the API would refuse anyway (see JevStateTooLargeError).
        tokens, method = _request_tokens(payload)
        if tokens > JEV_CONTEXT_LIMIT_TOKENS:
            message = (
                f"pre_flight: request is {tokens} tokens ({method}) > "
                f"{JEV_CONTEXT_LIMIT_TOKENS} System One context; state has {state_chars} chars, "
                f"refusing before the call instead of paying for 400 max_tokens_exceeded"
            )
            self._ledger_append(
                {
                    "ts": _iso_timestamp(),
                    "feature": self.feature,
                    "model": self.model,
                    "status": "error",
                    "error": message,
                    "attempt": 1,
                    "latency_ms": 0,
                    "state_chars": state_chars,
                }
            )
            raise JevStateTooLargeError(message)
        last_error: Exception | None = None
        for attempt in range(1, self.attempts + 1):
            started = time.time()
            try:
                data = self._post(payload)
            except urllib.error.HTTPError as exc:  # includes 4xx/5xx
                retryable = exc.code in _RETRYABLE_STATUS
                body = ""
                with contextlib.suppress(Exception):  # best-effort error body
                    body = exc.read().decode("utf-8", errors="replace")[:300]
                self._ledger_append(
                    {
                        "ts": _iso_timestamp(),
                        "feature": self.feature,
                        "model": self.model,
                        "status": "error",
                        "http_status": exc.code,
                        "error": body,
                        "attempt": attempt,
                        "latency_ms": int((time.time() - started) * 1000),
                        "state_chars": state_chars,
                    }
                )
                last_error = JevRequestError(f"TypeSafe API error {exc.code}: {body}")
                if retryable and attempt < self.attempts:
                    time.sleep(1.5 * attempt)
                    continue
                raise last_error from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                self._ledger_append(
                    {
                        "ts": _iso_timestamp(),
                        "feature": self.feature,
                        "model": self.model,
                        "status": "error",
                        "error": f"network: {exc}",
                        "attempt": attempt,
                        "latency_ms": int((time.time() - started) * 1000),
                        "state_chars": state_chars,
                    }
                )
                last_error = JevRequestError(f"network error: {exc}")
                if attempt < self.attempts:
                    time.sleep(1.5 * attempt)
                    continue
                raise last_error from exc

            if not isinstance(data, dict) or not isinstance(data.get("answers"), dict):
                self._ledger_append(
                    {
                        "ts": _iso_timestamp(),
                        "feature": self.feature,
                        "model": self.model,
                        "status": "error",
                        "error": "malformed_response: missing 'answers' mapping",
                        "attempt": attempt,
                        "latency_ms": int((time.time() - started) * 1000),
                        "state_chars": state_chars,
                    }
                )
                raise JevMalformedResponseError("TypeSafe response has no 'answers' mapping")
            resolved = data.get("model") or data.get("resolved_model") or self.model
            if isinstance(resolved, str) and resolved:
                self.last_resolved_model = resolved
            answers = data.get("answers") or {}
            digest: dict[str, Any] = {}
            for question_id, answer in answers.items():
                qtype = answer.get("type")
                if qtype == "choice":
                    digest[question_id] = {
                        "choice": answer.get("choice"),
                        "confidence": answer.get("confidence"),
                    }
                elif qtype == "score":
                    digest[question_id] = {
                        "score": answer.get("score"),
                        "confidence": answer.get("confidence"),
                    }
                else:
                    digest[question_id] = {"noul": answer.get("noul")}
            usage = data.get("usage") or {}
            self._ledger_append(
                {
                    "ts": _iso_timestamp(),
                    "feature": self.feature,
                    "model": self.model,
                    "resolved_model": self.last_resolved_model,
                    "status": "ok",
                    "latency_ms": int((time.time() - started) * 1000),
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "state_chars": state_chars,
                    "answers": digest,
                    "attempt": attempt,
                }
            )
            return data
        raise last_error or JevRequestError("unknown Jev failure")


def _ssl_context():
    """TLS context for the remote judge.

    uv-built pythons ship an empty CA store, so urlopen fails with
    CERTIFICATE_VERIFY_FAILED ("unable to get local issuer certificate") unless
    SSL_CERT_FILE is exported, which it is not under cron. Prefer certifi's bundle,
    fall back to the interpreter default.
    """
    import ssl

    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001 - certifi is optional
        return ssl.create_default_context()
