"""Data models for meetings, races, and runners."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional


@dataclass
class Runner:
    horse_no: int
    name: str
    draw: int
    jockey: str
    trainer: str
    rating: float
    weight_kg: float
    form: str = ""
    name_zh: str = ""
    rating_change: float = 0.0
    claim_kg: float = 0.0
    cd_wins: int = 0
    cd_places: int = 0
    c_wins: int = 0
    d_wins: int = 0
    gear: str = ""
    going_pref: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Runner":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in d.items() if k in known}
        return cls(**filtered)


@dataclass
class Race:
    race_no: int
    name: str
    class_: str
    distance_m: int
    surface: str
    going: str
    runners: list[Runner] = field(default_factory=list)
    race_id: str = ""  # e.g. simulcast id S2-1 (overseas); unused for local

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Race":
        runners = [Runner.from_dict(r) for r in d.get("runners", [])]
        return cls(
            race_no=int(d["race_no"]),
            name=d.get("name", f"Race {d['race_no']}"),
            class_=d.get("class", d.get("class_", "")),
            distance_m=int(d.get("distance_m", 1200)),
            surface=str(d.get("surface", "turf")).lower(),
            going=str(d.get("going", "GOOD")).upper(),
            runners=runners,
            race_id=str(d.get("race_id", "") or ""),
        )


@dataclass
class Meeting:
    date: str
    venue: str
    venue_name: str
    going: str
    surface: str
    races: list[Race] = field(default_factory=list)
    source: str = "unknown"

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Meeting":
        races = [Race.from_dict(r) for r in d.get("races", [])]
        return cls(
            date=str(d["date"]),
            venue=str(d["venue"]).upper(),
            venue_name=d.get("venue_name", d.get("venue", "")),
            going=str(d.get("going", "GOOD")).upper(),
            surface=str(d.get("surface", "turf")).lower(),
            races=races,
            source=d.get("source", "unknown"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FactorBreakdown:
    recent_form: float
    course_distance_fit: float
    draw_bias: float
    jockey: float
    trainer: float
    rating: float
    weight_claim: float
    going_gear: float

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass
class ScoredRunner:
    runner: Runner
    total: float
    factors: FactorBreakdown
    rank: int = 0
    confidence: float = 0.0  # softmax win-prob % vs field (0–100), not raw Score


@dataclass
class ScoredRace:
    race: Race
    scored: list[ScoredRunner]
    race_confidence: float = 0.0  # how decisive the ranking is (0–100)
    race_confidence_label: str = ""  # High / Med / Low


@dataclass
class TipSheet:
    meeting: Meeting
    scored_races: list[ScoredRace]
    config_path: str
    disclaimer: str = (
        "DISCLAIMER: For study and entertainment only. "
        "This is NOT betting advice. Gamble responsibly if you bet elsewhere."
    )
