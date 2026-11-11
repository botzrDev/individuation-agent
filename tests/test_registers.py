import pytest

from individuation_agent.models import Check
from individuation_agent.registers import (
    ArchetypeEntry,
    ArchetypeTable,
    Persona,
    PersonaRegister,
)


def guardian():
    return Persona(
        id="guardian-1",
        archetype="Guardian",
        display_name="Guardian",
        capability_bounds=["grep", "read"],
        cognitive_mode="convergent",
    )


def sage():
    return Persona(id="sage-1", archetype="Sage", display_name="Sage", cognitive_mode="divergent")


def table():
    return ArchetypeTable(
        entries=[
            ArchetypeEntry(
                archetype="Guardian",
                activation_conditions=[Check(kind="pattern", patterns=["security", "policy"])],
                default_cognitive_mode="convergent",
            ),
            ArchetypeEntry(
                archetype="Trickster",
                activation_conditions=[Check(kind="pattern", patterns=["stuck"]), Check(kind="manual")],
                default_cognitive_mode="divergent",
            ),
        ],
        default="Sage",
    )


def test_route_picks_first_fully_passing_entry():
    assert table().route("the user asked about security policy") == "Guardian"


def test_route_falls_back_to_default():
    assert table().route("what is the weather") == "Sage"
    # Trickster has a manual (UNKNOWN) condition, so it never fully passes
    assert table().route("I am stuck") == "Sage"


def test_resolve_by_archetype():
    reg = PersonaRegister(personas=[sage(), guardian()], active="sage-1")
    assert reg.resolve("Guardian").id == "guardian-1"


def test_resolve_missing_raises_KeyError():
    reg = PersonaRegister(personas=[sage()], active="sage-1")
    with pytest.raises(KeyError):
        reg.resolve("Hero")


def test_from_yaml_round_trip(tmp_path):
    p = tmp_path / "personas.yaml"
    p.write_text(
        """
personas:
  - id: sage-1
    archetype: Sage
    display_name: Sage
    cognitive_mode: divergent
  - id: guardian-1
    archetype: Guardian
    display_name: Guardian
    cognitive_mode: convergent
    capability_bounds: [grep, read]
    context_filters:
      - kind: text_forbidden
        patterns: ['\\bCritical\\b']
active: sage-1
""",
        encoding="utf-8",
    )
    reg = PersonaRegister.from_yaml(p)
    assert [x.id for x in reg.personas] == ["sage-1", "guardian-1"]
    assert reg.resolve("Guardian").context_filters[0].kind == "text_forbidden"

    a = tmp_path / "archetypes.yaml"
    a.write_text(
        """
entries:
  - archetype: Guardian
    activation_conditions:
      - kind: pattern
        patterns: [security]
    default_cognitive_mode: convergent
default: Sage
""",
        encoding="utf-8",
    )
    tab = ArchetypeTable.from_yaml(a)
    assert tab.route("security review") == "Guardian"
