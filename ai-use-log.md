# AI-use log: individuation-agent

Per-repo disclosure log, required by the paper's pre-submission gate. One entry per task or notable change. Author of record for all commits: Phillip Austin Green. The AI assistant drafts; a human reviews before anything leaves the private repo.

| Date | Tool | Model family | What the AI did | Human check |
| -- | -- | -- | -- | -- |
| 2026-11-03 | Claude Code (session "Steve") | Claude (Anthropic) | Wrote the P2a implementation plan from the P1 specs; scaffolded the repo (pyproject, pins, schema copy, first test) | Austin chose framework (LangGraph), repo location/visibility, execution mode; plan on file for his review |
| 2026-11-03 | Claude Code ("Steve") | Claude | Task 2: pydantic models + schema validation with cross-file $ref; found and fixed the envelope `kind` pattern defect in the P1 schema (digits) | Ruling recorded in the SDD ledger and on the P1 issue on the project board |
| 2026-11-03 | Claude Code ("Steve") | Claude | Task 3: append-only JSONL AtomStore (append, supersede, consult, latest, all) | tests watched RED then GREEN; ruling on supersede link direction in ledger |
| 2026-11-03 | Claude Code ("Steve") | Claude | Task 4: check evaluator (constraints-register vocabulary), PersonaRegister, ArchetypeTable with YAML loaders | tests watched RED then GREEN |
| 2026-11-03 | Claude Code ("Steve") | Claude | Task 5: four Shadow detectors + run_detectors with BLIND/UNKNOWN reports; typed IdentityAtom/ErrorAtom/ToolCallAtom | tests watched RED then GREEN; store-test fixtures renamed off the newly typed kinds |
| 2026-11-03 | Claude Code ("Steve") | Claude | Task 6: S3 synthesizer over BaseChatModel with JSON parsing, target filtering, tier inheritance, UNKNOWN on malformed output | tests on FakeListChatModel watched RED then GREEN |
| 2026-11-03 | Claude Code ("Steve") | Claude | Task 7: governance filter (constraint, obligation, reconcile stub, max_defer) and S4 reorganization; ConstraintAtom/ObligationAtom; AtomStore.mark_superseded | tests watched RED then GREEN |
| 2026-11-03 | Claude Code ("Steve") | Claude | Task 8: four-stage cycle as a LangGraph StateGraph; IndividuationAgent with default should_cycle policy; Es computed in S4 | tests on a scripted chat model watched RED then GREEN; config annotation fix after first run |
| 2026-11-03 | Claude Code ("Steve") | Claude | Task 9: demo CLI (`demo`, `show`), fakes module (ScriptedModel, demo seed), docs (architecture, paper mapping, review checklist) | first demo run recorded below; tests watched RED then GREEN |

## First demo run (fake model, 2026-11-04 UTC)

`individuation-agent demo --store runs/demo.jsonl --fake` -> `probed=2 accepted=1 rejected=0 es=0.5`

S4 excerpt from `show`:

```json
{"kind": "self.stage_record", "tier": "VERIFIED",
 "accepted": [{"action": "resolve"}], "rejected": [],
 "governance": {"constraint_check": "PASS", "obligation_check": "PASS", "reconcile": "PASS"},
 "es": 0.5}
```

Note (2026-11-08, cross-model review finding 9): this excerpt is from the first build. The current build records this S4 at tier INFERRED, because the accepted resolve is model-authored over a REPORTED input. The excerpt stays as the historical record.
| 2026-11-04 | Claude Code ("Steve") | Claude | Whole-branch review by a fresh Claude reviewer (2 Critical, 10 Important, minors); one fix pass: shared row serializer + persisted-row validation, Shadow item carry-forward so max_defer fires in the cycle, never-called semantics for unused tools, tier cap at INFERRED for model-authored atoms, new_atom validation, duplicate-target dedupe, live-only obligations, references on resolving atoms, list-content message text, docs scrubbed of tracker ids | each fix has a test watched RED then GREEN; minors deferred and listed in the SDD ledger |
| 2026-11-05 | Claude Code ("Steve") | Claude | Case-study harness `examples/case_study.py` (synthetic ten-session history, five cycles, obligation breach and discharge interventions, JSON and Markdown trace) plus `tests/test_case_study.py`; `runs/` ignored wholesale. Built after an external reviewer asked for a real-model trace; the real-model run is a separate entry | Austin chose to run it live; dry run reviewed; the open-item probing discrepancy it surfaced is logged on the project board for his decision |
| 2026-11-05 | Claude Code ("Steve") | Claude | Live case-study run: five cycles on claude-sonnet-5-5 over the synthetic history (API key loaded for the one process from a file outside the repo; never written anywhere); trace committed to docs/case-study/; harness reporting fixed (pre-cycle defer counts, defer rendering) and a --from-store re-render added so the trace is reproducible from the store without a model call | Austin authorized the spend and reviews the trace; the evidence-constraint blocks and the blind-spot non-revisit are reported as found |
| 2026-11-05 | Claude Code ("Steve") | Claude | Open-item probing rule (Austin's ruling): run_detectors now carries every open item into the probe set, test-first (78 tests); shadow.py docstring and docs/paper-mapping.md updated; first live trace renamed trace-refound-only.*; case study re-run on claude-sonnet-5-5 under the new rule (the carried blind spot was resolved in cycle 3) | Austin chose the rule from three options; authorized the spend; reviews both traces |
| 2026-11-05 | Claude Code ("Steve") | Claude | Eight-property closure for the P2b lab, test-first: artifacts.py (verify against mounted artifacts, audit), gate.py (session-close freshness gate, fail closed, diary flag), reconcile.py (user-owned ledger, precedence relation, governance verdict computed), AtomStore(validate=True), cites_evidence check kind; S1 schema enum extended (vault copy identical); docs updated; 109 tests | Austin decided the closure and "start the build" from options; reviews the four commits |
| 2026-11-08 | Claude Code ("Steve") | Claude | Cross-model review packet prepared for the pre-public gate: repo archived at this commit with `git archive`, paired with `docs/review-checklist.md`, a reviewer prompt and the paper PDF; no code change | Austin runs the review on a non-Claude model; findings come back as a response document before any fix is applied |
| 2026-11-08 | Claude Code ("Steve") | Claude | Cross-model review (Beam Free, non-Claude; verdict PASS WITH FIXES, nine findings) applied per Austin: checks.evaluate reports UNKNOWN on any exception, test-first (156 tests); reconcile verdict, idle-S3 tier and the REPORTED-transcription rule documented at the code, in the checklist, the lab README and paper-mapping; this log annotated (finding 9). Response document in the vault review packet | Austin chose "apply all as recommended" over implementing new code paths for findings 1, 3, 5, 7; reviews the diff |
| 2026-11-11 | Claude Code ("Steve") | Claude | Release preparation: README status line for v0.1.0; sensitivity grep over tracked files (two fixes: the workload test now checks real organization names by SHA-256 digest instead of listing them; local paths and a collaborator's name removed from the P2a plan); published as a fresh single-commit public repository at Austin's decision, the development history staying private | Austin chose the clean-history release |
