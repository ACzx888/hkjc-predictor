"""Fundamental condition scoring (NO odds / pools)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from hkjc_predictor.confidence import attach_confidence
from hkjc_predictor.models import (
    FactorBreakdown,
    Meeting,
    Race,
    Runner,
    ScoredRace,
    ScoredRunner,
    TipSheet,
)

DISCLAIMER = (
    "DISCLAIMER: For study and entertainment only. "
    "This is NOT betting advice. Gamble responsibly if you bet elsewhere."
)


def load_weights(config_path: str | Path) -> dict[str, Any]:
    path = Path(config_path)
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict) or "weights" not in data:
        raise ValueError(f"Invalid weights config: {path}")
    return data


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def parse_form(form: str, cfg: dict[str, Any]) -> list[int]:
    """Parse form string like '1/3/5/8/2/4' into placing ints (most recent first)."""
    form_cfg = cfg.get("form", {})
    max_starts = int(form_cfg.get("max_starts", 6))
    if not form or not str(form).strip():
        return []
    parts = str(form).replace("-", "/").replace(",", "/").split("/")
    placings: list[int] = []
    for p in parts:
        p = p.strip().upper()
        if not p or p in {"X", "-", "W", "P", "F", "PU", "UR", "DNF"}:
            continue
        # Strip place suffixes like 1st -> 1
        digits = "".join(c for c in p if c.isdigit())
        if digits:
            placings.append(int(digits))
        if len(placings) >= max_starts:
            break
    return placings[:max_starts]


def score_recent_form(runner: Runner, cfg: dict[str, Any]) -> float:
    form_cfg = cfg.get("form", {})
    placings = parse_form(runner.form, cfg)
    if not placings:
        return float(form_cfg.get("no_form_score", 40))
    points_map = {int(k): float(v) for k, v in form_cfg.get("placing_points", {}).items()}
    default_p = int(form_cfg.get("default_placing", 8))
    default_pts = points_map.get(default_p, 25.0)
    scores = [points_map.get(p, default_pts if p > 10 else default_pts) for p in placings]
    # Weight recent starts more heavily
    weights = [1.0 / (i + 1) for i in range(len(scores))]
    total_w = sum(weights)
    return _clamp(sum(s * w for s, w in zip(scores, weights)) / total_w)


def score_course_distance(runner: Runner, cfg: dict[str, Any] | None = None) -> float:
    """Proxy from CD / C / D win-place counts."""
    del cfg  # reserved for future tuning
    cd_w = runner.cd_wins
    cd_p = runner.cd_places
    c_w = runner.c_wins
    d_w = runner.d_wins
    # Heuristic: CD wins strongest, then places, then C/D wins
    raw = (
        18 * cd_w
        + 10 * max(0, cd_p - cd_w)
        + 8 * c_w
        + 6 * d_w
        + 40  # baseline so zero-record horses aren't crushed
    )
    return _clamp(raw)


def score_draw_bias(runner: Runner, race: Race, meeting: Meeting, cfg: dict[str, Any]) -> float:
    venue = meeting.venue.upper()
    surface = (race.surface or meeting.surface or "turf").lower()
    if surface not in {"turf", "awt"}:
        surface = "turf"
    bias = cfg.get("draw_bias", {}).get(venue, {}).get(surface, {})
    scores = bias.get("scores", {})
    # YAML may load keys as ints or strs
    key = runner.draw
    if key in scores:
        return _clamp(float(scores[key]))
    if str(key) in scores:
        return _clamp(float(scores[str(key)]))
    # Extrapolate: far outside draws get low default
    preferred_low = bool(bias.get("preferred_low", True))
    if preferred_low:
        return _clamp(100 - (runner.draw - 1) * 6)
    return _clamp(70 - abs(runner.draw - 6) * 5)


def _tier_score(name: str, tiers: dict[str, Any]) -> float:
    name_l = (name or "").strip().lower()
    if not name_l:
        return float(tiers.get("default", 55))
    for tier, key in (
        ("elite", "elite_names"),
        ("strong", "strong_names"),
        ("solid", "solid_names"),
        ("apprentice", "apprentice_names"),
    ):
        names = tiers.get(key, []) or []
        for n in names:
            if n.strip().lower() == name_l or n.strip().lower() in name_l:
                return float(tiers.get(tier, tiers.get("default", 55)))
    return float(tiers.get("default", 55))


def score_jockey(runner: Runner, cfg: dict[str, Any]) -> float:
    return _tier_score(runner.jockey, cfg.get("jockey_tiers", {}))


def score_trainer(runner: Runner, cfg: dict[str, Any]) -> float:
    return _tier_score(runner.trainer, cfg.get("trainer_tiers", {}))


def score_rating(runner: Runner, race: Race, cfg: dict[str, Any]) -> float:
    rcfg = cfg.get("rating", {})
    lo = float(rcfg.get("min_rating", 20))
    hi = float(rcfg.get("max_rating", 130))
    # Relative to field if possible
    field_ratings = [r.rating for r in race.runners] or [runner.rating]
    field_max = max(field_ratings)
    field_min = min(field_ratings)
    span = max(field_max - field_min, 1.0)
    relative = (runner.rating - field_min) / span * 100.0
    # Also absolute band
    absolute = (runner.rating - lo) / max(hi - lo, 1.0) * 100.0
    base = 0.7 * relative + 0.3 * absolute
    bonus_per = float(rcfg.get("change_bonus_per_point", 1.5))
    cap = float(rcfg.get("change_cap", 15))
    change = _clamp(runner.rating_change * bonus_per, -cap, cap)
    return _clamp(base + change)


def score_weight_claim(runner: Runner, cfg: dict[str, Any]) -> float:
    wcfg = cfg.get("weight_claim", {})
    # HKJC race cards often list weight in pounds; sample uses lbs-like numbers (~123–135).
    # Convert to kg if looks like pounds (>90).
    wt = float(runner.weight_kg)
    if wt > 90:
        wt = wt * 0.453592
    claim = float(runner.claim_kg or 0.0)
    effective = wt - claim
    baseline = float(wcfg.get("baseline_kg", 57.0))
    penalty = float(wcfg.get("kg_penalty", 3.0))
    claim_bonus = float(wcfg.get("claim_bonus", 2.0))
    score = 70.0 - (effective - baseline) * penalty + claim * claim_bonus
    return _clamp(score, float(wcfg.get("min_score", 25)), float(wcfg.get("max_score", 95)))


def score_going_gear(runner: Runner, race: Race, meeting: Meeting, cfg: dict[str, Any]) -> float:
    gcfg = cfg.get("going_gear", {})
    score = float(gcfg.get("default", 50))
    going = (race.going or meeting.going or "GOOD").upper()
    pref = (runner.going_pref or "").upper()
    if pref:
        if "SOFT" in going or "YIELD" in going:
            if "SOFT" in pref or "YIELD" in pref:
                score = float(gcfg.get("soft_suitable", 70))
            elif "FIRM" in pref:
                score = 35.0
        elif "FIRM" in going:
            if "FIRM" in pref:
                score = float(gcfg.get("firm_suitable", 70))
            elif "SOFT" in pref:
                score = 35.0
        elif "GOOD" in going and "GOOD" in pref:
            score = 60.0
    gear = (runner.gear or "").upper()
    if gear and any(g in gear for g in ("B1", "H1", "TT1", "XB1")):
        # first-time gear mild bump
        score = max(score, float(gcfg.get("gear_positive", 60)))
    elif gear:
        score = max(score, 55.0)
    return _clamp(score)


def score_runner(
    runner: Runner,
    race: Race,
    meeting: Meeting,
    cfg: dict[str, Any],
) -> ScoredRunner:
    factors = FactorBreakdown(
        recent_form=score_recent_form(runner, cfg),
        course_distance_fit=score_course_distance(runner, cfg),
        draw_bias=score_draw_bias(runner, race, meeting, cfg),
        jockey=score_jockey(runner, cfg),
        trainer=score_trainer(runner, cfg),
        rating=score_rating(runner, race, cfg),
        weight_claim=score_weight_claim(runner, cfg),
        going_gear=score_going_gear(runner, race, meeting, cfg),
    )
    w = cfg.get("weights", {})
    total = (
        factors.recent_form * float(w.get("recent_form", 0.28))
        + factors.course_distance_fit * float(w.get("course_distance_fit", 0.18))
        + factors.draw_bias * float(w.get("draw_bias", 0.12))
        + factors.jockey * float(w.get("jockey", 0.10))
        + factors.trainer * float(w.get("trainer", 0.08))
        + factors.rating * float(w.get("rating", 0.14))
        + factors.weight_claim * float(w.get("weight_claim", 0.07))
        + factors.going_gear * float(w.get("going_gear", 0.03))
    )
    return ScoredRunner(runner=runner, total=_clamp(total), factors=factors)


def score_race(race: Race, meeting: Meeting, cfg: dict[str, Any]) -> ScoredRace:
    scored = [score_runner(r, race, meeting, cfg) for r in race.runners]
    scored.sort(key=lambda s: (-s.total, s.runner.horse_no))
    for i, s in enumerate(scored, start=1):
        s.rank = i
    race_pct, race_label = attach_confidence(scored, cfg)
    return ScoredRace(
        race=race,
        scored=scored,
        race_confidence=race_pct,
        race_confidence_label=race_label,
    )


def score_meeting(meeting: Meeting, cfg: dict[str, Any], config_path: str = "") -> TipSheet:
    scored_races = [score_race(r, meeting, cfg) for r in meeting.races]
    return TipSheet(
        meeting=meeting,
        scored_races=scored_races,
        config_path=config_path,
        disclaimer=DISCLAIMER,
    )


# Guard: ensure this module never references odds/pools terminology in scoring paths
FORBIDDEN_KEYS = frozenset({"odds", "win_odds", "place_odds", "pool", "dividend", "tote"})
