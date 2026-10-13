import pytest

from repro_events.schemas import SchemaSet, load_schema_set


@pytest.fixture(scope="session")
def schema_set() -> SchemaSet:
    return load_schema_set()
