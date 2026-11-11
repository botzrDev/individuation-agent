# Review checklist (before this repo goes public)

## Cross-model review rule

The paper's pre-submission gate requires an independent review by a model that is **not** from the same family as the author. This code was written with Claude. The reviewer must therefore be a non-Claude model (or a human). The review covers: correctness against `schemas/` and the P1 spec, the append-only guarantee, the honesty states, and the sensitivity list below.

## Sensitivity list (must not appear in code, docs, examples, or sample data)

- API key paths and decryption mechanisms
- Counterparty names from the obligations register
- Business pricing numbers
- KNOWN_ABSENT entries from the memory audit (the mechanism may be described; the data may not)
- Linear team prefixes and workspace structure
- Specific hook DENY surfaces

Fair to describe: the instrument architecture, evidence tiers, gate structure, ratchet mechanisms, failure modes.

## Review focus (behaviours the plan's tests pin; re-check them by reading)

1. A `defer` proposal on an item at `defer_count == 3` is rejected with `blocked_by = "max_defer"` (`tests/test_governance.py::test_fourth_defer_rejected_max_defer`).
2. Malformed S3 JSON, or a proposal naming an unknown `probe_id`, a bad action, or a duplicate target, is dropped and S3 is recorded at tier UNKNOWN; nothing raises (`tests/test_synthesis.py::test_unknown_target_dropped`, `test_malformed_json_yields_empty_unknown_s3`, `test_duplicate_targets_keep_first_only`).
6. A deferred item carries forward with its `probe_id` and `defer_count`; the fourth defer is rejected at the graph level, not only in the governance unit (`tests/test_graph.py::test_deferred_item_carries_forward_and_hits_max_defer`).
7. Every row the store writes validates against its schema as the raw dict on disk (`tests/test_persistence.py`).
8. A `resolve`/`revise` proposal without a valid `new_atom` is rejected with `blocked_by = "new_atom_invalid"`; the model's rationale is never written as an identity fact (`tests/test_governance.py::test_resolve_without_valid_new_atom_rejected`).
3. One detector raising does not stop the others; the raiser is reported UNKNOWN (`tests/test_shadow.py::test_run_detectors_marks_raiser_unknown_and_continues`).
4. `consult()` by the authoring session does not set `last_read` (`tests/test_store.py`).
5. A persona with empty `capability_bounds` makes the tool-registry source BLIND, not OK with zero (`tests/test_shadow.py`).

## Other things to check

- No em dashes anywhere in the repo (substrate convention).
- `ai-use-log.md` has an entry for every task.
- Repo is still PRIVATE: `gh repo view botzrDev/individuation-agent --json visibility`.
- All six schemas in `schemas/` are byte-identical to the vault's `P1-formalize/04-schemas/`.
- Run a demo cycle and validate every persisted JSONL row against its schema (`tests/test_persistence.py` does this; re-run it against `runs/demo.jsonl` too).
- Cycle-authored atoms (Stage 3 proposals, Stage 4 appends) are never above tier INFERRED; contradiction items carry the weakest tier of the two atoms. An agent's direct transcription of a source's statement (the lab's `memory_append`) is REPORTED by design: that is the tier for an unverified assertion by a source, and only `memory_verify` against a mounted artifact raises it to VERIFIED.
- The severity enum value `KNOWN_ABSENT` in `schemas/shadow-item.schema.json` and `models.py` is the mechanism, not audit data; the sensitivity list allows it.
- An S3 record with no proposals and nothing dropped is tier VERIFIED (it asserts only that nothing was proposed); the reconcile verdict is PASS or UNKNOWN, never FAIL, because the precedence relation is total. Both rules are documented at the code.
