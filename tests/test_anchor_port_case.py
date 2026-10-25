"""Regression: the port invariant is case-insensitive on the word 'port' only."""
from loom import anchors


def _kinds(text):
    return {(i.kind, i.value) for i in anchors.extract(text)}


def test_port_uppercase_assignment_is_a_port_invariant():
    assert ("port", "PORT = 8765") in _kinds("PORT = 8765")


def test_port_mixed_case_and_colon():
    assert ("port", "Port: 3000") in _kinds("listening, Port: 3000")


def test_port_lowercase_unchanged():
    assert ("port", "port 8080") in _kinds("bind on port 8080 now")


def test_port_not_matched_inside_longer_words():
    kinds = _kinds("REPORT 12 and support 80 and Transport 443")
    assert not any(kind == "port" for kind, _ in kinds)


def test_port_out_of_range_rejected():
    assert not any(kind == "port" for kind, _ in _kinds("PORT = 99999"))


def test_other_casing_rules_untouched():
    kinds = _kinds("HOME_DIR=/x ERROR happened")
    assert ("env_var", "HOME_DIR") in kinds
    assert not any(v == "ERROR" for k, v in kinds if k == "env_var")
