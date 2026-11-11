# individuation-agent

Reference implementation of the four-stage individuation cycle (Persona Recognition, Shadow Confrontation, Anima/Animus Integration, Self-Reorganization) as a LangGraph graph over an append-only atom store. Every state change is a new atom with an evidence tier; nothing is edited in place. The package exists so the architecture paper describes a system that runs, not a hypothesis.

**Status: released 2026-11-11 (v0.1.0).** This is the reference implementation described in the paper *Reflective Identity Optimization: A Cognitive Architecture for Persistent Agent Identity over Append-Only Memory* (Zenodo, [doi:10.5281/zenodo.24145069](https://doi.org/10.5281/zenodo.24145069)). The implementation passed an independent cross-model review by a non-Claude model on 2026-11-08; see `ai-use-log.md`.

## Install

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```
uv sync --group dev
uv run pytest
```

## Demo (no provider call)

```
uv run individuation-agent demo --store runs/demo.jsonl --fake
uv run individuation-agent show --store runs/demo.jsonl
```

`demo` seeds the store with two conflicting identity atoms and one tool call, then runs one cycle with a scripted model that resolves the first contradiction. `show` prints the Stage 4 record. Without `--fake` it uses `langchain_anthropic.ChatAnthropic` and needs `ANTHROPIC_API_KEY`.

## Case study (five cycles, optional live model)

```
uv run python examples/case_study.py --fake                      # scripted model, no spend
uv run python examples/case_study.py --model claude-sonnet-5-5   # needs ANTHROPIC_API_KEY
```

Seeds a synthetic ten-session history (a role contradiction, a recurring error, two bound tools never called, a live obligation, a self-imposed constraint), runs five cycles, breaches the obligation before cycle 2 and discharges it before cycle 3, and writes `docs/case-study/trace.json` and `trace.md`. It is qualitative: it shows a Stage 3 proposal being accepted and governance refusing, and computes no `S_c`. `tests/test_case_study.py` pins the scripted run.

## Layout

- `src/individuation_agent/` the package
- `schemas/` the six JSON Schema 2020-12 contracts for the inter-stage messages (copied verbatim from the paper's P1 formalization; do not edit here)
- `tests/`
- `docs/` architecture notes, the mapping back to the paper, and the review checklist
- `ai-use-log.md` the per-repo AI-use disclosure log
