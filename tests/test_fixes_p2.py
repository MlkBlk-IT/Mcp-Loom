"""Regression tests: passthrough, truncated ids, datetime invariants, score-based facts, number cap."""
import re

from loom import anchors, compress, server
from loom.profile import PROFILES


def test_datetime_digits_are_not_number_invariants():
    text = "[2026-10-24 09:12:03] INFO ok 2026-10-15T17:03:55.218Z latency 87 ms"
    nums = [i.value for i in anchors.extract(text) if i.kind == "number"]
    assert nums == ["87"]


def test_plain_numbers_still_extracted():
    nums = {i.value for i in anchors.extract("retries 3 timeout 30 ratio 0.5") if i.kind == "number"}
    assert {"3", "30", "0.5"} <= nums


def test_facts_selected_by_score_not_position():
    lines = [f"tests/m.py::t{i} PASSED" for i in range(80)]
    lines.append("tests/m.py::t_bad FAILED")
    lines.append("=== 1 failed, 80 passed ===")
    anchor, _ = compress.build_anchor("\n".join(lines), PROFILES["strict"])
    assert "t_bad FAILED" in anchor
    assert "1 failed" in anchor


def test_numbers_capped_in_anchor():
    content = "\n".join(f"value {1000 + i} warning" for i in range(300))
    anchor, _ = compress.build_anchor(content, PROFILES["strict"])
    assert len(re.findall(r"^- \[number\]", anchor, re.M)) <= compress.MAX_NUMBERS_IN_ANCHOR


def test_small_content_is_passthrough(tmp_path, monkeypatch):
    monkeypatch.setattr("loom.store.DB_PATH", tmp_path / "t.db", raising=False)
    content = "short log line 1\nshort log line 2 exit code 0\n"
    res = server._store_impl(content, session_id="t_pass", label="x")
    assert res["passthrough"] is True
    assert res["anchor"] == content
    assert res["saved_ratio"] == 0.0
    assert res["tokens_after"] == res["tokens_before"]


def test_chunk_ids_truncated_for_big_content(tmp_path, monkeypatch):
    monkeypatch.setattr("loom.store.DB_PATH", tmp_path / "t.db", raising=False)
    content = "\n".join(f"line {i} error path D:\\x\\f{i}.log" for i in range(2000))
    res = server._store_impl(content, session_id="t_ids", label="x")
    assert res["chunk_ids_truncated"] is True
    assert len(res["chunk_ids"]) == server.MAX_IDS_IN_RESPONSE
    assert res["chunk_id_last"] - res["chunk_id_first"] + 1 == res["chunk_count"]
