"""Property 4 of the pre-registered substrate, cross-referenced: every atom links to at least one other
or is explicitly terminal. The envelope schema already says so; a validating store enforces it at
append time instead of trusting the writer (lab mode)."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from jsonschema import ValidationError

from individuation_agent.models import AtomEnvelope
from individuation_agent.store import AtomStore

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


def atom(**kw):
    base = dict(id=uuid4(), kind="self.note", made_on=NOW, made_by="agent:t", made_in="session:1",
                tier="VERIFIED", status="live")
    return AtomEnvelope(**{**base, **kw})


def test_validating_store_rejects_an_unlinked_non_terminal_atom(tmp_path):
    store = AtomStore(tmp_path / "atoms.jsonl", validate=True)
    with pytest.raises(ValidationError):
        store.append(atom(links=[], terminal=False))
    assert store.line_count() == 0  # nothing reached the file


def test_validating_store_accepts_terminal_and_linked_atoms(tmp_path):
    store = AtomStore(tmp_path / "atoms.jsonl", validate=True)
    a = store.append(atom(terminal=True))
    store.append(atom(links=[a], terminal=False))
    assert store.line_count() == 2


def test_validating_store_rejects_a_kind_outside_the_envelope_vocabulary(tmp_path):
    store = AtomStore(tmp_path / "atoms.jsonl", validate=True)
    with pytest.raises(ValidationError):
        store.append(atom(kind="lab.note", terminal=True))


def test_default_store_does_not_validate(tmp_path):
    store = AtomStore(tmp_path / "atoms.jsonl")
    store.append(atom(links=[], terminal=False))
    assert store.line_count() == 1
