"""Evaluate a constraints-register ``check`` against a piece of text.

The vocabulary is the substrate's, not ours: ``lint_tool``, ``text_forbidden``,
``pattern``, ``manual``, ``live_text``. P2a wires the two regex kinds; the
others report UNKNOWN rather than pretending to pass. ``cites_evidence`` is
the lab's addition: PASS when the text names an atom id, a probe id or a
session id that exists in the store, so "cite evidence" is checked by
reference rather than by vocabulary.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .models import Check, Verdict

if TYPE_CHECKING:
    from .store import AtomStore

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)


def _any_match(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text) for p in patterns)


def _cites_evidence(text: str, store: AtomStore) -> bool:
    known_ids: set[str] = set()
    sessions: set[str] = set()
    for atom in store.all():
        known_ids.add(str(atom.id))
        probe = getattr(atom, "probe_id", None)
        if probe is not None:
            known_ids.add(str(probe))
        sessions.add(atom.made_in)
    if any(m.group(0).lower() in known_ids for m in _UUID.finditer(text)):
        return True
    # a session id counts only as a whole token, never as a substring of a word
    return any(s and re.search(rf"(?<![\w:]){re.escape(s)}(?![\w:])", text) for s in sessions)


def evaluate(check: Check, text: str, store: AtomStore | None = None) -> Verdict:
    try:
        if check.kind == "text_forbidden":
            return "FAIL" if _any_match(check.patterns, text) else "PASS"
        if check.kind == "pattern":
            return "PASS" if _any_match(check.patterns, text) else "FAIL"
        if check.kind == "cites_evidence":
            if store is None:
                return "UNKNOWN"
            return "PASS" if _cites_evidence(text, store) else "FAIL"
        # manual, lint_tool, live_text: not evaluable in-process in P2a
        return "UNKNOWN"
    except Exception:  # honesty state: a check that cannot run is UNKNOWN, never a crash in the router
        return "UNKNOWN"
