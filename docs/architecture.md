# Architecture

## Module map

| Module | Responsibility | Paper component |
| -- | -- | -- |
| `models.py` | Pydantic models for the atom envelope, Shadow items, S1 to S4 messages, and the typed component atoms; `validate_against_schema` proves them against `schemas/` | all |
| `store.py` | `AtomStore`: append-only JSONL; `append`, `supersede`, `mark_superseded`, `consult`, `get`, `all`, `latest` | memory substrate (property set P: append-only, source-attributed, recall-measured) |
| `checks.py` | `evaluate(check, text, store)` over the constraints-register check vocabulary, plus the id-based `cites_evidence` kind | constraint-bound |
| `artifacts.py` | `ArtifactMount`, `verify_atom`, `audit_verified`: a claim is checked against the far-side file it names and stamped VERIFIED with its hash | verified against the artifact |
| `gate.py` | `session_close_gate` (fails closed on stale or expired atoms, flags diary), `require_gate_pass`, `acknowledge` | freshness-gated; recall-measured |
| `reconcile.py` | `Ledger`, `reconcile`: precedence relation between the atom store and a user-owned ledger; conflicts resolved by appending and reported | reconciled across stores |
| `registers.py` | `PersonaRegister`, `ArchetypeTable` (YAML-loaded, read-only in a cycle) | Persona; Archetypes |
| `shadow.py` | four `ShadowDetector`s and `run_detectors` (BLIND / UNKNOWN reporting) | Shadow; Collective Unconscious (hook) |
| `synthesis.py`, `prompts.py` | `Synthesizer`: one call under the complementary cognitive mode, JSON proposals, tier inheritance | Anima/Animus |
| `governance.py` | `Governance.filter`: constraint, obligation, reconcile verdicts; `max_defer` | governance inside S4 |
| `reorganize.py` | `apply`: accepted proposals become appended atoms; targets are superseded with a resolution | Self (state update) |
| `graph.py` | `CycleState`, `CycleDeps`, four node functions, `build_graph` | the four-stage cycle |
| `agent.py` | `IndividuationAgent.run_cycle`, `should_cycle` default policy | cycle trigger |
| `fakes.py` | `ScriptedModel`, demo seed and deps; no provider calls | test support |
| `cli.py` | `demo`, `show` | |

## The graph

```
START -> recognize -> probe -> synthesize -> reorganize -> END
           S1          S2         S3            S4
```

- `recognize` routes the context through the Archetype Table, resolves a persona, appends S1.
- `probe` runs every detector, appends each Shadow item, appends S2 with per-source reports.
- `synthesize` calls the model once under the opposite cognitive mode, appends S3.
- `reorganize` filters proposals through governance, applies the accepted ones, computes Es, appends S4.

Dependencies travel in `config["configurable"]["deps"]` (a `CycleDeps`), so node functions are plain functions of state.

## Append-only rules

1. No code path rewrites or deletes a line of the store file. Tests assert the first bytes of the file are unchanged after every mutating operation.
2. A change is a new atom whose `supersedes` names the old one; the old atom is re-appended with `status: superseded`.
3. `last_read` is derived from `ego.consult` atoms written by sessions other than the author's (the recall-meter CONSULT rule).
4. Every atom carries `tier` and `status`. S3 proposals inherit the weakest tier of the items they synthesize; S4 carries S3's tier.

## Honesty states

- A detector that cannot see reports `BLIND`; one that raises is reported `UNKNOWN`; neither is ever `OK` with zero findings by accident.
- Governance verdicts are `PASS | FAIL | UNKNOWN`; a crash in a check is `UNKNOWN`, never `PASS`. `UNKNOWN` is recorded, not treated as a rejection.
