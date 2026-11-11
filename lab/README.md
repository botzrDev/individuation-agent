# The P2b lab

The isolated sandbox that tests the pre-registered claim (Paper 2's Q1): an agent over the eight-property substrate scores higher on a 60-probe self-model battery than a matched free-form control. The governing documents are the pre-registration (locked, append-only) and the lab plan (`individuation-paper/rebuild/P2b-lab/00-lab-plan.md` in the vault). This directory implements the plan; it imports `individuation_agent` and never forks a stage of it.

## Planes

| Plane | Directory | Status |
| -- | -- | -- |
| 1. Workload: one deterministic scenario, identical bytes for every condition and run | `workload/` | built |
| 2. Condition runner: session driver with per-condition memory tools, cycle hooks, session-close gate | `driver/` | built |
| 3. Blind exam: probe pool from the workload facts, stratified draw, condition-blind grading | `exam/` | built |
| 4. Statistics: refuses to run before 30 + 30 results; Welch's t, d with CI, secondaries with Bonferroni | `stats/` | built |

## Workload

```
uv run python -m lab.workload.generate            # regenerates lab/workload/scenario-v1/
uv run pytest tests/lab                            # the scenario's contract
```

`scenario-v1/` holds `sessions.jsonl` (15 sessions, their turns, mounts and injected faults), `facts.jsonl` (320 facts: category, establishing turn, the user's words, the canonical first-person statement, the wrong twin, the exam question), `mounts/sXX/` (artifact overlays per session; the driver accumulates them) and `manifest.json` with the hash that freezes all of it. Fault seeds: a REPORTED claim in session 4 contradicted by a mounted artifact in session 5; one tool error signature in sessions 7 and 8; a constraint trap in session 11; a ledger edit marking an obligation BREACHED before session 12; a mounted file that changes in session 14 so the freshness gate has something to catch; build-log noise on every turn of sessions 13 to 15.

Everything is synthetic. No real person, client, counterparty, price, key, path or workspace appears, and the test suite greps for the sensitive strings.

## Driver

```
uv run python -m lab.driver.run --condition C_P --out runs/lab/p01 --scripted     # no spend, about five seconds
uv run python -m lab.driver.run --condition C_0 --out runs/lab/c01 --scripted
ANTHROPIC_API_KEY=... uv run python -m lab.driver.run --condition C_P --out runs/lab/p01 --model claude-sonnet-5-5
```

Conditions: `C_P` (eight-property store plus the cycle), `C_S` (the same store with the cycle disabled; the exploratory arm), `C_0` (free-form notes; the matched control). A run directory holds `run.json` (condition, model id, scenario hash, per-session turn counts, provider calls, latency), `transcripts/sXX.jsonl` (every user turn, assistant message, tool call and result, provider call with latency and prompt hash, plus cycle, reconcile and gate rows), and the condition's memory: `store.jsonl`, `ledger.jsonl` and `mounts/` for the P conditions, `notes.md` for the control.

Both conditions get the same system prompt apart from the memory rules, the same twelve task tools, the same user turns (including the ledger notice), and the same memory access pattern: a keyword search returning up to eight hits and an append. The P-agent's search returns live atoms with tiers and records a consult; the control's returns raw note lines, stale or not. Nothing is loaded into context at session start in either condition. The P-agent's constraints register (two rules) is substrate configuration seeded at run start, not a probed fact. Atoms the agent appends are REPORTED: they transcribe what a source said, and only `memory_verify` against a mounted artifact raises one to VERIFIED. The INFERRED cap applies to claims the cycle itself authors in Stage 3 and Stage 4.

The scripted model (`driver/scripted.py`) is plumbing: it stores every item the user asks for, reads and verifies against mounted files when told to, calls the tool a turn names, resolves contradictions by keeping the newer statement, adopts unused tools, and answers exam probes from its first search hit. It proves nothing about the hypothesis.

## Exam

One run is one evaluation session, administered once, at least 24 wall-clock hours after the run's sessions (the draw refuses younger probes; the scripted dry run passes `min_age=timedelta(0)` explicitly).

1. `exam.pool.build_pool` reads the 320 facts and stamps each with the wall-clock time of its establishing user turn in this run's transcripts. `draw_battery` takes 15 per category without replacement, seeded from the run id and the scenario hash, so the draw is reproducible and differs across runs.
2. `exam.runner.run_exam` asks each probe in a fresh context (system prompt plus the question, nothing else) with the condition's memory search as the only tool. Answers are keyed by a salted hash of the probe id; the salt stays in the run directory. Output: `exam/battery.json`, `exam/answers.jsonl`, `exam/transcript.jsonl`.
3. `exam.grade.grade_run` builds five-field blind inputs (hash, question, canonical statement, wrong twin, answer) and runs a deterministic pre-check (decides only when the answer contains the distinguishing tokens of exactly one side, or is a refusal) and the grader. A grade goes to `exam/tiebreak-queue.jsonl` when the grader's confidence is under the threshold, when it disagrees with the pre-check, or when the grader's output could not be parsed. The queue is the file the blinded second grader reads; decisions come back as `{probe_hash, outcome}` lines through `apply_tiebreaks`.
4. `exam.score.score_run` refuses until every grade is final, then joins hashes back to probe ids and writes `exam/result.json`: hits, contradictions, refusals, S_c, per-category hit rates, mean latency to a correct answer.

The `ScriptedGrader` is for dry runs only. Reported results use `ModelGrader` with the grader model fixed at freeze.

## Statistics

```
uv run python -m lab.stats.compile --runs runs/lab --out runs/lab/report
```

`lab/stats/compile.py` reads every run directory under `--runs` (its `run.json` and `exam/result.json`), applies `exclusions.jsonl` (one `{run_id, reason}` per line, decided before scoring), and refuses with `LockedError` unless 30 graded runs per primary condition remain and no complete run is ungraded. Every invocation, refused or compiled, is appended to `stats-invocations.jsonl`; that log ships with the results. When it runs it writes `report.json` and `report.md`: Welch's two-sided t on the 60-probe hit rate, Cohen's d with a seeded bootstrap 95% CI, the pre-registered verdict (d < 0.2 failed; 0.2 to 0.5 inconclusive; d >= 0.5 with p < 0.05 supported), the Bonferroni-corrected secondary family (contradiction rate, latency to a correct answer, four categories), the exclusion appendix, and an exploratory section with no verdict (E_s per cycle; the substrate-without-loop arm). Negative controls are compiled only after the primary report exists.

## Phase A gate: the scripted end-to-end dry run

```
uv run python -m lab.dry_run --runs runs/lab/dry --n 30 --fresh
```

Drives 30 scripted runs per primary condition through exam, grading, a fixed dry-run tie-break rule, scoring, and the compiler; first confirms the compiler refuses on the empty ledger. Takes a few minutes. Its numbers are plumbing, not evidence.

## What must never be run early

The statistics script reads results only when the ledger shows 30 completed runs per primary condition. Running it earlier is a hard error that is itself logged. Sequential analysis would invalidate the pre-registration.
