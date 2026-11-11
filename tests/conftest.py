import pytest


@pytest.fixture
def schema_dir():
    from individuation_agent.schemas import SCHEMA_DIR

    return SCHEMA_DIR
