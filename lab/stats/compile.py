"""The locked statistics compiler (lab plan section 10; pre-registration analysis plan).

    uv run python -m lab.stats.compile --runs runs/lab --out runs/lab/report

It refuses to run until the run ledger holds 30 graded runs per primary condition after exclusions.
Every invocation, refused or compiled, is appended to ``<runs>/stats-invocations.jsonl``; that log is
part of the release, because the pre-registration forbids sequential analysis and the log is how a
reader checks that none happened. Exclusions are read from ``<runs>/exclusions.jsonl`` and must have
been decided before scoring (the file carries the reason; the appendix prints it).

Primary: two-sample two-sided Welch's t on the 60-probe hit rate, Cohen's d (pooled SD), a 95% CI on
d by seeded percentile bootstrap, exact p, and the pre-registered verdict. Secondary family with
Bonferroni: contradiction rate, latency to a correct answer, the four categories. Exploratory, in a
separate section with no verdict: E_s per cycle for the P-agent, and the substrate-without-loop arm.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean, variance

from scipy import stats

PRIMARY = ("C_P", "C_0")
REQUIRED_N = 30
ALPHA = 0.05
TARGET_D = 0.5
ABANDON_D = 0.2
CATEGORIES = ("identity_fact", "decision", "commitment", "preference")
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20260925  # the pre-registration's signing date; frozen here, not chosen after the data


class LockedError(RuntimeError):
    """The sample is not complete; no analysis is run."""


# --------------------------------------------------------------------------- ledger


def _load_runs(root: Path) -> tuple[dict[str, list[dict]], list[dict], list[str]]:
    exclusions: list[dict] = []
    ex_path = root / "exclusions.jsonl"
    if ex_path.exists():
        for line in ex_path.read_text(encoding="utf-8").splitlines():
            if line:
                d = json.loads(line)
                exclusions.append({"run_id": d["run_id"], "reason": d["reason"]})
    excluded = {e["run_id"] for e in exclusions}
    by_condition: dict[str, list[dict]] = {}
    ungraded: list[str] = []
    for d in sorted(p for p in root.iterdir() if p.is_dir() and (p / "run.json").exists()):
        manifest = json.loads((d / "run.json").read_text(encoding="utf-8"))
        if manifest.get("status") != "complete" or manifest["run_id"] in excluded:
            continue
        result_path = d / "exam" / "result.json"
        if not result_path.exists():
            ungraded.append(manifest["run_id"])
            continue
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result.get("status") != "graded":
            ungraded.append(manifest["run_id"])
            continue
        result["_dir"] = str(d)
        by_condition.setdefault(manifest["condition"], []).append(result)
    return by_condition, exclusions, ungraded


def _log(root: Path, **row) -> None:
    row.setdefault("at", datetime.now(timezone.utc).isoformat())
    with (root / "stats-invocations.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


# --------------------------------------------------------------------------- statistics


def cohens_d(x: list[float], y: list[float]) -> float:
    nx, ny = len(x), len(y)
    pooled = math.sqrt(((nx - 1) * variance(x) + (ny - 1) * variance(y)) / (nx + ny - 2)) if nx + ny > 2 else 0.0
    return (fmean(x) - fmean(y)) / pooled if pooled > 0 else 0.0


def bootstrap_d_ci(x: list[float], y: list[float], resamples: int = BOOTSTRAP_RESAMPLES, seed: int = BOOTSTRAP_SEED) -> tuple[float, float]:
    rng = random.Random(seed)
    ds = []
    for _ in range(resamples):
        bx = [x[rng.randrange(len(x))] for _ in range(len(x))]
        by = [y[rng.randrange(len(y))] for _ in range(len(y))]
        ds.append(cohens_d(bx, by))
    ds.sort()
    lo = ds[int(0.025 * (resamples - 1))]
    hi = ds[int(0.975 * (resamples - 1))]
    return lo, hi


def welch(x: list[float], y: list[float]) -> dict:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        t, p = stats.ttest_ind(x, y, equal_var=False)
    vx, vy, nx, ny = variance(x), variance(y), len(x), len(y)
    num = (vx / nx + vy / ny) ** 2
    den = (vx / nx) ** 2 / (nx - 1) + (vy / ny) ** 2 / (ny - 1)
    out = {"t": float(t), "p_value": float(p), "df": float(num / den) if den > 0 else float(nx + ny - 2),
           "mean": {"x": fmean(x), "y": fmean(y)}, "sd": {"x": math.sqrt(vx), "y": math.sqrt(vy)}, "cohens_d": cohens_d(x, y)}
    if caught:
        out["warnings"] = sorted({str(w.message) for w in caught})  # recorded in the report, never hidden
    return out


def verdict(d: float, p: float) -> str:
    if d < ABANDON_D:
        return "HYPOTHESIS_FAILED"
    if d < TARGET_D:
        return "INCONCLUSIVE"
    return "SUPPORTED" if p < ALPHA else "INCONCLUSIVE"


# --------------------------------------------------------------------------- exploratory


def _es_values(run_dir: Path) -> list[float]:
    out: list[float] = []
    t = run_dir / "transcripts"
    if not t.is_dir():
        return out
    for p in sorted(t.glob("s*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line:
                row = json.loads(line)
                if row.get("role") == "cycle" and row.get("es") is not None:
                    out.append(float(row["es"]))
    return out


# --------------------------------------------------------------------------- compile


def compile_report(runs_root: Path, out_dir: Path, required_n: int = REQUIRED_N) -> dict:
    runs_root, out_dir = Path(runs_root), Path(out_dir)
    by_condition, exclusions, ungraded = _load_runs(runs_root)
    counts = {c: len(by_condition.get(c, [])) for c in sorted(set(by_condition) | set(PRIMARY))}
    short = {c: required_n - counts.get(c, 0) for c in PRIMARY if counts.get(c, 0) < required_n}
    if short or ungraded:
        reasons = []
        if short:
            reasons.append("short: " + ", ".join(f"{c} needs {n} more" for c, n in short.items()))
        if ungraded:
            reasons.append("ungraded runs present: " + ", ".join(ungraded))
        _log(runs_root, outcome="refused", counts=counts, reason="; ".join(reasons))
        raise LockedError("; ".join(reasons))

    p_runs, c_runs = by_condition["C_P"], by_condition["C_0"]
    x = [r["sc"] for r in p_runs]
    y = [r["sc"] for r in c_runs]
    w = welch(x, y)
    lo, hi = bootstrap_d_ci(x, y)
    primary = {
        "outcome_measure": "hit_rate_60_probes", "test": "welch_t_two_sided", "n": {"C_P": len(x), "C_0": len(y)},
        "mean": {"C_P": w["mean"]["x"], "C_0": w["mean"]["y"]}, "sd": {"C_P": w["sd"]["x"], "C_0": w["sd"]["y"]},
        "t": w["t"], "df": w["df"], "p_value": w["p_value"], "cohens_d": w["cohens_d"], "d_ci95": [lo, hi],
        "d_ci_method": f"bootstrap percentile, {BOOTSTRAP_RESAMPLES} resamples, seed {BOOTSTRAP_SEED}",
        "alpha": ALPHA, "target_d": TARGET_D, "abandon_d": ABANDON_D, "verdict": verdict(w["cohens_d"], w["p_value"]),
    }
    if "warnings" in w:
        primary["warnings"] = w["warnings"]

    family: dict[str, dict] = {}

    def secondary(name: str, px: list[float], cy: list[float]) -> None:
        if len(px) < 2 or len(cy) < 2:
            family[name] = {"n": {"C_P": len(px), "C_0": len(cy)}, "note": "too few values"}
            return
        s = welch(px, cy)
        family[name] = {"n": {"C_P": len(px), "C_0": len(cy)}, "mean": {"C_P": s["mean"]["x"], "C_0": s["mean"]["y"]},
                        "t": s["t"], "p_value": s["p_value"], "cohens_d": s["cohens_d"]}
        if "warnings" in s:
            family[name]["warnings"] = s["warnings"]

    secondary("contradiction_rate", [r["contradiction_rate"] for r in p_runs], [r["contradiction_rate"] for r in c_runs])
    secondary("latency_to_correct_ms",
              [r["mean_latency_to_correct_ms"] for r in p_runs if r.get("mean_latency_to_correct_ms") is not None],
              [r["mean_latency_to_correct_ms"] for r in c_runs if r.get("mean_latency_to_correct_ms") is not None])
    for cat in CATEGORIES:
        secondary(cat, [r["by_category"][cat] for r in p_runs], [r["by_category"][cat] for r in c_runs])
    k = len(family)
    for t in family.values():
        if "p_value" in t:
            t["p_adjusted"] = min(1.0, round(t["p_value"] * k, 6))
    secondary_section = {"family_size": k, "correction": "bonferroni", "tests": family}

    es_runs = [(_es_values(Path(r["_dir"]))) for r in p_runs]
    es_all = [v for vs in es_runs for v in vs]
    exploratory: dict = {
        "not_pre_registered": True,
        "note": "Descriptive only. Nothing here is a test of the pre-registered hypothesis and nothing here carries a verdict.",
        "es": {"runs": sum(1 for vs in es_runs if vs), "cycles": len(es_all),
               "mean_per_cycle": fmean(es_all) if es_all else None},
    }
    s_runs = by_condition.get("C_S", [])
    if s_runs:
        z = [r["sc"] for r in s_runs]
        exploratory["substrate_without_loop"] = {
            "n": len(z), "mean": fmean(z), "sd": math.sqrt(variance(z)) if len(z) > 1 else None,
            "d_vs_C_P": cohens_d(z, x) if len(z) > 1 else None, "d_vs_C_0": cohens_d(z, y) if len(z) > 1 else None,
            "note": "exploratory arm added after pre-registration; reported beside, never inside, the primary comparison",
        }

    report = {
        "compiled_at": datetime.now(timezone.utc).isoformat(), "runs_root": str(runs_root.resolve()), "counts": counts,
        "primary": primary, "secondary": secondary_section, "exclusions": exclusions, "exploratory": exploratory,
        "negative_controls": {"status": "not run", "note": "analysed only after the primary comparison has resolved"},
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    (out_dir / "report.md").write_text(_markdown(report), encoding="utf-8")
    _log(runs_root, outcome="compiled", counts=counts, verdict=primary["verdict"], report=str(out_dir / "report.json"))
    return report


def _markdown(r: dict) -> str:
    p, s, e = r["primary"], r["secondary"], r["exploratory"]
    L = ["# Pre-registered analysis", "", f"Compiled {r['compiled_at']} from `{r['runs_root']}`.", "",
         "## Primary: 60-probe hit rate, P-agent vs matched control", "",
         f"- n: C_P {p['n']['C_P']}, C_0 {p['n']['C_0']}",
         f"- mean (sd): C_P {p['mean']['C_P']:.3f} ({p['sd']['C_P']:.3f}), C_0 {p['mean']['C_0']:.3f} ({p['sd']['C_0']:.3f})",
         f"- Welch's t = {p['t']:.3f}, df = {p['df']:.1f}, p = {p['p_value']:.4g}",
         f"- Cohen's d = {p['cohens_d']:.3f}, 95% CI [{p['d_ci95'][0]:.3f}, {p['d_ci95'][1]:.3f}] ({p['d_ci_method']})",
         f"- Verdict against the pre-registered thresholds (abandon d < {p['abandon_d']}, target d >= {p['target_d']}, alpha {p['alpha']}): **{p['verdict']}**",
         "", f"## Secondary family ({s['family_size']} tests, {s['correction']})", "",
         "| test | n | mean C_P | mean C_0 | d | p | p adjusted |", "| -- | -- | -- | -- | -- | -- | -- |"]
    for name, t in s["tests"].items():
        if "p_value" in t:
            L.append(f"| {name} | {t['n']['C_P']}/{t['n']['C_0']} | {t['mean']['C_P']:.3f} | {t['mean']['C_0']:.3f} | "
                     f"{t['cohens_d']:.3f} | {t['p_value']:.4g} | {t['p_adjusted']:.4g} |")
        else:
            L.append(f"| {name} | {t['n']['C_P']}/{t['n']['C_0']} | | | | | {t.get('note', '')} |")
    L += ["", "## Exclusions", ""]
    L += [f"- {x['run_id']}: {x['reason']}" for x in r["exclusions"]] or ["- none"]
    L += ["", "## Exploratory (not pre-registered; no verdict)", "", f"- {e['note']}",
          f"- E_s: {e['es']['cycles']} cycles over {e['es']['runs']} P-agent runs, mean per cycle "
          f"{e['es']['mean_per_cycle'] if e['es']['mean_per_cycle'] is None else round(e['es']['mean_per_cycle'], 3)}"]
    if "substrate_without_loop" in e:
        c = e["substrate_without_loop"]
        L.append(f"- Substrate without loop (C_S): n {c['n']}, mean {c['mean']:.3f}, d vs C_P "
                 f"{'n/a' if c['d_vs_C_P'] is None else round(c['d_vs_C_P'], 3)}, d vs C_0 "
                 f"{'n/a' if c['d_vs_C_0'] is None else round(c['d_vs_C_0'], 3)}. {c['note']}.")
    L += ["", f"## Negative controls", "", f"- {r['negative_controls']['status']}: {r['negative_controls']['note']}", ""]
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    try:
        report = compile_report(Path(args.runs), Path(args.out))
    except LockedError as e:
        print(f"LOCKED: {e}", file=sys.stderr)
        return 3
    print(f"compiled: verdict {report['primary']['verdict']}, d {report['primary']['cohens_d']:.3f}, p {report['primary']['p_value']:.4g}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
