"""Render and export tip sheets (markdown + txt)."""

from __future__ import annotations

from pathlib import Path

from hkjc_predictor.models import ScoredRace, TipSheet, horse_label


def _race_block_md(sr: ScoredRace) -> str:
    race = sr.race
    label = sr.race_confidence_label or "Med"
    lines = [
        f"## Race {race.race_no}: {race.name}",
        f"- Class: {race.class_ or 'n/a'} | Distance: {race.distance_m}m | "
        f"Surface: {race.surface} | Going: {race.going}",
        f"- **Race confidence: {sr.race_confidence:.0f}% ({label})**",
        "",
        "| Rank | No | 馬名 Horse | Score | Conf % | Form | Draw | Jockey | Trainer | Rtg | Wt |",
        "|-----:|---:|-------|------:|-------:|------|-----:|--------|---------|----:|---:|",
    ]
    for s in sr.scored:
        r = s.runner
        lines.append(
            f"| {s.rank} | {r.horse_no} | {horse_label(r)} | {s.total:.1f} | {s.confidence:.1f} | "
            f"{r.form or '-'} | {r.draw} | {r.jockey} | {r.trainer} | "
            f"{r.rating:g} | {r.weight_kg:g} |"
        )
    lines.append("")
    lines.append("### Factor breakdown (top 3)")
    for s in sr.scored[:3]:
        f = s.factors
        lines.append(
            f"- **{horse_label(s.runner)}** (score={s.total:.1f}, conf={s.confidence:.1f}%): "
            f"form={f.recent_form:.0f}, CD={f.course_distance_fit:.0f}, "
            f"draw={f.draw_bias:.0f}, jockey={f.jockey:.0f}, trainer={f.trainer:.0f}, "
            f"rtg={f.rating:.0f}, wt={f.weight_claim:.0f}, going/gear={f.going_gear:.0f}"
        )
    lines.append("")
    return "\n".join(lines)


def _race_block_txt(sr: ScoredRace) -> str:
    race = sr.race
    label = sr.race_confidence_label or "Med"
    lines = [
        f"Race {race.race_no}: {race.name}",
        f"  {race.class_ or 'n/a'} | {race.distance_m}m | {race.surface} | {race.going}",
        f"  Race confidence: {sr.race_confidence:.0f}% ({label})",
        "-" * 78,
        f"{'Rk':>3} {'No':>3} {'Horse':<28} {'Score':>6} {'Conf%':>6} "
        f"{'Form':<12} {'Dr':>3} {'Jockey':<14}",
    ]
    for s in sr.scored:
        r = s.runner
        lines.append(
            f"{s.rank:>3} {r.horse_no:>3} {horse_label(r)[:28]:<28} {s.total:>6.1f} "
            f"{s.confidence:>6.1f} {(r.form or '-'):<12} {r.draw:>3} "
            f"{r.jockey[:14]:<14}"
        )
    lines.append("")
    lines.append("  Top 3 factor notes:")
    for s in sr.scored[:3]:
        f = s.factors
        lines.append(
            f"  - {horse_label(s.runner)} (conf {s.confidence:.1f}%): "
            f"form={f.recent_form:.0f} CD={f.course_distance_fit:.0f} "
            f"draw={f.draw_bias:.0f} jky={f.jockey:.0f} trn={f.trainer:.0f} "
            f"rtg={f.rating:.0f}"
        )
    lines.append("")
    return "\n".join(lines)


def render_markdown(sheet: TipSheet) -> str:
    m = sheet.meeting
    parts = [
        f"# HKJC Tip Sheet — {m.date} {m.venue_name} ({m.venue})",
        "",
        f"Source: `{m.source}` | Going: {m.going} | Surface: {m.surface}",
        f"Config: `{sheet.config_path or 'default'}`",
        "",
        f"> {sheet.disclaimer}",
        "",
        "Scores are 0–100 from fundamental conditions only (no odds/pools). Conf % is softmax win probability vs the field; Race confidence is how decisive the ranking is.",
        "",
    ]
    for sr in sheet.scored_races:
        parts.append(_race_block_md(sr))
    parts.append("---")
    parts.append(sheet.disclaimer)
    parts.append("")
    return "\n".join(parts)


def render_txt(sheet: TipSheet) -> str:
    m = sheet.meeting
    parts = [
        f"HKJC Tip Sheet — {m.date} {m.venue_name} ({m.venue})",
        f"Source: {m.source} | Going: {m.going} | Surface: {m.surface}",
        f"Config: {sheet.config_path or 'default'}",
        "",
        sheet.disclaimer,
        "",
        "Scores 0-100 from fundamentals only (NO odds). Conf % = field softmax; Race confidence = ranking decisiveness.",
        "=" * 72,
        "",
    ]
    for sr in sheet.scored_races:
        parts.append(_race_block_txt(sr))
    parts.append("=" * 72)
    parts.append(sheet.disclaimer)
    parts.append("")
    return "\n".join(parts)


def summary_lines(sheet: TipSheet) -> list[str]:
    lines = [
        f"Meeting: {sheet.meeting.date} {sheet.meeting.venue} "
        f"({len(sheet.scored_races)} race(s), source={sheet.meeting.source})",
        sheet.disclaimer,
    ]
    for sr in sheet.scored_races:
        top = sr.scored[:3]
        label = sr.race_confidence_label or "Med"
        picks = ", ".join(
            f"{s.rank}. {horse_label(s.runner)} ({s.total:.1f}/{s.confidence:.1f}%)"
            for s in top
        )
        top_conf = f"{top[0].confidence:.1f}%" if top else "n/a"
        lines.append(
            f"  R{sr.race.race_no} [race conf {sr.race_confidence:.0f}% ({label}), "
            f"top conf {top_conf}]: {picks}"
        )
    return lines


def export_tip_sheet(sheet: TipSheet, output_dir: str | Path) -> tuple[Path, Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    m = sheet.meeting
    stem = f"tips_{m.date}_{m.venue}"
    md_path = out / f"{stem}.md"
    txt_path = out / f"{stem}.txt"
    md_path.write_text(render_markdown(sheet), encoding="utf-8")
    txt_path.write_text(render_txt(sheet), encoding="utf-8")
    return md_path, txt_path
