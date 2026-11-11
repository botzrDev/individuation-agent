"""The probe pool and the battery draw (pre-registration: 60 drawn without replacement from a pool of at
least 300, 15 per category, each from a session at least 24 hours before the evaluation session)."""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from lab.workload.generate import Fact, load_scenario

CATEGORIES = ("identity_fact", "decision", "commitment", "preference")
PER_CATEGORY = 15
MIN_POOL = 300


class EligibilityError(ValueError):
    """Too few probes old enough for the draw."""


@dataclass(frozen=True)
class Probe:
    probe_id: str
    category: str
    component: tuple[str, ...]
    session_index: int
    turn_id: str
    first_person_question: str
    canonical_statement: str
    wrong_twin: str
    established_at: datetime  # wall-clock time of the establishing user turn in this run


def _establishing_times(run_dir: Path) -> dict[tuple[int, str], datetime]:
    out: dict[tuple[int, str], datetime] = {}
    for p in sorted((run_dir / "transcripts").glob("s*.jsonl")):
        index = int(p.stem[1:])
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            row = json.loads(line)
            if row.get("role") == "user" and row.get("turn_id"):
                out[(index, row["turn_id"])] = datetime.fromisoformat(row["at"])
    return out


def build_pool(scenario_dir: Path, run_dir: Path) -> list[Probe]:
    sc = load_scenario(Path(scenario_dir))
    times = _establishing_times(Path(run_dir))
    pool = []
    for f in sc.facts:
        assert isinstance(f, Fact)
        when = times.get((f.session_index, f.turn_id))
        if when is None:
            raise ValueError(f"no establishing turn in the run transcripts for {f.fact_id}")
        pool.append(Probe(f.fact_id, f.category, tuple(f.component), f.session_index, f.turn_id, f.first_person_question,
                          f.canonical_statement, f.wrong_twin, when))
    if len(pool) < MIN_POOL:
        raise ValueError(f"pool has {len(pool)} probes; the pre-registration requires at least {MIN_POOL}")
    return pool


def draw_seed(run_id: str, scenario_sha: str) -> int:
    return int(hashlib.sha256(f"{run_id}:{scenario_sha}".encode("utf-8")).hexdigest()[:16], 16)


def draw_battery(pool: list[Probe], run_id: str, scenario_sha: str, eval_time: datetime,
                 min_age: timedelta = timedelta(hours=24), per_category: int = PER_CATEGORY) -> list[Probe]:
    """Stratified draw without replacement, reproducible from the run id and the scenario hash."""
    rng = random.Random(draw_seed(run_id, scenario_sha))
    drawn: list[Probe] = []
    for cat in CATEGORIES:
        eligible = sorted((p for p in pool if p.category == cat and p.established_at + min_age <= eval_time),
                          key=lambda p: p.probe_id)
        if len(eligible) < per_category:
            raise EligibilityError(f"category {cat}: {len(eligible)} probes at least {min_age} old; need {per_category}")
        drawn.extend(rng.sample(eligible, per_category))
    rng.shuffle(drawn)
    return drawn
