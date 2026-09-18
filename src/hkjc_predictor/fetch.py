"""Fetch HKJC race cards (fundamentals only — no odds endpoints).

Prefers the public GraphQL horseQuery; falls back to HTML RaceCard.aspx.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional
from urllib.parse import urlencode

import requests

from hkjc_predictor.models import Meeting
from hkjc_predictor.parse import parse_racecard_html

USER_AGENT = (
    "Mozilla/5.0 (compatible; HKJCPredictor/0.1; +https://github.com/example/hkjc-predictor) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

TIMEOUT = 20

# English race card (historical pattern). HKJC URLs change; try several.
EN_RACECARD = "https://racing.hkjc.com/racing/information/English/Racing/RaceCard.aspx"
ZH_RACECARD = "https://racing.hkjc.com/racing/information/Chinese/Racing/RaceCard.aspx"
# Meeting fixture / calendar style endpoints (no odds)
FIXTURE_EN = "https://racing.hkjc.com/racing/information/English/Racing/LocalResults.aspx"


class FetchError(Exception):
    """Raised when live HKJC data cannot be retrieved or parsed."""


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-HK,en;q=0.9,zh-HK;q=0.8",
        }
    )
    return s


def _fmt_hkjc_date(d: str) -> str:
    """YYYY-MM-DD -> DD/MM/YYYY used by some HKJC pages."""
    y, m, day = d.split("-")
    return f"{day}/{m}/{y}"


def build_racecard_urls(meeting_date: str, venue: str, race_no: int = 1) -> list[str]:
    venue = venue.upper()
    racecourse = "ST" if venue == "ST" else "HV"
    dmy = _fmt_hkjc_date(meeting_date)
    params_list = [
        {"RaceDate": dmy, "Racecourse": racecourse, "RaceNo": str(race_no)},
        {"RaceDate": meeting_date, "Racecourse": racecourse, "RaceNo": str(race_no)},
        {"racedate": dmy, "Racecourse": racecourse, "RaceNo": str(race_no)},
    ]
    urls: list[str] = []
    for base in (EN_RACECARD, ZH_RACECARD):
        for p in params_list:
            urls.append(f"{base}?{urlencode(p)}")
    return urls


def fetch_url(url: str, session: Optional[requests.Session] = None) -> str:
    sess = session or _session()
    resp = sess.get(url, timeout=TIMEOUT)
    if resp.status_code != 200:
        raise FetchError(f"HTTP {resp.status_code} for {url}")
    text = resp.text
    if not text or len(text) < 200:
        raise FetchError(f"Empty or tiny response from {url}")
    # Soft block detection
    if re.search(r"Access Denied|Request Rejected|captcha|Just a moment", text, re.I):
        raise FetchError(f"Blocked or challenged by HKJC/CDN: {url}")
    return text


def _fetch_meeting_graphql(meeting_date: str, venue: str) -> Meeting:
    """Prefer GraphQL horseQuery for local ST/HV cards."""
    from hkjc_predictor.graphql_client import (
        GraphQLError,
        fetch_live_meetings,
        is_overseas_meeting,
        map_payload_to_meetings,
        post_horse_query,
    )

    venue = venue.upper()
    try:
        payload = post_horse_query(date=meeting_date, venue_code=venue, cache=True)
        meetings = map_payload_to_meetings(payload)
        # Prefer exact local venue+date match
        for m in meetings:
            if m.date == meeting_date and m.venue.upper() == venue:
                return m
        # Active-only world: GraphQL may return the sole active (possibly overseas)
        for m in meetings:
            if m.date == meeting_date and not is_overseas_meeting(m.venue):
                if m.venue.upper() == venue:
                    return m
        # If caller asked for local but only overseas active is returned, signal miss
        live = fetch_live_meetings(date=meeting_date, venue_code=venue, cache=True)
        for m in live:
            if m.venue.upper() == venue and m.date == meeting_date:
                return m
        if meetings:
            # Wrong meeting type for this local fetch
            kinds = ", ".join(f"{x.date} {x.venue}" for x in meetings)
            raise FetchError(
                f"GraphQL returned meeting(s) [{kinds}] but not local "
                f"{meeting_date} {venue} (card may be undeclared)."
            )
        raise FetchError(f"GraphQL returned no meetings for {meeting_date} {venue}")
    except GraphQLError as e:
        raise FetchError(str(e)) from e


def _fetch_meeting_html(
    meeting_date: str,
    venue: str,
    *,
    max_races: int = 11,
) -> Meeting:
    """Legacy HTML RaceCard.aspx aggregation."""
    venue = venue.upper()
    sess = _session()
    errors: list[str] = []
    all_races = []
    going = "GOOD"
    surface = "turf"
    got_any = False

    for rno in range(1, max_races + 1):
        race_ok = False
        for url in build_racecard_urls(meeting_date, venue, rno):
            try:
                html = fetch_url(url, sess)
                meeting = parse_racecard_html(
                    html, date=meeting_date, venue=venue, race_no=rno
                )
                if meeting.races:
                    for race in meeting.races:
                        if not any(x.race_no == race.race_no for x in all_races):
                            all_races.append(race)
                    going = meeting.going or going
                    surface = meeting.surface or surface
                    got_any = True
                    race_ok = True
                    break
            except FetchError as e:
                errors.append(str(e))
            except requests.RequestException as e:
                errors.append(f"Network error: {e}")
        if not race_ok and got_any and rno > 1:
            break

    if not got_any or not all_races:
        hint = "; ".join(errors[:3]) if errors else (
            "HKJC returned a race-card shell/SPA page with no parseable runner table "
            "(card may be unpublished, cancelled, or JS-rendered)"
        )
        raise FetchError(
            f"Could not fetch HKJC race card for {meeting_date} {venue}. "
            f"({hint}). Use --demo for offline sample data."
        )

    all_races.sort(key=lambda r: r.race_no)
    return Meeting(
        date=meeting_date,
        venue=venue,
        venue_name="Sha Tin" if venue == "ST" else "Happy Valley",
        going=going,
        surface=surface,
        races=all_races,
        source="hkjc_live_html",
    )


def fetch_meeting(
    meeting_date: str,
    venue: str,
    *,
    max_races: int = 11,
    prefer_graphql: bool = True,
) -> Meeting:
    """
    Fetch a full meeting race card from HKJC.
    Prefers GraphQL horseQuery; falls back to HTML racecard aggregation.
    Raises FetchError on total failure.
    """
    venue = venue.upper()
    if venue not in {"ST", "HV"}:
        raise FetchError(f"Venue must be ST or HV, got {venue}")

    errors: list[str] = []
    if prefer_graphql:
        try:
            return _fetch_meeting_graphql(meeting_date, venue)
        except FetchError as e:
            errors.append(f"GraphQL: {e}")

    try:
        return _fetch_meeting_html(meeting_date, venue, max_races=max_races)
    except FetchError as e:
        errors.append(f"HTML: {e}")
        raise FetchError(
            f"Could not fetch HKJC race card for {meeting_date} {venue}. "
            f"({' | '.join(errors)}). Use --demo or --live for active meetings."
        ) from e


def guess_next_meeting(after: Optional[date] = None) -> tuple[str, str]:
    """
    Heuristic next HKJC meeting after `after` (default: today HK).
    Midweek often HV (Wed), weekend ST (Sun) or HV (Wed/Thu) — simplified calendar.
    Returns (YYYY-MM-DD, venue).
    Known cancellations (static hints; fixtures still subject to HKJC notices):
    - 2026-09-20 ST cancelled per HKJC fixture notice.
    """
    base = after or date.today()
    cancelled = {("2026-09-20", "ST")}
    # Typical: Wed HV, Sun ST (simplified; actual fixtures vary)
    for offset in range(0, 21):
        d = base + timedelta(days=offset)
        wd = d.weekday()  # Mon=0 … Sun=6
        if wd == 2:  # Wednesday -> HV
            cand = (d.isoformat(), "HV")
        elif wd == 6:  # Sunday -> ST
            cand = (d.isoformat(), "ST")
        elif wd == 3:  # Thursday sometimes HV night
            cand = (d.isoformat(), "HV")
        else:
            continue
        if cand in cancelled:
            continue
        return cand
    # Fallback: next Wednesday HV
    days = (2 - base.weekday()) % 7
    if days == 0:
        days = 7
    d = base + timedelta(days=days)
    return d.isoformat(), "HV"


def try_fetch_next_meeting(after: Optional[date] = None) -> tuple[Optional[Meeting], str]:
    """
    Try live fetch for guessed next meeting (GraphQL first).
    Returns (meeting_or_None, status_message).
    """
    meeting_date, venue = guess_next_meeting(after)
    try:
        meeting = fetch_meeting(meeting_date, venue)
        msg = (
            f"Live fetch OK: {meeting_date} {venue} "
            f"({len(meeting.races)} race(s), source={meeting.source})"
        )
        return meeting, msg
    except FetchError as e:
        return None, (
            f"Live fetch unavailable for guessed next meeting "
            f"{meeting_date} {venue}: {e}"
        )
    except requests.RequestException as e:
        return None, (
            f"Network error fetching next meeting {meeting_date} {venue}: {e}"
        )


def probe_live_status(after: Optional[date] = None) -> dict:
    """Return structured status for reporting (no odds)."""
    meeting_date, venue = guess_next_meeting(after)
    status: dict = {
        "guessed_date": meeting_date,
        "guessed_venue": venue,
        "urls_tried": [],
        "ok": False,
        "detail": "",
        "source": "",
    }
    # GraphQL probe first
    try:
        from hkjc_predictor.graphql_client import fetch_live_meetings

        meetings = fetch_live_meetings(date=meeting_date, venue_code=venue, cache=True)
        for m in meetings:
            n = sum(len(r.runners) for r in m.races)
            if m.venue.upper() == venue.upper() and n > 0:
                status["ok"] = True
                status["source"] = m.source
                status["detail"] = f"GraphQL: {len(m.races)} race(s), {n} runners"
                return status
        if meetings:
            status["detail"] = (
                "GraphQL active meeting(s): "
                + ", ".join(f"{m.date} {m.venue}" for m in meetings)
                + f" (not local {meeting_date} {venue})"
            )
    except Exception as e:  # noqa: BLE001
        status["detail"] = f"GraphQL probe: {e}"

    urls = build_racecard_urls(meeting_date, venue, 1)[:2]
    sess = _session()
    for url in urls:
        status["urls_tried"].append(url)
        try:
            html = fetch_url(url, sess)
            m = parse_racecard_html(html, date=meeting_date, venue=venue, race_no=1)
            n = sum(len(r.runners) for r in m.races)
            status["ok"] = n > 0
            status["detail"] = f"Parsed {len(m.races)} race(s), {n} runners"
            if status["ok"]:
                return status
            status["detail"] = "HTML fetched but no runners parsed"
        except Exception as e:  # noqa: BLE001 — probe must never crash
            status["detail"] = str(e)
    return status
