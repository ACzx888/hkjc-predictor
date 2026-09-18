"""HKJC simulcast / overseas adapter.

Live path uses the public GraphQL horseQuery for active overseas meetings
(S1/S2/S3 or meetingType O). HTML fixture/racecard URLs remain as a weak
fallback. Always supports offline demo via data/sample_overseas_meeting.json.

Does NOT call local HK race-card fetch (hkjc_predictor.fetch.fetch_meeting).
Odds / pmPools fields in GraphQL payloads are ignored by the mapper.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import requests

from hkjc_predictor.models import Meeting
from hkjc_predictor.overseas.sources import OverseasSource
from hkjc_predictor.parse import load_meeting_json

PACKAGE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SAMPLE = PACKAGE_ROOT / "data" / "sample_overseas_meeting.json"

USER_AGENT = (
    "Mozilla/5.0 (compatible; HKJCPredictor/0.1-overseas; "
    "+https://github.com/example/hkjc-predictor) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

FIXTURE_URL = "https://racing.hkjc.com/en-us/overseas/simulcast_fixture"
RACECARD_URL = "https://racing.hkjc.com/racing/overseas/english/racecard.aspx"
TIMEOUT = 20


class SimulcastFetchError(Exception):
    """Live HKJC simulcast data unavailable (SPA/PDF/block)."""


class HkjcSimulcastSource(OverseasSource):
    name = "hkjc_simulcast"
    label = "HKJC Simulcast (GraphQL)"

    def load_meeting(
        self,
        *,
        demo: bool = False,
        date: Optional[str] = None,
        sample_path: Optional[str] = None,
    ) -> Meeting:
        if demo:
            return self._load_demo(sample_path)

        # Live: GraphQL first for active overseas meetings
        try:
            return self._try_live_graphql(date=date)
        except Exception as gql_exc:  # noqa: BLE001
            try:
                return self._try_live_html(date=date)
            except Exception as html_exc:  # noqa: BLE001
                raise SimulcastFetchError(
                    f"HKJC simulcast live fetch failed "
                    f"(GraphQL: {gql_exc}; HTML: {html_exc}). "
                    "Use --demo-overseas for offline sample data."
                ) from gql_exc

    def _load_demo(self, sample_path: Optional[str] = None) -> Meeting:
        path = Path(sample_path) if sample_path else DEFAULT_SAMPLE
        if not path.is_file():
            alt = Path("data/sample_overseas_meeting.json")
            if alt.is_file():
                path = alt
            else:
                raise FileNotFoundError(f"Overseas sample not found: {path}")
        meeting = load_meeting_json(path)
        meeting.source = meeting.source or "HKJC Simulcast sample"
        if "sample" not in (meeting.source or "").lower():
            meeting.source = f"{meeting.source} (demo)"
        return meeting

    def _try_live_graphql(self, date: Optional[str] = None) -> Meeting:
        from hkjc_predictor.graphql_client import (
            GraphQLError,
            fetch_live_meetings,
            is_overseas_meeting,
            split_local_overseas,
        )

        venue_guess = None
        meetings = fetch_live_meetings(date=date, venue_code=venue_guess, cache=True)
        _local, overseas = split_local_overseas(meetings)
        # Also accept meetings whose venue looks like country codes from S*
        if not overseas:
            overseas = [
                m
                for m in meetings
                if is_overseas_meeting(m.venue, "O")
                or (m.venue.upper() not in {"ST", "HV"})
            ]
        if date:
            dated = [m for m in overseas if m.date == date]
            if dated:
                overseas = dated
        if not overseas:
            raise GraphQLError(
                f"No active overseas GraphQL meeting"
                + (f" for date={date}" if date else "")
            )
        # Prefer the meeting with the most runners
        overseas.sort(
            key=lambda m: sum(len(r.runners) for r in m.races), reverse=True
        )
        meeting = overseas[0]
        # Ensure source label mentions GraphQL / real schedule
        if "GraphQL" not in (meeting.source or ""):
            meeting.source = f"HKJC GraphQL / real schedule {meeting.date}"
        return meeting

    def _try_live_html(self, date: Optional[str] = None) -> Meeting:
        """Attempt fixture / racecard HTML. Often fails on SPA shells."""
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language": "en-HK,en;q=0.9",
            }
        )
        urls = [FIXTURE_URL, RACECARD_URL]
        if date:
            urls.append(f"{RACECARD_URL}?{urlencode({'RaceDate': date})}")

        last_err: Exception | None = None
        for url in urls:
            try:
                resp = session.get(url, timeout=TIMEOUT)
                if resp.status_code != 200:
                    last_err = SimulcastFetchError(f"HTTP {resp.status_code} for {url}")
                    continue
                text = resp.text or ""
                if len(text) < 200:
                    last_err = SimulcastFetchError(f"Tiny response from {url}")
                    continue
                if re.search(r"Access Denied|Request Rejected|captcha|Just a moment", text, re.I):
                    last_err = SimulcastFetchError(f"Blocked: {url}")
                    continue
                if "racecard" not in text.lower() and "simulcast" not in text.lower():
                    last_err = SimulcastFetchError(
                        f"No simulcast racecard markers in {url} (likely SPA)"
                    )
                    continue
                raise SimulcastFetchError(
                    f"Received HTML from {url} but structured overseas card "
                    "parsing is not implemented for live SPA/PDF responses. "
                    "Use GraphQL --live or --demo-overseas."
                )
            except SimulcastFetchError as e:
                last_err = e
            except requests.RequestException as e:
                last_err = e
        raise SimulcastFetchError(str(last_err) if last_err else "Live fetch failed")
