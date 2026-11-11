"""Plane 4 of the lab: the locked statistics compiler. It refuses until 30 graded runs per primary
condition exist after exclusions, logs every invocation, and then produces exactly the pre-registered
analysis: Welch's t on the 60-probe hit rate, Cohen's d with a 95% CI, the verdict thresholds, the
Bonferroni-corrected secondary family, the exclusion appendix, and a separate, unverdicted exploratory
section for E_s and the substrate-without-loop arm."""

import json
from pathlib import Path

import pytest

from lab.stats.compile import LockedError, compile_report

CATEGORIES = ("identity_fact", "decision", "commitment", "preference")


def make_run(root: Path, run_id: str, condition: str, sc: float, contradiction_rate: float = 0.1, latency: float = 900.0,
             es: list[float] | None = None, graded: bool = True) -> None:
    d = root / run_id
    (d / "exam").mkdir(parents=True, exist_ok=True)
    (d / "run.json").write_text(json.dumps({"run_id": run_id, "condition": condition, "model_id": "m", "status": "complete",
                                            "scenario_sha256": "abc"}), encoding="utf-8")
    if graded:
        hits = round(sc * 60)
        contradictions = round(contradiction_rate * 60)
        (d / "exam" / "result.json").write_text(json.dumps({
            "run_id": run_id, "condition": condition, "status": "graded", "n_probes": 60, "hits": hits,
            "contradictions": contradictions, "refusals": 60 - hits - contradictions, "sc": hits / 60,
            "contradiction_rate": contradictions / 60, "refusal_rate": (60 - hits - contradictions) / 60,
            "by_category": {c: min(1.0, sc + 0.01 * i) for i, c in enumerate(CATEGORIES)},
            "mean_latency_to_correct_ms": latency, "items": [],
        }), encoding="utf-8")
    if es is not None:
        (d / "transcripts").mkdir(exist_ok=True)
        rows = [json.dumps({"role": "cycle", "event": "session_end", "es": v}) for v in es]
        (d / "transcripts" / "s01.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")


def spread(center: float, n: int = 30, width: float = 0.12) -> list[float]:
    """n hit rates around center, deterministic, with real variance."""
    return [max(0.0, min(1.0, center + width * ((i % 7) - 3) / 3)) for i in range(n)]


def populate(root: Path, p_center: float, c_center: float, n_p: int = 30, n_c: int = 30) -> None:
    for i, sc in enumerate(spread(p_center, n_p)):
        make_run(root, f"p{i:02d}", "C_P", sc, contradiction_rate=0.05 + 0.01 * (i % 3), latency=1200.0 + 15 * (i % 6),
                 es=[0.5, 0.25, 1.0])
    for i, sc in enumerate(spread(c_center, n_c)):
        make_run(root, f"c{i:02d}", "C_0", sc, contradiction_rate=0.2 + 0.01 * (i % 3), latency=800.0 + 15 * (i % 6))


def test_refuses_before_thirty_graded_runs_per_condition_and_logs_it(tmp_path):
    populate(tmp_path, 0.8, 0.5, n_p=29)
    with pytest.raises(LockedError):
        compile_report(tmp_path, tmp_path / "report")
    log = [json.loads(l) for l in (tmp_path / "stats-invocations.jsonl").read_text(encoding="utf-8").splitlines() if l]
    assert len(log) == 1 and log[0]["outcome"] == "refused" and log[0]["counts"]["C_P"] == 29
    assert not (tmp_path / "report" / "report.json").exists()


def test_excluded_and_ungraded_runs_do_not_count(tmp_path):
    populate(tmp_path, 0.8, 0.5)
    (tmp_path / "exclusions.jsonl").write_text(json.dumps({"run_id": "p03", "reason": "substrate failure: gate crashed in s09"}) + "\n",
                                               encoding="utf-8")
    with pytest.raises(LockedError):
        compile_report(tmp_path, tmp_path / "report")
    make_run(tmp_path, "p30", "C_P", 0.8)  # replacement run restores n = 30
    report = compile_report(tmp_path, tmp_path / "report")
    assert report["primary"]["n"] == {"C_P": 30, "C_0": 30}
    assert report["exclusions"] == [{"run_id": "p03", "reason": "substrate failure: gate crashed in s09"}]
    populate(tmp_path / "ungraded", 0.8, 0.5)
    make_run(tmp_path / "ungraded", "p31", "C_P", 0.8, graded=False)
    with pytest.raises(LockedError, match="ungraded"):
        compile_report(tmp_path / "ungraded", tmp_path / "ungraded" / "report")


def test_primary_report_supported_when_the_effect_is_large(tmp_path):
    populate(tmp_path, 0.8, 0.5)
    report = compile_report(tmp_path, tmp_path / "report")
    p = report["primary"]
    assert p["test"] == "welch_t_two_sided" and p["outcome_measure"] == "hit_rate_60_probes"
    assert p["cohens_d"] >= 0.5 and p["p_value"] < 0.05
    assert p["d_ci95"][0] <= p["cohens_d"] <= p["d_ci95"][1] and p["d_ci_method"].startswith("bootstrap")
    assert p["verdict"] == "SUPPORTED"
    assert p["mean"]["C_P"] > p["mean"]["C_0"]
    assert json.loads((tmp_path / "report" / "report.json").read_text(encoding="utf-8"))["primary"]["verdict"] == "SUPPORTED"
    log = [json.loads(l) for l in (tmp_path / "stats-invocations.jsonl").read_text(encoding="utf-8").splitlines() if l]
    assert log[-1]["outcome"] == "compiled"


def test_primary_report_fails_the_hypothesis_when_there_is_no_effect_or_the_control_wins(tmp_path):
    populate(tmp_path, 0.6, 0.6)
    assert compile_report(tmp_path, tmp_path / "r1")["primary"]["verdict"] == "HYPOTHESIS_FAILED"
    populate(tmp_path / "rev", 0.5, 0.8)
    rev = compile_report(tmp_path / "rev", tmp_path / "rev" / "r")["primary"]
    assert rev["cohens_d"] < 0 and rev["verdict"] == "HYPOTHESIS_FAILED"


def test_inconclusive_band(tmp_path):
    populate(tmp_path, 0.63, 0.6)
    v = compile_report(tmp_path, tmp_path / "r")["primary"]
    assert 0.2 <= v["cohens_d"] < 0.5 and v["verdict"] == "INCONCLUSIVE"


def test_secondary_family_is_bonferroni_corrected(tmp_path):
    populate(tmp_path, 0.8, 0.5)
    sec = compile_report(tmp_path, tmp_path / "report")["secondary"]
    assert set(sec["tests"]) == {"contradiction_rate", "latency_to_correct_ms", *CATEGORIES}
    assert sec["family_size"] == 6 and sec["correction"] == "bonferroni"
    for t in sec["tests"].values():
        assert t["p_adjusted"] == min(1.0, round(t["p_value"] * 6, 6))
    assert sec["tests"]["contradiction_rate"]["mean"]["C_0"] > sec["tests"]["contradiction_rate"]["mean"]["C_P"]


def test_exploratory_section_is_separate_and_carries_no_verdict(tmp_path):
    populate(tmp_path, 0.8, 0.5)
    for i, sc in enumerate(spread(0.7, 5)):
        make_run(tmp_path, f"s{i:02d}", "C_S", sc)
    report = compile_report(tmp_path, tmp_path / "report")
    ex = report["exploratory"]
    assert ex["not_pre_registered"] is True and "verdict" not in ex
    assert ex["es"]["runs"] == 30 and abs(ex["es"]["mean_per_cycle"] - (0.5 + 0.25 + 1.0) / 3) < 1e-9
    cs = ex["substrate_without_loop"]
    assert cs["n"] == 5 and "d_vs_C_P" in cs and "d_vs_C_0" in cs and "p_value" not in cs
    assert "verdict" not in cs
    md = (tmp_path / "report" / "report.md").read_text(encoding="utf-8")
    assert "not pre-registered" in md and "SUPPORTED" in md and "Exclusions" in md
