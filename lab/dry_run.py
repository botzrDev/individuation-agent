"""Phase A gate: the whole pipeline end to end on the scripted model, zero spend (lab plan section 11).

    uv run python -m lab.dry_run --runs runs/lab/dry --n 30

For each primary condition it drives n scripted runs, administers the exam (with the 24-hour rule
waived explicitly, which is only allowed here), grades with the scripted grader, resolves the
tie-break queue by a fixed dry-run rule (the deterministic pre-check's outcome when it has one,
else MISS_REFUSAL, so the dry run never flatters the agent), scores, and finally invokes the locked
compiler. The numbers mean nothing about the hypothesis: the scripted model is plumbing. What the
gate checks is that every stage runs, every file lands, and the compiler refuses early and compiles
late.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import timedelta
from pathlib import Path

from lab.driver.run import run_condition
from lab.driver.scripted import LabScriptedModel
from lab.exam.grade import ScriptedGrader, apply_tiebreaks, deterministic_check, grade_run
from lab.exam.runner import run_exam
from lab.exam.score import score_run
from lab.stats.compile import LockedError, compile_report


def _resolve_queue_for_dry_run(run_dir: Path) -> int:
    queue_path = run_dir / "exam" / "tiebreak-queue.jsonl"
    decisions = []
    for line in queue_path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        q = json.loads(line)
        det = deterministic_check(q["canonical"], q["wrong_twin"], q["answer"])
        decisions.append({"probe_hash": q["probe_hash"], "outcome": det or "MISS_REFUSAL"})
    path = run_dir / "exam" / "tiebreak-decisions.dry-run.jsonl"
    path.write_text("".join(json.dumps(d) + "\n" for d in decisions), encoding="utf-8")
    return apply_tiebreaks(run_dir, path) if decisions else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", default="runs/lab/dry")
    ap.add_argument("--scenario", default="lab/workload/scenario-v1")
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--conditions", default="C_P,C_0")
    ap.add_argument("--fresh", action="store_true", help="delete the runs directory first")
    args = ap.parse_args(argv)
    root, scenario = Path(args.runs), Path(args.scenario)
    if args.fresh and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()

    # the compiler must refuse on an empty or partial ledger
    try:
        compile_report(root, root / "report")
        print("GATE FAILED: the compiler ran on an incomplete ledger", file=sys.stderr)
        return 1
    except LockedError as e:
        print(f"compiler refused as required: {e}")

    for cond in args.conditions.split(","):
        prefix = {"C_P": "p", "C_0": "c", "C_S": "s"}[cond]
        for i in range(args.n):
            run_dir = root / f"{prefix}{i:02d}"
            if (run_dir / "exam" / "result.json").exists():
                continue
            if run_dir.exists():
                shutil.rmtree(run_dir)
            run_condition(cond, scenario, run_dir, LabScriptedModel(), model_id="scripted")
            run_exam(run_dir, scenario, LabScriptedModel(), model_id="scripted", min_age=timedelta(0))
            report = grade_run(run_dir, ScriptedGrader())
            resolved = _resolve_queue_for_dry_run(run_dir)
            result = score_run(run_dir)
            print(f"{cond} {run_dir.name}: sc={result['sc']:.3f} queued={report.queued} resolved={resolved} "
                  f"({time.perf_counter() - t0:.0f}s)")

    report = compile_report(root, root / "report")
    p = report["primary"]
    print(f"compiled: n={p['n']} verdict={p['verdict']} d={p['cohens_d']:.3f} p={p['p_value']:.3g} "
          f"(scripted model; the numbers are plumbing, not evidence)")
    print(f"report: {root / 'report' / 'report.md'}; invocation log: {root / 'stats-invocations.jsonl'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
