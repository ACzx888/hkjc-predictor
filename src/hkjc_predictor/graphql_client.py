"""HKJC public GraphQL client (horseQuery) — fundamentals only, odds ignored."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import requests

from hkjc_predictor.models import Meeting, Race, Runner

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
QUERY_PATH = Path(__file__).resolve().parent / "horseQuery.graphql"
CACHE_DIR = PACKAGE_ROOT / "data" / "cache"

GRAPHQL_URL = "https://info.cld.hkjc.com/graphql/base/"

# Browser-like headers required by the CDN / GraphQL gateway.
DEFAULT_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://bet.hkjc.com",
    "Referer": "https://bet.hkjc.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

OVERSEAS_VENUES = frozenset({"S1", "S2", "S3"})
LOCAL_VENUES = frozenset({"ST", "HV"})

# Odds / pool keys that must never reach scoring models.
ODDS_KEYS = frozenset(
    {
        "winOdds",
        "pmPools",
        "jpEsts",
        "poolInvs",
        "obSt",
        "jkcInstNo",
        "tncInstNo",
        "totalInvestment",
    }
)

TIMEOUT = 30


class GraphQLError(Exception):
    """HKJC GraphQL request or schema failure."""


def load_horse_query(path: Optional[Path] = None) -> str:
    """Load the exact whitelisted horseQuery document."""
    qpath = path or QUERY_PATH
    # Also accept /tmp copy used during development
    if not qpath.is_file():
        alt = Path("/tmp/horseQuery.graphql")
        if alt.is_file():
            qpath = alt
        else:
            raise GraphQLError(f"horseQuery.graphql not found at {QUERY_PATH}")
    text = qpath.read_text(encoding="utf-8").strip()
    if "query raceMeetings" not in text:
        raise GraphQLError("horseQuery.graphql does not contain raceMeetings query")
    return text


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(DEFAULT_HEADERS)
    return s


def post_horse_query(
    *,
    date: Optional[str] = None,
    venue_code: Optional[str] = None,
    cache: bool = True,
    session: Optional[requests.Session] = None,
    query: Optional[str] = None,
) -> dict[str, Any]:
    """
    POST the whitelisted horseQuery to HKJC GraphQL.

    Returns the full JSON response. Raw payloads are cached under data/cache/
    when cache=True. Odds fields may be present in the payload but are ignored
    by mappers / scoring.
    """
    q = query or load_horse_query()
    variables: dict[str, Any] = {}
    if date:
        variables["date"] = date
    if venue_code:
        variables["venueCode"] = venue_code.upper()

    payload = {"query": q, "variables": variables}
    sess = session or _session()
    try:
        resp = sess.post(GRAPHQL_URL, json=payload, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise GraphQLError(f"Network error posting horseQuery: {e}") from e

    if resp.status_code != 200:
        raise GraphQLError(f"HTTP {resp.status_code} from HKJC GraphQL")

    try:
        data = resp.json()
    except ValueError as e:
        raise GraphQLError(f"Non-JSON GraphQL response: {e}") from e

    if isinstance(data, dict) and data.get("errors"):
        # Schema / variable errors still return useful diagnostics
        err = data["errors"]
        raise GraphQLError(f"GraphQL errors: {err}")

    if cache:
        _cache_raw(data, date=date, venue_code=venue_code)

    return data


def _cache_raw(
    data: dict[str, Any],
    *,
    date: Optional[str],
    venue_code: Optional[str],
) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dpart = date or "active"
    vpart = (venue_code or "NA").upper()
    path = CACHE_DIR / f"graphql_{dpart}_{vpart}_{stamp}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    # Also keep a rolling "latest" pointer for debugging
    latest = CACHE_DIR / f"graphql_{dpart}_{vpart}_latest.json"
    latest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def strip_odds_fields(obj: Any) -> Any:
    """Recursively drop odds/pool keys from a GraphQL payload (for fixtures/tests)."""
    if isinstance(obj, dict):
        return {
            k: strip_odds_fields(v)
            for k, v in obj.items()
            if k not in ODDS_KEYS and k.lower() not in {"winodds", "placeodds"}
        }
    if isinstance(obj, list):
        return [strip_odds_fields(x) for x in obj]
    return obj


def is_overseas_meeting(venue_code: str, meeting_type: Optional[str] = None) -> bool:
    venue = (venue_code or "").upper()
    mt = (meeting_type or "").upper()
    if mt == "O":
        return True
    if venue in OVERSEAS_VENUES:
        return True
    if venue in LOCAL_VENUES:
        return False
    # Unknown S* codes treated as overseas simulcast
    if venue.startswith("S") and venue[1:].isdigit():
        return True
    return False


def list_active_meetings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data") or {}
    return list(data.get("activeMeetings") or [])


def race_meetings_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data") or {}
    return list(data.get("raceMeetings") or [])


def fetch_active_meeting_payloads(
    *,
    prefer_date: Optional[str] = None,
    prefer_venue: Optional[str] = None,
    cache: bool = True,
) -> list[dict[str, Any]]:
    """
    Fetch GraphQL for the active meeting(s).

    When only one active meeting exists, querying HV/ST future dates still
    returns that active meeting — so we first discover actives, then fetch
    each with date+venueCode for a full raceMeetings payload.
    """
    # Discovery call (may omit date/venue)
    discovery = post_horse_query(
        date=prefer_date,
        venue_code=prefer_venue,
        cache=cache,
    )
    actives = list_active_meetings(discovery)
    detailed = race_meetings_from_payload(discovery)

    # If raceMeetings already populated for the request, use that payload once
    results: list[dict[str, Any]] = []
    if detailed:
        results.append(discovery)
        # If multiple actives and we only got one detailed, fetch the rest
        detailed_ids = {m.get("id") for m in detailed}
        for am in actives:
            if am.get("id") in detailed_ids:
                continue
            d = am.get("date")
            v = am.get("venueCode")
            if d and v:
                results.append(post_horse_query(date=d, venue_code=v, cache=cache))
        return results

    # No detailed meetings — fetch each active explicitly
    if not actives:
        return [discovery]
    for am in actives:
        d = am.get("date")
        v = am.get("venueCode")
        if d and v:
            results.append(post_horse_query(date=d, venue_code=v, cache=cache))
        else:
            results.append(discovery)
    return results or [discovery]


def _to_int(val: Any, default: int = 0) -> int:
    if val is None or val == "":
        return default
    try:
        return int(float(str(val).strip()))
    except (TypeError, ValueError):
        return default


def _to_float(val: Any, default: float = 0.0) -> float:
    if val is None or val == "":
        return default
    try:
        return float(str(val).strip())
    except (TypeError, ValueError):
        return default


def _parse_claim_kg(runner: dict[str, Any], jockey_name: str) -> float:
    """Claim from allowance field or jockey name suffix like (-6) / (-3)."""
    allowance = runner.get("allowance")
    if allowance not in (None, ""):
        # HKJC allowance often in pounds for overseas cards
        claim = abs(_to_float(allowance, 0.0))
        if claim > 0:
            # Convert pounds→kg if large
            return claim * 0.453592 if claim > 15 else claim
    m = re.search(r"\(\s*-?\s*(\d+(?:\.\d+)?)\s*\)", jockey_name or "")
    if m:
        claim = float(m.group(1))
        return claim * 0.453592 if claim > 15 else claim
    return 0.0


def _clean_jockey_name(name: str) -> str:
    """Strip allowance markers from jockey display name for tier matching."""
    if not name:
        return ""
    # "Holly Durnan (a)(-6)" -> "Holly Durnan"
    cleaned = re.sub(r"\([^)]*\)", "", name)
    return re.sub(r"\s+", " ", cleaned).strip()


def _runner_declared(status: str) -> bool:
    s = (status or "").strip().lower()
    if not s:
        return True
    if s in {"scratched", "scratchedreserved", "standby", "withdrawn", "rejected"}:
        return False
    return True  # Declared, Running, etc.


def _surface_from_race(race: dict[str, Any]) -> str:
    track = race.get("raceTrack") or {}
    course = race.get("raceCourse") or {}
    blob = " ".join(
        str(x or "")
        for x in (
            track.get("description_en"),
            track.get("description_ch"),
            course.get("description_en"),
            course.get("displayCode"),
            race.get("raceName_en"),
        )
    ).lower()
    if "awt" in blob or "all weather" in blob or "all-weather" in blob:
        return "awt"
    if "dirt" in blob:
        return "dirt"
    return "turf"


def _map_runner(raw: dict[str, Any]) -> Optional[Runner]:
    if not _runner_declared(str(raw.get("status") or "")):
        return None
    no = _to_int(raw.get("no"), 0)
    if no <= 0:
        return None
    jockey_obj = raw.get("jockey") or {}
    trainer_obj = raw.get("trainer") or {}
    jockey_raw = str(jockey_obj.get("name_en") or jockey_obj.get("name_ch") or "")
    trainer = str(trainer_obj.get("name_en") or trainer_obj.get("name_ch") or "")
    jockey = _clean_jockey_name(jockey_raw) or jockey_raw

    # Prefer local currentRating; fall back to internationalRating (overseas)
    rating = _to_float(raw.get("currentRating"), 0.0)
    if rating <= 0:
        rating = _to_float(raw.get("internationalRating"), 0.0)

    weight = _to_float(raw.get("handicapWeight"), 0.0)
    if weight <= 0:
        weight = _to_float(raw.get("currentWeight"), 0.0)

    # Intentionally ignore winOdds / any pool fields
    return Runner(
        horse_no=no,
        name=str(raw.get("name_en") or raw.get("name_ch") or f"Horse {no}"),
        name_zh=str(raw.get("name_ch") or ""),
        draw=_to_int(raw.get("barrierDrawNumber"), 0),
        jockey=jockey,
        trainer=trainer,
        rating=rating,
        weight_kg=weight,
        form=str(raw.get("last6run") or ""),
        gear=str(raw.get("gearInfo") or ""),
        claim_kg=_parse_claim_kg(raw, jockey_raw),
    )


def _map_race(raw: dict[str, Any], *, venue_code: str, overseas: bool) -> Optional[Race]:
    rno = _to_int(raw.get("no"), 0)
    if rno <= 0:
        return None
    runners: list[Runner] = []
    for r in raw.get("runners") or []:
        mapped = _map_runner(r)
        if mapped is not None:
            runners.append(mapped)
    if not runners:
        return None

    course = raw.get("raceCourse") or {}
    going = str(raw.get("go_en") or raw.get("go_ch") or "GOOD").upper() or "GOOD"
    class_ = str(raw.get("raceClass_en") or raw.get("claCode") or "")
    name = str(raw.get("raceName_en") or raw.get("raceName_ch") or f"Race {rno}")
    distance = _to_int(raw.get("distance"), 1200)
    surface = _surface_from_race(raw)
    race_id = ""
    if overseas:
        race_id = f"{venue_code.upper()}-{rno}"
    # postTime available on raw but not stored on Race model — kept in name context only
    _ = raw.get("postTime")
    _ = course.get("description_en")

    return Race(
        race_no=rno,
        name=name,
        class_=class_,
        distance_m=distance,
        surface=surface,
        going=going,
        runners=runners,
        race_id=race_id,
    )


def _venue_name_for(raw_meeting: dict[str, Any], venue_code: str, overseas: bool) -> str:
    if not overseas:
        return "Sha Tin" if venue_code == "ST" else "Happy Valley" if venue_code == "HV" else venue_code
    countries = raw_meeting.get("country") or []
    country_name = ""
    if countries and isinstance(countries[0], dict):
        country_name = str(countries[0].get("nameen") or countries[0].get("code") or "")
    # Prefer first race course description
    races = raw_meeting.get("races") or []
    course_name = ""
    if races:
        rc = (races[0].get("raceCourse") or {}).get("description_en") or ""
        course_name = str(rc).strip()
    if course_name and country_name:
        return f"{course_name} ({country_name.title()} Simulcast {venue_code})"
    if course_name:
        return f"{course_name} ({venue_code})"
    if country_name:
        return f"{country_name.title()} Simulcast {venue_code}"
    return f"Overseas {venue_code}"


def _meeting_venue_code(raw_meeting: dict[str, Any], overseas: bool) -> str:
    venue = str(raw_meeting.get("venueCode") or "").upper()
    if overseas:
        countries = raw_meeting.get("country") or []
        if countries and isinstance(countries[0], dict):
            code = str(countries[0].get("code") or "").upper()
            if code:
                return code
    return venue or "UNK"


def map_race_meeting(raw_meeting: dict[str, Any]) -> Optional[Meeting]:
    """Map one GraphQL raceMeetings[] entry to a Meeting (odds stripped on map)."""
    venue_code = str(raw_meeting.get("venueCode") or "").upper()
    meeting_type = str(raw_meeting.get("meetingType") or "")
    overseas = is_overseas_meeting(venue_code, meeting_type)
    meeting_date = str(raw_meeting.get("date") or "")
    if not meeting_date:
        return None

    races: list[Race] = []
    for r in raw_meeting.get("races") or []:
        race = _map_race(r, venue_code=venue_code or "S1", overseas=overseas)
        if race is not None:
            races.append(race)
    if not races:
        return None

    races.sort(key=lambda x: x.race_no)
    going = races[0].going if races else "GOOD"
    surface = races[0].surface if races else "turf"
    model_venue = _meeting_venue_code(raw_meeting, overseas)
    venue_name = _venue_name_for(raw_meeting, venue_code, overseas)

    source = f"HKJC GraphQL / {meeting_date}"
    if overseas:
        source = f"HKJC GraphQL / real schedule {meeting_date}"

    return Meeting(
        date=meeting_date,
        venue=model_venue,
        venue_name=venue_name,
        going=going,
        surface=surface,
        races=races,
        source=source,
    )


def map_payload_to_meetings(payload: dict[str, Any]) -> list[Meeting]:
    """Map a full GraphQL response to zero or more Meeting models."""
    meetings: list[Meeting] = []
    for raw in race_meetings_from_payload(payload):
        m = map_race_meeting(raw)
        if m is not None:
            meetings.append(m)
    return meetings


def fetch_live_meetings(
    *,
    date: Optional[str] = None,
    venue_code: Optional[str] = None,
    cache: bool = True,
) -> list[Meeting]:
    """Fetch active/requested meetings and map to models (fundamentals only)."""
    payloads = fetch_active_meeting_payloads(
        prefer_date=date,
        prefer_venue=venue_code,
        cache=cache,
    )
    meetings: list[Meeting] = []
    seen: set[tuple[str, str]] = set()
    for payload in payloads:
        for m in map_payload_to_meetings(payload):
            key = (m.date, m.venue)
            if key in seen:
                continue
            seen.add(key)
            meetings.append(m)
    return meetings


def split_local_overseas(
    meetings: list[Meeting],
) -> tuple[list[Meeting], list[Meeting]]:
    """Split mapped meetings into local (ST/HV) vs overseas."""
    local: list[Meeting] = []
    overseas: list[Meeting] = []
    for m in meetings:
        v = m.venue.upper()
        if v in LOCAL_VENUES:
            local.append(m)
        else:
            overseas.append(m)
    return local, overseas


def note_next_local_fixture(after: Optional[date] = None) -> str:
    """
    Best-effort note about the next local HV/ST fixture.
    Tries fixture page markers; falls back to calendar guesser.
    """
    from hkjc_predictor.fetch import guess_next_meeting

    base = after or date.today()
    guessed_date, guessed_venue = guess_next_meeting(base)
    note = (
        f"Next guessed local fixture: {guessed_date} {guessed_venue} "
        "(calendar heuristic; confirm on HKJC fixture page)."
    )
    # Soft probe of LocalResults / fixture-style page for date markers
    try:
        from hkjc_predictor.fetch import FIXTURE_EN, _session, TIMEOUT

        sess = _session()
        resp = sess.get(FIXTURE_EN, timeout=TIMEOUT)
        if resp.status_code == 200 and resp.text:
            text = resp.text
            # Look for ISO or DD/MM/YYYY near ST/HV
            if re.search(rf"{re.escape(guessed_date)}|{_dmy(guessed_date)}", text):
                note = (
                    f"Local fixture page mentions {guessed_date}; "
                    f"guessed venue {guessed_venue}. "
                    "Card may still be undeclared."
                )
            else:
                note = (
                    f"No declared local card found yet. "
                    f"Guessed next local meeting: {guessed_date} {guessed_venue}."
                )
    except Exception:  # noqa: BLE001 — fixture note must never crash live path
        pass
    return note


def _dmy(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{d}/{m}/{y}"
