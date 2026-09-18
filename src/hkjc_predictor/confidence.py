"""Softmax horse confidence % and whole-race confidence (fundamentals only).

Score (0–100) is the weighted fundamental rating of a runner in isolation
(relative to field on some factors). Conf % is that horse's share of a
softmax over the race's scores — how strongly the model backs it vs the
field. Race confidence is how decisive the ranking is (gap + entropy).
"""

from __future__ import annotations

import math
from typing import Any, Sequence

from hkjc_predictor.models import ScoredRunner

DEFAULT_TEMPERATURE = 8.0
DEFAULT_GAP_SCALE = 10.0
DEFAULT_HIGH = 70.0
DEFAULT_MED = 45.0


def softmax_probabilities(
    scores: Sequence[float],
    temperature: float = DEFAULT_TEMPERATURE,
) -> list[float]:
    """Convert raw scores to a probability distribution via softmax.

    Lower temperature → sharper (more peaked) distribution.
    """
    n = len(scores)
    if n == 0:
        return []
    if n == 1:
        return [1.0]
    t = max(float(temperature), 1e-6)
    max_s = max(scores)
    exps = [math.exp((float(s) - max_s) / t) for s in scores]
    z = sum(exps)
    if z <= 0:
        return [1.0 / n] * n
    return [e / z for e in exps]


def compute_race_confidence(
    scores_desc: Sequence[float],
    probs: Sequence[float],
    conf_cfg: dict[str, Any] | None = None,
) -> tuple[float, str]:
    """Map score gap (top1−top2) and distribution entropy to 0–100 + label.

    High when the top pick is well separated and the field is not flat.
    Low when scores are bunched (photo-finish / high entropy).
    """
    cfg = conf_cfg or {}
    gap_scale = float(cfg.get("gap_scale", DEFAULT_GAP_SCALE))
    high_th = float(cfg.get("high_threshold", DEFAULT_HIGH))
    med_th = float(cfg.get("med_threshold", DEFAULT_MED))
    gap_weight = float(cfg.get("gap_weight", 0.6))
    ent_weight = float(cfg.get("entropy_weight", 0.4))

    if len(scores_desc) < 2:
        return 55.0, "Med"

    gap = float(scores_desc[0]) - float(scores_desc[1])
    gap_score = min(100.0, max(0.0, (gap / max(gap_scale, 1e-6)) * 100.0))

    n = len(probs)
    entropy = -sum(float(p) * math.log(max(float(p), 1e-15)) for p in probs)
    max_ent = math.log(n) if n > 1 else 1.0
    concentration = 1.0 - (entropy / max_ent) if max_ent > 0 else 0.0
    ent_score = max(0.0, min(100.0, concentration * 100.0))

    conf = gap_weight * gap_score + ent_weight * ent_score
    conf = max(0.0, min(100.0, conf))
    # Integer % so display and High/Med/Low label stay consistent
    conf_r = float(int(round(conf)))

    if conf_r >= high_th:
        label = "High"
    elif conf_r >= med_th:
        label = "Med"
    else:
        label = "Low"
    return conf_r, label


def attach_confidence(
    scored: list[ScoredRunner],
    cfg: dict[str, Any] | None = None,
) -> tuple[float, str]:
    """Fill each runner's ``confidence`` (0–100) and return race confidence.

    ``scored`` should already be sorted best-first. Mutates runners in place.
    Returns ``(race_confidence_pct, label)``.
    """
    conf_cfg = (cfg or {}).get("confidence", {}) if cfg else {}
    if not isinstance(conf_cfg, dict):
        conf_cfg = {}
    temperature = float(conf_cfg.get("temperature", DEFAULT_TEMPERATURE))

    if not scored:
        return 0.0, "Low"

    scores = [s.total for s in scored]
    probs = softmax_probabilities(scores, temperature)
    for s, p in zip(scored, probs):
        s.confidence = round(p * 100.0, 1)

    race_pct, label = compute_race_confidence(scores, probs, conf_cfg)
    return race_pct, label


def format_race_confidence(pct: float, label: str) -> str:
    return f"Race confidence: {pct:.0f}% ({label})"
