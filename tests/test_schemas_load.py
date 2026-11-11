import json


def test_all_six_schemas_pass_metaschema(schema_dir):
    from jsonschema import Draft202012Validator

    names = sorted(p.name for p in schema_dir.glob("*.json"))
    assert names == [
        "atom-envelope.schema.json",
        "s1-persona-recognition.schema.json",
        "s2-shadow-probe.schema.json",
        "s3-synthesis.schema.json",
        "s4-stage-record.schema.json",
        "shadow-item.schema.json",
    ]
    for p in schema_dir.glob("*.json"):
        Draft202012Validator.check_schema(json.loads(p.read_text("utf-8")))
