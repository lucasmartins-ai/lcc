"""Opt-in genuine request log: off by default, redacted, never touches outputs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lcc import request_log
from lcc.cli import app
from lcc.mcp_server import handle_message

SECRET_DOSSIER = "ZEBRA-CONTEXT-MARKER the clinic funnel loses users at step two.\n\n" * 3


def _call_compact(question: str, **extra) -> dict:
    resp = handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "compact",
                "arguments": {"text": SECRET_DOSSIER, "question": question, **extra},
            },
        }
    )
    assert resp is not None and "error" not in resp
    return resp


def _entries(log_dir: Path) -> list[dict]:
    path = log_dir / request_log.LOG_FILE
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


@pytest.fixture
def log_dir(tmp_path, monkeypatch) -> Path:
    monkeypatch.delenv(request_log.ENV_FLAG, raising=False)
    monkeypatch.setenv(request_log.ENV_DIR, str(tmp_path / "rl"))
    monkeypatch.setenv(request_log.ENV_SESSION, "session-abc")
    return tmp_path / "rl"


def test_off_by_default_writes_nothing(log_dir, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _call_compact("reduce booking friction")
    assert request_log.log_request("anything") is None
    assert not log_dir.exists()
    assert not (tmp_path / ".lcc").exists()


@pytest.mark.parametrize("value", ["0", "true", "yes", ""])
def test_only_exact_flag_enables(log_dir, monkeypatch, value):
    monkeypatch.setenv(request_log.ENV_FLAG, value)
    request_log.log_request("anything")
    assert not log_dir.exists()


@pytest.mark.parametrize(
    ("raw", "placeholder", "leak"),
    [
        ("summarize /Users/lucas/clients/acme/notes.md please", "<PATH>", "/Users/lucas"),
        ("check ~/secrets/prod.env now", "<PATH>", "prod.env"),
        (r"open C:\Users\bob\file.txt", "<PATH>", "bob"),
        ("look at src/lcc/cli.py", "<PATH>", "cli.py"),
        ("email lucas@lookadev.com about it", "<EMAIL>", "lookadev"),
        ("use sk-proj-AbC123xyz789QWERTY000 key", "<TOKEN>", "AbC123"),
        ("Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig_abc", "<TOKEN>", "eyJhbG"),
        ("api_key=hunter2hunter2", "<TOKEN>", "hunter2"),
        ("ghp_" + "0123456789abcdefghij" "ABCDEFGHIJ012345 leaked", "<TOKEN>", "ghp_"),  # split so secret scanners skip the fake token
        ("deploy to api.internal.acme.io today", "<HOST>", "acme"),
        ("ping 10.0.12.7 first", "<HOST>", "10.0.12.7"),
        ("fetch https://acme.com/x?id=9", "<URL>", "acme.com"),
        ('patient "Maria Souza" blood pressure', "<VALUE>", "Maria"),
        ("record 4815162342 status", "<NUMBER>", "4815162342"),
    ],
)
def test_redaction_replaces_sensitive_spans(raw, placeholder, leak):
    out = request_log.redact(raw)
    assert placeholder in out
    assert leak not in out


def test_redaction_keeps_plain_goal():
    goal = "qual o valor de pressão arterial mais recente and/or trend"
    assert request_log.redact(goal) == goal


def test_ruleset_hash_is_recorded_and_stable(log_dir, monkeypatch):
    monkeypatch.setenv(request_log.ENV_FLAG, "1")
    request_log.log_request("find latest weight")
    [entry] = _entries(log_dir)
    assert entry["redaction_ruleset_sha256"] == request_log.RULESET_SHA256
    assert len(request_log.RULESET_SHA256) == 64


def test_mcp_logs_redacted_goal_without_context(log_dir, monkeypatch):
    monkeypatch.setenv(request_log.ENV_FLAG, "1")
    _call_compact("latest weight for lucas@lookadev.com", field="weight_kg")
    raw = (log_dir / request_log.LOG_FILE).read_text()
    assert "ZEBRA-CONTEXT-MARKER" not in raw
    assert "lucas@lookadev.com" not in raw
    [entry] = _entries(log_dir)
    assert set(entry) == {
        "id",
        "date",
        "goal",
        "language",
        "session",
        "tool",
        "field",
        "lcc_version",
        "redaction_ruleset_sha256",
    }
    assert entry["goal"] == "latest weight for <EMAIL>"
    assert entry["field"] == "weight_kg"
    assert len(entry["date"]) == 10  # UTC date granularity only


def test_field_defaults_to_none_string(log_dir, monkeypatch):
    monkeypatch.setenv(request_log.ENV_FLAG, "1")
    request_log.log_request("find latest weight")
    assert _entries(log_dir)[0]["field"] == "none"


def test_logger_failure_does_not_change_result(log_dir, monkeypatch):
    baseline = _call_compact("reduce booking friction")
    monkeypatch.setenv(request_log.ENV_FLAG, "1")

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(request_log, "_append", boom)
    with pytest.warns(RuntimeWarning, match="disk full"):
        broken = _call_compact("reduce booking friction")
    a = json.loads(baseline["result"]["content"][0]["text"])
    b = json.loads(broken["result"]["content"][0]["text"])
    assert a["compacted_text"] == b["compacted_text"]


def test_enabled_does_not_change_output(log_dir, monkeypatch):
    off = _call_compact("reduce booking friction")
    monkeypatch.setenv(request_log.ENV_FLAG, "1")
    on = _call_compact("reduce booking friction")
    a = json.loads(off["result"]["content"][0]["text"])
    b = json.loads(on["result"]["content"][0]["text"])
    assert a["compacted_text"] == b["compacted_text"]


def test_session_hash_stable_per_salt_and_not_raw():
    h1 = request_log.session_hash("session-abc", b"salt-1")
    assert h1 == request_log.session_hash("session-abc", b"salt-1")
    assert h1 != request_log.session_hash("session-abc", b"salt-2")
    assert "session-abc" not in h1


def test_session_hash_in_entries_uses_workspace_salt(log_dir, monkeypatch):
    monkeypatch.setenv(request_log.ENV_FLAG, "1")
    request_log.log_request("one")
    request_log.log_request("two")
    a, b = _entries(log_dir)
    assert a["session"] == b["session"]
    assert "session-abc" not in json.dumps(a)
    salt = (log_dir / request_log.SALT_FILE).read_bytes()
    assert a["session"] == request_log.session_hash("session-abc", salt)


def test_cli_summary_and_delete(log_dir, monkeypatch):
    monkeypatch.setenv(request_log.ENV_FLAG, "1")
    request_log.log_request("one", language="en")
    request_log.log_request("dois", language="pt")
    first = _entries(log_dir)[0]["id"]
    runner = CliRunner()
    res = runner.invoke(app, ["request-log", "--json"])
    assert res.exit_code == 0, res.output
    summary = json.loads(res.stdout)
    assert summary["total"] == 2
    assert summary["by_language"] == {"en": 1, "pt": 1}
    assert summary["sessions"] == 1
    res = runner.invoke(app, ["request-log", "--delete", first, "--json"])
    assert res.exit_code == 0, res.output
    assert json.loads(res.stdout)["total"] == 1
    assert [e["id"] for e in _entries(log_dir)] != [first]


# --- review fixes: short-goal language, tool provenance, wider redaction ---


@pytest.mark.parametrize(
    ("goal", "lang"),
    [
        ("reduce booking friction", "en"),
        ("what is the latest weight", "en"),
        ("qual o valor de pressão arterial mais recente", "pt"),
        ("reduzir atrito no agendamento", "pt"),
        ("mostrar o último peso do paciente na consulta de hoje", "pt"),
    ],
)
def test_short_goals_get_a_language(log_dir, monkeypatch, goal, lang):
    monkeypatch.setenv(request_log.ENV_FLAG, "1")
    request_log.log_request(goal)
    assert _entries(log_dir)[0]["language"] == lang


def test_short_goal_language_unknown_stays_none():
    assert request_log.detect_language("<PATH> 42") is None


def test_mcp_records_tool_and_field_stays_none(log_dir, monkeypatch):
    monkeypatch.setenv(request_log.ENV_FLAG, "1")
    _call_compact("reduce booking friction")
    [entry] = _entries(log_dir)
    assert entry["tool"] == "mcp:compact"
    assert entry["field"] == "none"


def test_cli_compact_records_tool(log_dir, monkeypatch, tmp_path):
    monkeypatch.setenv(request_log.ENV_FLAG, "1")
    src = tmp_path / "in.txt"
    src.write_text(SECRET_DOSSIER)
    res = CliRunner().invoke(app, ["compact", str(src), "--question", "reduce booking friction"])
    assert res.exit_code == 0, res.output
    [entry] = _entries(log_dir)
    assert entry["tool"] == "cli:compact"
    assert "ZEBRA" not in json.dumps(entry)


@pytest.mark.parametrize(
    ("raw", "placeholder", "leak"),
    [
        ("my password is hunter2", "<TOKEN>", "hunter2"),
        ("senha: hunter2", "<TOKEN>", "hunter2"),
        ("a senha é hunter2 ok", "<TOKEN>", "hunter2"),
        ("chave=abc123xyz", "<TOKEN>", "abc123xyz"),
        ("Authorization: Basic dXNlcjpwYXNz", "<TOKEN>", "dXNlcjpwYXNz"),
        ("token glpat-AbCdEfGh12345678xx", "<TOKEN>", "glpat"),
        ("patient 'Maria Souza' bp", "<VALUE>", "Maria"),
        ("hit localhost:8080 first", "<HOST>", "8080"),
        ("mail lucas@localhost now", "<EMAIL>", "lucas"),
        (r"open \\server\share\notes.txt", "<PATH>", "server"),
        ("ping fe80::1ff:fe23:4567:890a now", "<HOST>", "fe80"),
        ("ping 2001:db8::1 now", "<HOST>", "2001"),
        ("open C:/Users/bob/x.txt", "<PATH>", "C:"),
        # import review: 20-31 char mixed-case tokens, bare "senha <value>", digits glued to letters
        ("key abc_1XyzQWERTyUIOpA2Bc3D4e here", "<TOKEN>", "QWERT"),
        ("use 1a2BCDEFGH3IJK4LMn5op6qR now", "<TOKEN>", "BCDEFGH"),
        ("key abcde_aBcDeFg1HIJKlm2 ok", "<TOKEN>", "aBcDeFg"),
        ("a senha minhasenha2024 ok", "<TOKEN>", "2024"),
        ("PASSWORD abc12345", "<TOKEN>", "abc12345"),
        ("cpf 12345678901Fulano ok", "<NUMBER>", "12345678901"),
        ("tel abc987654321", "<NUMBER>", "987654321"),
    ],
)
def test_redaction_review_gaps(raw, placeholder, leak):
    out = request_log.redact(raw)
    assert placeholder in out
    assert leak not in out


def test_redaction_still_keeps_plain_pt_and_en_goals():
    for goal in ("what's the plan for today", "isn't it the latest", "qual a senha padrão do wifi"):
        out = request_log.redact(goal)
        assert "<VALUE>" not in out, out
    # prose after a secret keyword, CamelCase / snake_case identifiers and short numbers survive
    for goal in ("rotate the token tomorrow", "refactor HttpRequestLoggerFactoryBuilder", "fix test_import_v2_requests_cases", "retry 3 times"):
        assert request_log.redact(goal) == goal, goal
