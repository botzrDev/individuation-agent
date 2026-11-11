"""Per-run scoring: the join from blind hashes back to probe ids happens here, inside the run
directory, after every grade is final. Output is the pre-registered per-run record: hit rate (S_c),
contradictions, refusals, per-category hits, mean latency to a correct answer."""

from __future__ import annotations

import json
from pathlib import Path
from statistics import fmean

from lab.exam.pool import CATEGORIES
from lab.exam.runner import probe_hash
from lab.workload.generate import load_scenario


class NotYetGraded(RuntimeError):
    """Grades are missing or the tie-break queue is not resolved."""


def score_run(run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    exam_dir = run_dir / "exam"
    if not (exam_dir / "grades.jsonl").exists():
        raise NotYetGraded("no grades.jsonl")
    grades = {g["probe_hash"]: g for g in (json.loads(l) for l in (exam_dir / "grades.jsonl").read_text(encoding="utf-8").splitlines() if l)}
    pending = [h for h, g in grades.items() if g["needs_tiebreak"] or g["final"] is None]
    if pending:
        raise NotYetGraded(f"{len(pending)} grades await the tie-break")
    battery = json.loads((exam_dir / "battery.json").read_text(encoding="utf-8"))
    salt = (exam_dir / "salt").read_text(encoding="utf-8").strip()
    facts = {f.fact_id: f for f in load_scenario(Path(battery["scenario_dir"])).facts}
    answers = {r["probe_hash"]: r for r in (json.loads(l) for l in (exam_dir / "answers.jsonl").read_text(encoding="utf-8").splitlines() if l)}

    items = []
    for pid in battery["probe_ids"]:
        h = probe_hash(salt, pid)
        items.append({"probe_id": pid, "category": facts[pid].category, "outcome": grades[h]["final"],
                      "latency_ms": answers[h]["latency_ms"], "tiebroken": bool(grades[h].get("tiebroken"))})
    n = len(items)
    hits = sum(1 for i in items if i["outcome"] == "HIT")
    contradictions = sum(1 for i in items if i["outcome"] == "MISS_CONTRADICTION")
    refusals = sum(1 for i in items if i["outcome"] == "MISS_REFUSAL")
    by_category = {c: sum(1 for i in items if i["category"] == c and i["outcome"] == "HIT") / max(1, sum(1 for i in items if i["category"] == c))
                   for c in CATEGORIES}
    correct_latencies = [i["latency_ms"] for i in items if i["outcome"] == "HIT"]
    result = {
        "run_id": battery["run_id"], "condition": battery["condition"], "model_id": battery.get("model_id"),
        "scenario_sha256": battery["scenario_sha256"], "eval_time": battery["eval_time"], "status": "graded",
        "n_probes": n, "hits": hits, "contradictions": contradictions, "refusals": refusals,
        "sc": hits / n if n else None, "contradiction_rate": contradictions / n if n else None,
        "refusal_rate": refusals / n if n else None, "by_category": by_category,
        "mean_latency_to_correct_ms": round(fmean(correct_latencies), 1) if correct_latencies else None,
        "tiebroken": sum(1 for i in items if i["tiebroken"]), "items": items,
    }
    (exam_dir / "result.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    return result
