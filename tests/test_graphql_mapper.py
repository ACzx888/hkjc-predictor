"""Unit tests for GraphQL → Meeting mapper (odds stripped; no live network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hkjc_predictor.graphql_client import (
    is_overseas_meeting,
    map_payload_to_meetings,
    map_race_meeting,
    split_local_overseas,
    strip_odds_fields,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "graphql_s1_caulfield_slice.json"


@pytest.fixture(scope="module")
def fixture_payload():
    assert FIXTURE.is_file(), f"missing fixture {FIXTURE}"
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_has_no_odds(fixture_payload):
    blob = json.dumps(fixture_payload)
    for bad in ("winOdds", "pmPools", "jpEsts", "poolInvs"):
        assert bad not in blob


def test_is_overseas_s1_and_meeting_type_o():
    assert is_overseas_meeting("S1", "O")
    assert is_overseas_meeting("S2")
    assert is_overseas_meeting("HV") is False
    assert is_overseas_meeting("ST", "R") is False


def test_map_s1_caulfield_fixture(fixture_payload):
    meetings = map_payload_to_meetings(fixture_payload)
    assert len(meetings) == 1
    m = meetings[0]
    assert m.date == "2026-09-19"
    assert m.venue == "AUS"
    assert "Caulfield" in m.venue_name or "AUSTRALIA" in m.venue_name.upper()
    assert "GraphQL" in m.source
    assert "2026-09-19" in m.source
    assert len(m.races) == 2
    for race in m.races:
        assert race.race_id.startswith("S1-")
        assert race.distance_m > 0
        assert len(race.runners) >= 1
        for r in race.runners:
            assert r.name
            assert r.draw >= 0
            assert r.form  # last6run present in fixture
            # scoring fields only — no odds attribute on Runner
            assert not hasattr(r, "win_odds")
            assert not hasattr(r, "winOdds")


def test_strip_odds_fields_removes_nested():
    raw = {
        "winOdds": "5.2",
        "name_en": "A",
        "nested": {"pmPools": [1], "keep": True},
        "list": [{"winOdds": "9"}, {"ok": 1}],
    }
    cleaned = strip_odds_fields(raw)
    assert "winOdds" not in cleaned
    assert cleaned["name_en"] == "A"
    assert "pmPools" not in cleaned["nested"]
    assert cleaned["nested"]["keep"] is True
    assert "winOdds" not in cleaned["list"][0]
    assert cleaned["list"][1]["ok"] == 1


def test_split_local_overseas(fixture_payload):
    meetings = map_payload_to_meetings(fixture_payload)
    local, overseas = split_local_overseas(meetings)
    assert local == []
    assert len(overseas) == 1


def test_scratched_runners_excluded(fixture_payload):
    raw = fixture_payload["data"]["raceMeetings"][0]
    # Inject a scratched runner into race 1
    race0 = json.loads(json.dumps(raw["races"][0]))
    race0["runners"].append(
        {
            "no": "99",
            "status": "Scratched",
            "name_en": "Should Skip",
            "barrierDrawNumber": "1",
            "last6run": "1/1/1",
            "handicapWeight": "50",
            "internationalRating": "80",
            "gearInfo": "",
            "jockey": {"name_en": "X"},
            "trainer": {"name_en": "Y"},
        }
    )
    meeting_raw = json.loads(json.dumps(raw))
    meeting_raw["races"] = [race0]
    m = map_race_meeting(meeting_raw)
    assert m is not None
    names = [r.name for r in m.races[0].runners]
    assert "Should Skip" not in names


def test_international_rating_used_when_current_empty(fixture_payload):
    m = map_payload_to_meetings(fixture_payload)[0]
    # Fixture runners use internationalRating
    assert any(r.rating > 0 for race in m.races for r in race.runners)
