"""Stage 3: the complementary-mode pass over open Shadow items.

One call to a chat model under the opposite cognitive mode. Proposals are
parsed, filtered against the items actually probed (first proposal per
target wins), and tier-stamped: a model-authored proposal is reasoning from
evidence, so its tier is the weakest of INFERRED and the item it targets.
If anything the model said had to be dropped, the S3 record is UNKNOWN.
Nothing is applied here.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from uuid import UUID, uuid4

from langchain_core.language_models import BaseChatModel

from .models import CognitiveMode, ContradictionPayload, ModelCall, Proposal, S3Synthesis, ShadowItem, weakest
from .prompts import SYNTHESIS_TEMPLATE
from .registers import Persona

_ACTIONS = {"resolve", "adopt", "revise", "defer"}
_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$", re.MULTILINE)


def complement_of(mode: CognitiveMode) -> CognitiveMode:
    return "divergent" if mode == "convergent" else "convergent"


def _summary(item: ShadowItem) -> str:
    p = item.payload
    if isinstance(p, ContradictionPayload):
        body = f"a='{p.statement_a or p.atom_a}' b='{p.statement_b or p.atom_b}'"
    else:
        body = getattr(p, "tool_id", None) or getattr(p, "error_signature", None) or getattr(p, "prompt_hash", "")
    return f"{item.probe_id}: {item.class_}: {body}"


def _message_text(message) -> str:
    text = getattr(message, "text", None)  # a property in langchain-core 1.x; joins text blocks
    if isinstance(text, str):
        return text
    content = getattr(message, "content", "")
    return content if isinstance(content, str) else str(content)


class Synthesizer:
    def __init__(self, model: BaseChatModel, base_model_id: str, base_model_version: str):
        self.model = model
        self.model_call = ModelCall(base_model_id=base_model_id, base_model_version=base_model_version)

    def run(
        self, persona: Persona, items: list[ShadowItem], context_text: str, cycle_id: str, session_id: str
    ) -> S3Synthesis:
        mode = complement_of(persona.cognitive_mode)
        prompt = SYNTHESIS_TEMPLATE.format(
            persona_name=persona.display_name,
            archetype=persona.archetype,
            active_mode=persona.cognitive_mode,
            complement_mode=mode,
            context=context_text,
            items="\n".join(_summary(i) for i in items) or "(none)",
        )
        text = _message_text(self.model.invoke(prompt))
        by_probe: dict[UUID, ShadowItem] = {i.probe_id: i for i in items}

        proposals: list[Proposal] = []
        used: set[UUID] = set()
        dropped = False
        try:
            data = json.loads(_FENCE.sub("", text.strip()).strip())
            if not isinstance(data, list):
                raise json.JSONDecodeError("not a list", text, 0)
        except json.JSONDecodeError:
            dropped = True
            data = []

        for entry in data:
            if not isinstance(entry, dict):
                dropped = True
                continue
            action = entry.get("action")
            try:
                target = UUID(str(entry.get("target")))
            except (ValueError, TypeError):
                dropped = True
                continue
            if action not in _ACTIONS or target not in by_probe or target in used:
                dropped = True
                continue
            used.add(target)
            new_atom = entry.get("new_atom")
            proposals.append(
                Proposal(
                    id=uuid4(),
                    action=action,
                    target=target,
                    rationale=str(entry.get("rationale", "")),
                    tier=weakest([by_probe[target].tier, "INFERRED"]),
                    new_atom=new_atom if isinstance(new_atom, dict) else None,
                )
            )

        if dropped:
            tier = "UNKNOWN"
        elif proposals:
            tier = weakest([p.tier for p in proposals])
        else:
            # no proposals and nothing dropped: the record asserts only that nothing was proposed, which
            # the system observed directly, so VERIFIED. A record with proposals inherits its weakest
            # proposal's tier, and a proposal is never above INFERRED (model-authored).
            tier = "VERIFIED"

        return S3Synthesis(
            id=uuid4(),
            made_on=datetime.now(timezone.utc),
            made_by=f"synthesizer:{self.model_call.base_model_id}",
            made_in=session_id,
            links=[i.id for i in items],
            terminal=not items,
            tier=tier,
            status="live",
            cycle_id=cycle_id,
            mode=mode,
            complement_of=persona.id,
            model_call=self.model_call,
            proposals=proposals,
        )
