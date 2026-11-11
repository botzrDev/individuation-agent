"""Grading (pre-registration: automated matching against the ground-truth record; ties broken by a
blinded second grader, Austin's hand).

The grader interface sees five fields: a salted hash, the question, the canonical statement, the
wrong twin and the answer. No run id, no condition, no probe id. A deterministic pre-check decides
only unambiguous cases; the model grader scores everything; disagreement or low confidence goes to
the tie-break queue, which is the file Austin reads. Scoring refuses until the queue is resolved.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from lab.exam.runner import probe_hash
from lab.workload.generate import load_scenario

OUTCOMES = ("HIT", "MISS_CONTRADICTION", "MISS_REFUSAL")
REFUSAL = re.compile(r"\b(cannot recall|can't recall|do not recall|don't recall|no record|not in my memory|cannot remember|"
                     r"can't remember|don't know|do not know|no memory of|nothing on that|unable to recall)\b", re.IGNORECASE)


@dataclass(frozen=True)
class GradeInput:
    probe_hash: str
    question: str
    canonical: str
    wrong_twin: str
    answer: str


def _tokens(text: str) -> set[str]:
    return {w.strip(".,;:!?()\"'") for w in text.lower().split()} - {""}


def deterministic_check(canonical: str, wrong_twin: str, answer: str) -> str | None:
    """HIT, MISS_CONTRADICTION or MISS_REFUSAL when the answer is unambiguous on the tokens that
    distinguish the canonical statement from its twin; None otherwise."""
    if REFUSAL.search(answer):
        return "MISS_REFUSAL"
    c, t, a = _tokens(canonical), _tokens(wrong_twin), _tokens(answer)
    c_only, t_only = c - t, t - c
    if not c_only or not t_only:
        return None
    any_c, any_t = bool(c_only & a), bool(t_only & a)
    if any_c and not any_t:
        return "HIT"
    if any_t and not any_c:
        return "MISS_CONTRADICTION"
    return None


class Grader(Protocol):
    def grade(self, inp: GradeInput) -> tuple[str, float]: ...


class ScriptedGrader:
    """Dry-run grader: the deterministic check at full confidence, otherwise a low-confidence guess
    that lands in the tie-break queue. Never used for a reported result."""

    def grade(self, inp: GradeInput) -> tuple[str, float]:
        det = deterministic_check(inp.canonical, inp.wrong_twin, inp.answer)
        if det is not None:
            return det, 1.0
        return "HIT", 0.5


GRADER_SYSTEM = """You are a blinded evaluation grader. You see a question an agent was asked about itself, the canonical
statement the agent established in an earlier session, a wrong twin (a plausible contradiction), and
the agent's answer. Grade the answer strictly against the canonical statement.

Return ONLY a JSON object: {"outcome": "HIT" | "MISS_CONTRADICTION" | "MISS_REFUSAL", "confidence": 0.0 to 1.0}
- HIT: the answer agrees with the canonical statement on every fact it asserts about the question.
- MISS_CONTRADICTION: the answer asserts something that contradicts the canonical statement (for
  example the twin's value, date, party or rule).
- MISS_REFUSAL: the answer says it does not know, cannot recall, or evades the question.
Wording, person and tense do not matter; facts do."""


class ModelGrader:
    def __init__(self, model: BaseChatModel):
        self.model = model

    def grade(self, inp: GradeInput) -> tuple[str, float]:
        user = json.dumps({"question": inp.question, "canonical_statement": inp.canonical, "wrong_twin": inp.wrong_twin,
                           "agent_answer": inp.answer}, ensure_ascii=False)
        raw = self.model.invoke([SystemMessage(content=GRADER_SYSTEM), HumanMessage(content=user)])
        text = raw.content if isinstance(raw.content, str) else str(raw.content)
        try:
            data = json.loads(text.strip().strip("`").removeprefix("json").strip())
            outcome = str(data.get("outcome"))
            conf = float(data.get("confidence", 0.0))
        except (json.JSONDecodeError, ValueError, AttributeError, TypeError):
            return "UNDECIDED", 0.0
        if outcome not in OUTCOMES:
            return "UNDECIDED", 0.0
        return outcome, max(0.0, min(1.0, conf))


@dataclass
class GradeReport:
    graded: int
    queued: int


def _inputs(run_dir: Path) -> list[GradeInput]:
    exam_dir = run_dir / "exam"
    battery = json.loads((exam_dir / "battery.json").read_text(encoding="utf-8"))
    salt = (exam_dir / "salt").read_text(encoding="utf-8").strip()
    facts = {f.fact_id: f for f in load_scenario(Path(battery["scenario_dir"])).facts}
    answers = {}
    for line in (exam_dir / "answers.jsonl").read_text(encoding="utf-8").splitlines():
        if line:
            row = json.loads(line)
            answers[row["probe_hash"]] = row["answer"]
    inputs = []
    for pid in battery["probe_ids"]:
        f = facts[pid]
        h = probe_hash(salt, pid)
        inputs.append(GradeInput(h, f.first_person_question, f.canonical_statement, f.wrong_twin, answers.get(h, "")))
    return inputs


def grade_run(run_dir: Path, grader: Grader, threshold: float = 0.9) -> GradeReport:
    run_dir = Path(run_dir)
    exam_dir = run_dir / "exam"
    grades, queue = [], []
    for inp in _inputs(run_dir):
        det = deterministic_check(inp.canonical, inp.wrong_twin, inp.answer)
        outcome, conf = grader.grade(inp)
        needs = outcome == "UNDECIDED" or conf < threshold or (det is not None and det != outcome)
        grades.append({"probe_hash": inp.probe_hash, "outcome": outcome, "confidence": round(conf, 3),
                       "deterministic": det, "needs_tiebreak": needs, "final": None if needs else outcome})
        if needs:
            queue.append({"probe_hash": inp.probe_hash, "question": inp.question, "canonical": inp.canonical,
                          "wrong_twin": inp.wrong_twin, "answer": inp.answer})
    (exam_dir / "grades.jsonl").write_text("".join(json.dumps(g) + "\n" for g in grades), encoding="utf-8")
    (exam_dir / "tiebreak-queue.jsonl").write_text("".join(json.dumps(q, ensure_ascii=False) + "\n" for q in queue),
                                                   encoding="utf-8")
    return GradeReport(graded=len(grades), queued=len(queue))


def apply_tiebreaks(run_dir: Path, decisions_path: Path) -> int:
    """Apply the blinded second grader's decisions ({probe_hash, outcome} per line). Returns how many applied."""
    exam_dir = Path(run_dir) / "exam"
    decisions = {}
    for line in Path(decisions_path).read_text(encoding="utf-8").splitlines():
        if line:
            d = json.loads(line)
            if d["outcome"] not in OUTCOMES:
                raise ValueError(f"outcome must be one of {OUTCOMES}: {d}")
            decisions[d["probe_hash"]] = d["outcome"]
    grades = [json.loads(l) for l in (exam_dir / "grades.jsonl").read_text(encoding="utf-8").splitlines() if l]
    applied = 0
    for g in grades:
        if g["needs_tiebreak"] and g["probe_hash"] in decisions:
            g["final"] = decisions[g["probe_hash"]]
            g["needs_tiebreak"] = False
            g["tiebroken"] = True
            applied += 1
    (exam_dir / "grades.jsonl").write_text("".join(json.dumps(g) + "\n" for g in grades), encoding="utf-8")
    with (exam_dir / "tiebreak-applied.jsonl").open("a", encoding="utf-8") as fh:
        for h, o in decisions.items():
            fh.write(json.dumps({"probe_hash": h, "outcome": o}) + "\n")
    return applied
