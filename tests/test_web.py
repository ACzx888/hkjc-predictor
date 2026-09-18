"""Web app smoke tests (TestClient; refresh mocked)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from hkjc_predictor.live import LiveResult
from hkjc_predictor.web.app import create_app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import hkjc_predictor.web.app as webapp

    state = tmp_path / "web_state.json"
    monkeypatch.setattr(webapp, "STATE_PATH", state)
    monkeypatch.setattr(webapp, "DATA_DIR", tmp_path)
    return TestClient(create_app())


def test_home_and_status(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Refresh live" in r.text or "即時更新" in r.text
    assert "免責聲明" in r.text or "DISCLAIMER" in r.text

    s = client.get("/api/status")
    assert s.status_code == 200
    body = s.json()
    assert "refreshing" in body


def test_local_overseas_routes(client):
    r = client.get("/local")
    assert r.status_code == 200
    assert "Local" in r.text or "本地" in r.text

    r2 = client.get("/overseas")
    assert r2.status_code == 200
    assert "Overseas" in r2.text or "海外" in r2.text


def test_refresh_mocked(client):
    fake = LiveResult(
        ok=True,
        meeting="2026-09-19 AUS",
        races=3,
        refreshed_at="2026-09-18 15:00:00 HKT",
        local_declared=False,
        overseas_declared=True,
        meetings=[
            {
                "kind": "overseas",
                "date": "2026-09-19",
                "venue": "AUS",
                "venue_name": "Caulfield",
                "races": 3,
                "runners": 30,
                "source": "HKJC GraphQL / test",
            }
        ],
        messages=["mocked"],
    )
    with patch("hkjc_predictor.live.run_live_pipeline", return_value=fake):
        r = client.post("/api/refresh")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["meeting"] == "2026-09-19 AUS"
    assert data["races"] == 3
    assert "refreshed_at" in data

    st = client.get("/api/status").json()
    assert st["ok"] is True
    assert st["meeting"] == "2026-09-19 AUS"


def test_refresh_concurrent_rejected(client, monkeypatch):
    import hkjc_predictor.web.app as webapp

    # Simulate lock already held
    assert webapp._refresh_lock.acquire(blocking=False)
    try:
        r = client.post("/api/refresh")
        assert r.status_code == 409
        body = r.json()
        assert body["ok"] is False
        assert "progress" in body["error"].lower() or body.get("refreshing")
    finally:
        webapp._refresh_lock.release()
