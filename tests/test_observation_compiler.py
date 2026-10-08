import hashlib
from dataclasses import dataclass

import pytest


@dataclass(frozen=True)
class Scope:
    entity: str = "service-a"
    field: str = "errors"
    start: str = "2027-01-01T12:00:00Z"
    end: str = "2027-01-01T12:05:00Z"


class Engine:
    is_local = True

    def supports_operation(self, operation):
        return operation == "rank_observations"

    def rank_observations(self, scope, blocks):
        return {
            "schema": "lcc-observation-ranking/0.1",
            "operation": "rank_observations",
            "is_local": True,
            "items": [
                {
                    "id": b["id"],
                    "text_sha256": hashlib.sha256(b["text"].encode()).hexdigest(),
                    "status": "NO_MATCH" if "unrelated" in b["text"] else "UNKNOWN",
                    "decision": "DROP" if "unrelated" in b["text"] else "KEEP",
                }
                for b in blocks
            ],
        }


def test_exact_gaps_and_kept_bytes_survive_selection():
    from lcc.relevance.observations import compact_observations

    first = "opaque observation  " * 8 + "\r\n"
    noise = "unrelated output  " * 8 + "\r\n"
    last = "preserve Unicode ação  " * 8 + "\r\n"
    text = "\r\n" + first + "\r\n\r\n" + noise + "\r\n\r\n" + last + "\r\n"
    result = compact_observations(text, Scope(), engine=Engine())
    assert result.compacted_text == text.replace(noise, "", 1)
    assert result.report["blocks_dropped"] == 1
    assert result.report["necessity_estimated"] is False


@pytest.mark.parametrize("engine", [None, object()])
def test_missing_runtime_keeps_all(engine):
    from lcc.relevance.observations import compact_observations

    text = "unrelated output " * 20
    result = compact_observations(text, Scope(), engine=engine)
    assert result.compacted_text == text
    assert result.report["degraded"] is True


def test_nonlocal_client_is_not_called():
    from lcc.relevance.observations import compact_observations

    class Remote(Engine):
        is_local = False

        def rank_observations(self, *args):
            raise AssertionError("Must not send context to remote client")

    text = "unrelated output " * 20
    assert compact_observations(text, Scope(), engine=Remote()).compacted_text == text


@pytest.mark.parametrize("change", ["hash", "id", "unknown_drop", "duplicates"])
def test_invalid_response_preserves_every_block(change):
    from lcc.relevance.observations import compact_observations

    class Broken(Engine):
        def rank_observations(self, scope, blocks):
            result = super().rank_observations(scope, blocks)
            item = result["items"][0]
            if change == "hash":
                item["text_sha256"] = "wrong"
            if change == "id":
                item["id"] = "wrong"
            if change == "unknown_drop":
                item["status"] = "UNKNOWN"
            if change == "duplicates":
                result["items"].append(item)
            return result

    text = "unrelated output " * 20
    result = compact_observations(text, Scope(), engine=Broken())
    assert result.compacted_text == text
    assert result.report["degradation_reason"] == "invalid_observation_response"


def test_short_and_prefix_blocks_are_protected():
    from lcc.relevance.observations import compact_observations

    prefix = "unrelated stable prefix " * 10
    text = prefix + "\n\nshort unrelated\n\n" + "unrelated output " * 20
    result = compact_observations(text, Scope(), engine=Engine(), protect_prefix_chars=len(prefix))
    assert prefix in result.compacted_text and "short unrelated" in result.compacted_text
    assert result.report["blocks_dropped"] == 1


@pytest.mark.parametrize("scope,max_chars", [("general diagnosis", 6000), (Scope(), 0)])
def test_invalid_scope_or_limits_reject_before_parsing(scope, max_chars):
    from lcc.relevance.observations import compact_observations

    with pytest.raises(ValueError):
        compact_observations("x", scope, engine=Engine(), max_block_chars=max_chars)
