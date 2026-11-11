"""Every persisted row whose kind has a schema must validate as the raw dict the store wrote (C1)."""

import json

from individuation_agent.agent import IndividuationAgent
from individuation_agent.fakes import ScriptedModel, demo_deps, seed_demo_store
from individuation_agent.models import validate_row

SCHEMA_FOR_KIND = {
    "cycle.s1_persona_recognition": "s1-persona-recognition.schema.json",
    "cycle.s2_shadow_probe": "s2-shadow-probe.schema.json",
    "cycle.s3_synthesis": "s3-synthesis.schema.json",
    "self.stage_record": "s4-stage-record.schema.json",
    "shadow.item": "shadow-item.schema.json",
}


def test_every_persisted_cycle_row_validates_against_its_schema(tmp_path):
    store = seed_demo_store(tmp_path / "demo.jsonl")
    agent = IndividuationAgent(demo_deps(store, ScriptedModel(), "scripted", "0", "session:p"))
    agent.run_cycle("session_start", "hello")
    agent.run_cycle("scheduled", "security policy")

    rows = [json.loads(line) for line in store.path.read_text("utf-8").splitlines() if line.strip()]
    checked = 0
    for row in rows:
        schema = SCHEMA_FOR_KIND.get(row["kind"])
        if schema:
            validate_row(row, schema)
            checked += 1
    assert checked >= 10  # 2 cycles x 4 stage atoms + shadow items
