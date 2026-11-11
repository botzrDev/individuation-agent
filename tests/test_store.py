from datetime import datetime, timezone
from uuid import uuid4

import pytest

from individuation_agent.models import AtomEnvelope
from individuation_agent.store import AtomStore

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


def atom(kind="self.note", session="session:1", **extra):
    return AtomEnvelope(
        id=uuid4(),
        kind=kind,
        made_on=NOW,
        made_by="agent:test",
        made_in=session,
        tier="VERIFIED",
        status="live",
        terminal=True,
        **extra,
    )


@pytest.fixture
def store(tmp_path):
    return AtomStore(tmp_path / "atoms.jsonl")


def test_append_then_get_round_trips(store):
    a = atom(statement="I am Guardian")
    aid = store.append(a)
    got = store.get(aid)
    assert got.id == a.id
    assert got.kind == "self.note"
    assert got.model_extra["statement"] == "I am Guardian"


def test_file_only_grows_on_supersede(store):
    old = atom(statement="v1")
    store.append(old)
    first_line = store.path.read_bytes().splitlines()[0]
    before = store.line_count()

    new = atom(statement="v2")
    store.supersede(old.id, new)

    assert store.line_count() == before + 2
    assert store.path.read_bytes().splitlines()[0] == first_line
    assert store.get(old.id).status == "superseded"
    assert store.get(new.id).supersedes == old.id


def test_latest_returns_newest_live_of_kind(store):
    a = atom(statement="first")
    b = atom(statement="second")
    store.append(a)
    store.append(b)
    assert store.latest("self.note").id == b.id
    store.supersede(b.id, atom(kind="self.note", statement="third"))
    assert store.latest("self.note").model_extra["statement"] == "third"
    assert store.latest("nope.kind") is None


def test_consult_by_other_session_sets_last_read(store):
    a = atom(session="session:1")
    store.append(a)
    store.consult(a.id, session_id="session:2")
    assert store.get(a.id).last_read is not None


def test_consult_by_author_session_does_not_set_last_read(store):
    a = atom(session="session:1")
    store.append(a)
    store.consult(a.id, session_id="session:1")
    assert store.get(a.id).last_read is None


def test_all_filters_by_kind_and_status(store):
    store.append(atom(kind="ego.note"))
    live = atom()
    store.append(live)
    store.supersede(live.id, atom())
    assert len(store.all(kind="self.note")) == 2
    assert len(store.all(kind="self.note", status="live")) == 1
    assert len(store.all()) == 3


def test_unknown_id_raises_KeyError(store):
    with pytest.raises(KeyError):
        store.get(uuid4())
