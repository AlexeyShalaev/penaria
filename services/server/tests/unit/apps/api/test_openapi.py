from pathlib import Path

import pytest

from penaria.apps.api.openapi import render_schema

pytestmark = pytest.mark.unit

COMMITTED = Path(__file__).parents[4] / "openapi.json"


def test_the_committed_document_matches_the_code() -> None:
    assert COMMITTED.read_text(encoding="utf-8") == render_schema(), (
        "services/server/openapi.json is stale: run `make -C services/server openapi`"
    )
