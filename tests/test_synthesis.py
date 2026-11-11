import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from individuation_agent.models import ShadowItem, UnusedCapabilityPayload, validate_against_schema
from individuation_agent.registers import Persona
from individuation_agent.synthesis import Synthesizer, complement_of

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


def item(tier="VERIFIED"):
    return ShadowItem(
        id=uuid4(), made_on=NOW, made_by="detector:tool_registry", made_in="s", terminal=True, tier=tier,
        probe_id=uuid4(), class_="unused_capability",
        payload=UnusedCapabilityPayload(tool_id="bash", available_since=NOW, never_called_in=["s"]),
        probed_in="c1", persona_id="g", defer_count=0,
    )


@pytest.fixture
def persona():
    return Persona(id="g", archetype="Guardian", display_name="G", cognitive_mode="convergent")


def synth(responses):
    return Synthesizer(FakeListChatModel(responses=responses), base_model_id="fake", base_model_version="0")


def test_complement_of_flips_mode():
    assert complement_of("convergent") == "divergent"
    assert complement_of("divergent") == "convergent"


def test_valid_json_becomes_proposals_with_inherited_tier(persona):
    it = item(tier="REPORTED")
    reply = json.dumps([{"action": "adopt", "target": str(it.probe_id), "rationale": "bash is in bounds"}])
    s3 = synth([reply]).run(persona, [it], "ctx", "c1", "s")
    assert s3.mode == "divergent"
    assert s3.complement_of == "g"
    assert len(s3.proposals) == 1
    assert s3.proposals[0].action == "adopt"
    assert s3.proposals[0].target == it.probe_id
    # model-authored synthesis is reasoning from evidence: capped at INFERRED, never above the item (I3)
    assert s3.proposals[0].tier == "INFERRED"
    assert s3.tier == "INFERRED"
    assert s3.model_call.distinct_model is False


def test_unknown_target_dropped(persona):
    it = item()
    reply = json.dumps([{"action": "adopt", "target": str(uuid4()), "rationale": "nope"}])
    s3 = synth([reply]).run(persona, [it], "ctx", "c1", "s")
    assert s3.proposals == []
    assert s3.tier == "UNKNOWN"  # a hallucinated probe_id is the same class of evidence as malformed JSON (I7)


def test_unknown_item_tier_stays_unknown(persona):
    it = item(tier="UNKNOWN")
    reply = json.dumps([{"action": "adopt", "target": str(it.probe_id), "rationale": "x"}])
    s3 = synth([reply]).run(persona, [it], "ctx", "c1", "s")
    assert s3.proposals[0].tier == "UNKNOWN"


def test_duplicate_targets_keep_first_only(persona):
    it = item()
    reply = json.dumps([
        {"action": "adopt", "target": str(it.probe_id), "rationale": "first"},
        {"action": "defer", "target": str(it.probe_id), "rationale": "second"},
    ])
    s3 = synth([reply]).run(persona, [it], "ctx", "c1", "s")
    assert [p.action for p in s3.proposals] == ["adopt"]


class ListContentModel(BaseChatModel):
    """Returns content as a list of blocks, as a multi-block provider response does."""

    payload: str = ""

    @property
    def _llm_type(self) -> str:
        return "list-content"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        msg = AIMessage(content=[{"type": "text", "text": self.payload}])
        return ChatResult(generations=[ChatGeneration(message=msg)])


def test_list_content_response_is_parsed(persona):
    it = item()
    reply = json.dumps([{"action": "adopt", "target": str(it.probe_id), "rationale": "x"}])
    model = ListContentModel(payload=reply)
    s3 = Synthesizer(model, base_model_id="m", base_model_version="0").run(persona, [it], "ctx", "c1", "s")
    assert [p.action for p in s3.proposals] == ["adopt"]


def test_bad_action_dropped(persona):
    it = item()
    reply = json.dumps([{"action": "delete", "target": str(it.probe_id), "rationale": "nope"}])
    s3 = synth([reply]).run(persona, [it], "ctx", "c1", "s")
    assert s3.proposals == []


def test_code_fenced_json_is_accepted(persona):
    it = item()
    reply = "```json\n" + json.dumps([{"action": "defer", "target": str(it.probe_id), "rationale": "later"}]) + "\n```"
    s3 = synth([reply]).run(persona, [it], "ctx", "c1", "s")
    assert [p.action for p in s3.proposals] == ["defer"]


def test_malformed_json_yields_empty_unknown_s3(persona):
    s3 = synth(["I think we should adopt bash"]).run(persona, [item()], "ctx", "c1", "s")
    assert s3.proposals == []
    assert s3.tier == "UNKNOWN"


def test_s3_validates_against_schema(persona):
    it = item()
    reply = json.dumps([{"action": "resolve", "target": str(it.probe_id), "rationale": "ok"}])
    s3 = synth([reply]).run(persona, [it], "ctx", "c1", "s")
    validate_against_schema(s3, "s3-synthesis.schema.json")
