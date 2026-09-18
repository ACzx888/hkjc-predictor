"""Parse HKJC race-card HTML / JSON into Meeting models. No odds parsing."""

from __future__ import annotations

import json
import re
from html import unescape
from pathlib import Path
from typing import Any, Optional

from hkjc_predictor.models import Meeting, Race, Runner


def load_meeting_json(path: str | Path) -> Meeting:
    with Path(path).open(encoding="utf-8") as f:
        data = json.load(f)
    meeting = Meeting.from_dict(data)
    meeting.source = meeting.source or "json"
    return meeting


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(text or "")).strip()


def _find_attr(tag: str, attr: str) -> Optional[str]:
    m = re.search(rf'{attr}=["\']([^"\']+)["\']', tag, re.I)
    return m.group(1) if m else None


def parse_racecard_html(
    html: str,
    *,
    date: str,
    venue: str,
    race_no: Optional[int] = None,
) -> Meeting:
    """
    Best-effort parse of HKJC English / zh-hk race card HTML.
    Structure varies; extracts runners from table rows when possible.
    Never reads odds columns.
    """
    venue = venue.upper()
    venue_name = "Sha Tin" if venue == "ST" else "Happy Valley" if venue == "HV" else venue

    # Try to detect going / distance from common patterns
    going = "GOOD"
    gm = re.search(r"Going\s*[:：]\s*([A-Z /]+)", html, re.I)
    if gm:
        going = gm.group(1).strip().upper()

    surface = "turf"
    if re.search(r"\bAWT\b|All[- ]Weather", html, re.I):
        surface = "awt"

    races: list[Race] = []

    # Split by race sections if present
    race_blocks = re.split(r'(?i)(?:Race\s*No\.?\s*|第)\s*(\d+)', html)
    # Alternating: preamble, num, body, num, body...
    if len(race_blocks) >= 3:
        i = 1
        while i + 1 < len(race_blocks):
            try:
                rno = int(race_blocks[i])
            except ValueError:
                i += 2
                continue
            body = race_blocks[i + 1]
            if race_no is not None and rno != race_no:
                i += 2
                continue
            race = _parse_race_block(body, rno, going, surface)
            if race.runners:
                races.append(race)
            i += 2
    else:
        # Single-page race card for one race
        rno = race_no or 1
        race = _parse_race_block(html, rno, going, surface)
        if race.runners:
            races.append(race)

    # Fallback: table rows with horse numbers
    if not races:
        race = _parse_table_runners(html, race_no or 1, going, surface)
        if race.runners:
            races.append(race)

    return Meeting(
        date=date,
        venue=venue,
        venue_name=venue_name,
        going=going,
        surface=surface,
        races=races,
        source="hkjc_html",
    )


def _parse_distance(text: str, default: int = 1200) -> int:
    m = re.search(r"(\d{3,4})\s*M\b", text, re.I)
    if m:
        return int(m.group(1))
    return default


def _parse_race_block(body: str, race_no: int, going: str, surface: str) -> Race:
    name = f"Race {race_no}"
    nm = re.search(r"(?:Race\s*Name|賽事名稱)\s*[:：]?\s*([^<\n]+)", body, re.I)
    if nm:
        name = _clean(nm.group(1))
    class_ = ""
    cm = re.search(r"(Class\s*\d+|第\s*\d+\s*班)", body, re.I)
    if cm:
        class_ = _clean(cm.group(1))
    distance_m = _parse_distance(body)

    runners = _extract_runners_from_html(body)
    return Race(
        race_no=race_no,
        name=name,
        class_=class_,
        distance_m=distance_m,
        surface=surface,
        going=going,
        runners=runners,
    )


def _parse_table_runners(html: str, race_no: int, going: str, surface: str) -> Race:
    return Race(
        race_no=race_no,
        name=f"Race {race_no}",
        class_="",
        distance_m=_parse_distance(html),
        surface=surface,
        going=going,
        runners=_extract_runners_from_html(html),
    )


def _extract_runners_from_html(html: str) -> list[Runner]:
    """
    Extract runners from <tr> rows. Looks for horse no, name, draw, jockey, trainer,
    rating, weight, form. Skips any column that looks like odds.
    """
    runners: list[Runner] = []
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S)
    for row in rows:
        # Skip header / odds-heavy rows
        if re.search(r"\b(Win Odds|Place Odds|賠率)\b", row, re.I):
            continue
        cells = [_clean(re.sub(r"<[^>]+>", " ", c)) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.I | re.S)]
        cells = [c for c in cells if c]
        if len(cells) < 4:
            continue
        # Horse number usually first numeric cell 1–14
        horse_no = None
        for c in cells[:3]:
            if re.fullmatch(r"\d{1,2}", c) and 1 <= int(c) <= 14:
                horse_no = int(c)
                break
        if horse_no is None:
            continue

        # Heuristic field picking
        name = ""
        draw = horse_no
        jockey = ""
        trainer = ""
        rating = 50.0
        weight = 126.0
        form = ""

        for c in cells:
            if re.fullmatch(r"\d{1,2}", c) and 1 <= int(c) <= 14 and c != str(horse_no):
                # likely draw
                draw = int(c)
            elif re.fullmatch(r"\d{2,3}", c):
                val = int(c)
                if 40 <= val <= 140 and rating == 50.0:
                    rating = float(val)
                elif 110 <= val <= 140:
                    weight = float(val)
            elif re.search(r"\d/\d", c) and not form:
                form = c.replace(" ", "")
            elif len(c) > 2 and not name and not re.search(r"odds|\$", c, re.I):
                # first long-ish text after number often horse name
                if horse_no and cells.index(c) <= 4:
                    name = c

        # Better: look for horse name links
        hm = re.search(r'Horse\.aspx[^>]*>([^<]+)<', row, re.I)
        if hm:
            name = _clean(hm.group(1))
        jm = re.search(r'Jockey[^>]*>([^<]+)<', row, re.I) or re.search(
            r"/Jockey/[^\"']+[\"'][^>]*>([^<]+)<", row, re.I
        )
        if jm:
            jockey = _clean(jm.group(1))
        tm = re.search(r'Trainer[^>]*>([^<]+)<', row, re.I) or re.search(
            r"/Trainer/[^\"']+[\"'][^>]*>([^<]+)<", row, re.I
        )
        if tm:
            trainer = _clean(tm.group(1))

        if not name:
            continue

        runners.append(
            Runner(
                horse_no=horse_no,
                name=name,
                draw=draw,
                jockey=jockey or "Unknown",
                trainer=trainer or "Unknown",
                rating=rating,
                weight_kg=weight,
                form=form,
            )
        )

    # Deduplicate by horse_no
    seen: set[int] = set()
    unique: list[Runner] = []
    for r in runners:
        if r.horse_no not in seen:
            seen.add(r.horse_no)
            unique.append(r)
    return unique


def meeting_from_partial(
    date: str,
    venue: str,
    races_data: list[dict[str, Any]],
) -> Meeting:
    venue = venue.upper()
    return Meeting.from_dict(
        {
            "date": date,
            "venue": venue,
            "venue_name": "Sha Tin" if venue == "ST" else "Happy Valley",
            "going": "GOOD",
            "surface": "turf",
            "source": "partial",
            "races": races_data,
        }
    )
