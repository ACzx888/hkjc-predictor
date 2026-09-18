"""Overseas fundamental scorer — NO odds; NO local HV/ST draw-bias tables.

Factors: recent form, course/distance, generic draw, jockey, trainer,
rating, weight, going/gear. Local draw-bias tables do NOT apply.
"""

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
from hkjc_predictor.score import (
    parse_form,
    score_course_distance,
    score_going_gear,
    score_jockey,
    score_rating,
    score_recent_form,
    score_trainer,
    score_weight_claim,
)

DISCLAIMER = (
    "DISCLAIMER: For study and entertainment only. "
    "This is NOT betting advice. Gamble responsibly if you bet elsewhere. "
    "Overseas scores use generic draw heuristics — local HV/ST draw-bias tables do NOT apply."
)

FORBIDDEN_KEYS = frozenset({"odds", "win_odds", "place_odds", "pool", "dividend", "tote"})


def load_overseas_weights(config_path: str | Path) -> dict[str, Any]:
    path = Path(config_path)
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict) or "weights" not in data:
        raise ValueError(f"Invalid overseas weights config: {path}")
    # Guard: must not embed local venue draw tables as primary bias
    draw = data.get("draw_generic") or data.get("draw_bias") or {}
    if isinstance(draw, dict) and ("HV" in draw or "ST" in draw):
        raise ValueError(
            "Overseas weights must not use local HV/ST draw_bias tables; "
            "use draw_generic instead."
        )
    return data


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def score_generic_draw(runner: Runner, race: Race, cfg: dict[str, Any]) -> float:
    """Generic draw heuristic for overseas tracks (no HV/ST tables).

    Prefer lower draws mildly on shorter trips; mid draws OK on longer trips.
    Field-size aware when possible.
    """
    g = cfg.get("draw_generic", {})
    field_size = max(len(race.runners), runner.draw, 1)
    draw = max(1, int(runner.draw))
    preferred_low = bool(g.get("preferred_low", True))
    short_m = int(g.get("short_distance_m", 1400))
    dist = int(race.distance_m or 1600)

    if preferred_low and dist <= short_m:
        # Inner better on shorter turns / sprints
        # Normalize: draw 1 -> ~90, outer ~35
        span = max(field_size - 1, 1)
        return _clamp(90.0 - (draw - 1) / span * 55.0)

    # Longer trips: mild mid preference
    mid = (field_size + 1) / 2.0
    return _clamp(80.0 - abs(draw - mid) / max(field_size / 2.0, 1.0) * 30.0)


def score_overseas_runner(
    runner: Runner,
    race: Race,
    meeting: Meeting,
    cfg: dict[str, Any],
) -> ScoredRunner:
    factors = FactorBreakdown(
        recent_form=score_recent_form(runner, cfg),
        course_distance_fit=score_course_distance(runner, cfg),
        draw_bias=score_generic_draw(runner, race, cfg),
        jockey=score_jockey(runner, cfg),
        trainer=score_trainer(runner, cfg),
        rating=score_rating(runner, race, cfg),
        weight_claim=score_weight_claim(runner, cfg),
        going_gear=score_going_gear(runner, race, meeting, cfg),
    )
    w = cfg.get("weights", {})
    total = (
        factors.recent_form * float(w.get("recent_form", 0.30))
        + factors.course_distance_fit * float(w.get("course_distance_fit", 0.16))
        + factors.draw_bias * float(w.get("draw_generic", w.get("draw_bias", 0.10)))
        + factors.jockey * float(w.get("jockey", 0.12))
        + factors.trainer * float(w.get("trainer", 0.10))
        + factors.rating * float(w.get("rating", 0.12))
        + factors.weight_claim * float(w.get("weight_claim", 0.06))
        + factors.going_gear * float(w.get("going_gear", 0.04))
    )
    return ScoredRunner(runner=runner, total=_clamp(total), factors=factors)


def score_overseas_race(race: Race, meeting: Meeting, cfg: dict[str, Any]) -> ScoredRace:
    scored = [score_overseas_runner(r, race, meeting, cfg) for r in race.runners]
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


def score_overseas_meeting(
    meeting: Meeting,
    cfg: dict[str, Any],
    config_path: str = "",
) -> TipSheet:
    scored_races = [score_overseas_race(r, meeting, cfg) for r in meeting.races]
    return TipSheet(
        meeting=meeting,
        scored_races=scored_races,
        config_path=config_path,
        disclaimer=DISCLAIMER,
    )


# Re-export parse_form for tests that may want form helpers via overseas module
__all__ = [
    "DISCLAIMER",
    "FORBIDDEN_KEYS",
    "load_overseas_weights",
    "parse_form",
    "score_generic_draw",
    "score_overseas_meeting",
    "score_overseas_race",
    "score_overseas_runner",
]
