from individuation_agent.checks import evaluate
from individuation_agent.models import Check


def test_text_forbidden_fails_on_match():
    chk = Check(kind="text_forbidden", patterns=[r"\bCritical\b", r"\b9\.8\b"])
    assert evaluate(chk, "this is a Critical issue") == "FAIL"


def test_text_forbidden_passes_when_clean():
    chk = Check(kind="text_forbidden", patterns=[r"\bCritical\b"])
    assert evaluate(chk, "this is a routine issue") == "PASS"


def test_pattern_passes_on_match():
    chk = Check(kind="pattern", patterns=["security", "policy"])
    assert evaluate(chk, "user asked about security") == "PASS"
    assert evaluate(chk, "user asked about lunch") == "FAIL"


def test_manual_is_unknown():
    assert evaluate(Check(kind="manual"), "anything") == "UNKNOWN"


def test_lint_tool_is_unknown_in_p2a():
    assert evaluate(Check(kind="lint_tool", tool="emdash_lint.py"), "anything") == "UNKNOWN"
    assert evaluate(Check(kind="live_text", url="https://example.invalid", text="x"), "anything") == "UNKNOWN"


def test_bad_regex_is_unknown():
    assert evaluate(Check(kind="pattern", patterns=["("]), "anything") == "UNKNOWN"
