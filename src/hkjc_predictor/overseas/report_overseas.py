"""Overseas tip sheets + static HTML pages (separate from local)."""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import Optional

from hkjc_predictor.models import ScoredRace, TipSheet, horse_label

DISCLAIMER_ZH = (
    "免責聲明：僅供研究與娛樂用途，並非投注建議。"
    "如在其他途徑博彩，請理性參與。"
)
DISCLAIMER_EN = (
    "DISCLAIMER: For study and entertainment only. "
    "This is NOT betting advice. Gamble responsibly if you bet elsewhere."
)

CSS = """
:root { --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa7b8;
        --accent:#3d8bfd; --accent2:#2dd4bf; --border:#2a3648; }
* { box-sizing: border-box; }
body { margin:0; font-family: "Segoe UI", "Noto Sans TC", system-ui, sans-serif;
       background: var(--bg); color: var(--text); line-height: 1.5; }
a { color: var(--accent2); text-decoration: none; }
a:hover { text-decoration: underline; }
header { background: var(--card); border-bottom: 1px solid var(--border);
         padding: 1rem 1.5rem; }
nav { display:flex; gap:1rem; flex-wrap:wrap; align-items:center; }
nav a.tab { padding:0.4rem 0.9rem; border-radius:999px; border:1px solid var(--border);
            color: var(--muted); }
nav a.tab.active, nav a.tab:hover { background: var(--accent); color:#fff; border-color: var(--accent); }
main { max-width: 960px; margin: 0 auto; padding: 1.5rem; }
h1 { font-size: 1.5rem; margin: 0 0 0.25rem; }
h2 { font-size: 1.15rem; margin-top: 1.75rem; color: var(--accent2); }
.meta, .source, .disclaimer { color: var(--muted); font-size: 0.92rem; }
.source { margin: 0.75rem 0; padding: 0.6rem 0.8rem; background: var(--card);
          border-left: 3px solid var(--accent); border-radius: 4px; }
.disclaimer { margin-top: 2rem; padding: 1rem; border: 1px solid var(--border);
              border-radius: 8px; background: var(--card); }
table { width:100%; border-collapse: collapse; margin: 0.75rem 0 1rem;
        font-size: 0.9rem; }
th, td { padding: 0.45rem 0.5rem; border-bottom: 1px solid var(--border); text-align: left; }
th { color: var(--muted); font-weight: 600; }
td.num, th.num { text-align: right; }
.factors { font-size: 0.85rem; color: var(--muted); }
footer { max-width:960px; margin:0 auto; padding:1rem 1.5rem 2rem; color:var(--muted);
         font-size:0.85rem; }
.card-link { display:block; padding:1rem; margin:0.75rem 0; background:var(--card);
             border:1px solid var(--border); border-radius:8px; color:var(--text); }
.card-link:hover { border-color: var(--accent); }
"""


def _race_label(sr: ScoredRace) -> str:
    race = sr.race
    rid = getattr(race, "race_id", "") or ""
    if rid:
        return f"{rid}: {race.name}"
    return f"Race {race.race_no}: {race.name}"


def _race_block_md(sr: ScoredRace) -> str:
    race = sr.race
    label = _race_label(sr)
    conf_label = sr.race_confidence_label or "Med"
    lines = [
        f"## {label}",
        f"- Class: {race.class_ or 'n/a'} | Distance: {race.distance_m}m | "
        f"Surface: {race.surface} | Going: {race.going}",
        f"- **Race confidence: {sr.race_confidence:.0f}% ({conf_label})**",
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
    lines.append("### Factor breakdown (top 3) — generic draw (no HV/ST tables)")
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
    conf_label = sr.race_confidence_label or "Med"
    lines = [
        _race_label(sr),
        f"  {race.class_ or 'n/a'} | {race.distance_m}m | {race.surface} | {race.going}",
        f"  Race confidence: {sr.race_confidence:.0f}% ({conf_label})",
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
    lines.append("  Top 3 (generic draw — no local HV/ST bias tables):")
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


def render_overseas_markdown(sheet: TipSheet, source_label: str = "") -> str:
    m = sheet.meeting
    src = source_label or m.source
    parts = [
        f"# Overseas / Simulcast Tip Sheet — {m.date} {m.venue_name} ({m.venue})",
        "",
        f"Source: `{src}` | Going: {m.going} | Surface: {m.surface}",
        f"Config: `{sheet.config_path or 'weights_overseas.yaml'}`",
        "",
        f"> {sheet.disclaimer}",
        "",
        "Scores are 0–100 from fundamental conditions only (no odds/pools).",
        "Local HV/ST draw-bias tables do **not** apply.",
        "",
    ]
    for sr in sheet.scored_races:
        parts.append(_race_block_md(sr))
    parts.append("---")
    parts.append(sheet.disclaimer)
    parts.append("")
    return "\n".join(parts)


def render_overseas_txt(sheet: TipSheet, source_label: str = "") -> str:
    m = sheet.meeting
    src = source_label or m.source
    parts = [
        f"Overseas / Simulcast Tip Sheet — {m.date} {m.venue_name} ({m.venue})",
        f"Source: {src} | Going: {m.going} | Surface: {m.surface}",
        f"Config: {sheet.config_path or 'weights_overseas.yaml'}",
        "",
        sheet.disclaimer,
        "",
        "Scores 0-100 from fundamentals only (NO odds). Conf % = field softmax; Race confidence = ranking decisiveness. Generic draw (no HV/ST tables).",
        "=" * 72,
        "",
    ]
    for sr in sheet.scored_races:
        parts.append(_race_block_txt(sr))
    parts.append("=" * 72)
    parts.append(sheet.disclaimer)
    parts.append("")
    return "\n".join(parts)


def summary_lines_overseas(sheet: TipSheet) -> list[str]:
    lines = [
        f"Overseas meeting: {sheet.meeting.date} {sheet.meeting.venue} "
        f"({len(sheet.scored_races)} race(s), source={sheet.meeting.source})",
        sheet.disclaimer,
    ]
    for sr in sheet.scored_races:
        top = sr.scored[:3]
        rid = getattr(sr.race, "race_id", None) or f"R{sr.race.race_no}"
        conf_label = sr.race_confidence_label or "Med"
        picks = ", ".join(
            f"{s.rank}. {horse_label(s.runner)} ({s.total:.1f}/{s.confidence:.1f}%)"
            for s in top
        )
        top_conf = f"{top[0].confidence:.1f}%" if top else "n/a"
        lines.append(
            f"  {rid} [race conf {sr.race_confidence:.0f}% ({conf_label}), "
            f"top conf {top_conf}]: {picks}"
        )
    return lines


def export_overseas_tip_sheet(
    sheet: TipSheet,
    output_dir: str | Path,
    source_label: str = "",
) -> tuple[Path, Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    m = sheet.meeting
    stem = f"tips_overseas_{m.date}_{m.venue}"
    md_path = out / f"{stem}.md"
    txt_path = out / f"{stem}.txt"
    md_path.write_text(render_overseas_markdown(sheet, source_label), encoding="utf-8")
    txt_path.write_text(render_overseas_txt(sheet, source_label), encoding="utf-8")
    return md_path, txt_path


def _nav(active: str) -> str:
    tabs = [
        ("index.html", "首頁 Home", active == "index"),
        ("local.html", "本地 Local", active == "local"),
        ("overseas.html", "海外 Overseas", active == "overseas"),
    ]
    bits = []
    for href, label, is_active in tabs:
        cls = "tab active" if is_active else "tab"
        bits.append(f'<a class="{cls}" href="{href}">{html.escape(label)}</a>')
    return "\n".join(bits)


def _page_shell(title: str, active: str, body: str) -> str:
    """Static HTML shell with relative nav + Refresh live button (POST /api/refresh)."""
    from hkjc_predictor.web.chrome import REFRESH_BTN, REFRESH_SCRIPT, WEB_CSS_EXTRA

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{html.escape(title)}</title>
<style>{CSS}
{WEB_CSS_EXTRA}
</style>
</head>
<body>
<header>
  <h1>HKJC Predictor · 基本面提示單</h1>
  <p class="meta">Fundamentals only · 不含賠率 No odds</p>
  <nav>{_nav(active)}</nav>
  {REFRESH_BTN}
</header>
<main>
{body}
</main>
<footer>
  <p>{html.escape(DISCLAIMER_ZH)}</p>
  <p>{html.escape(DISCLAIMER_EN)}</p>
</footer>
{REFRESH_SCRIPT}
</body>
</html>
"""


def _sheet_to_html_body(sheet: TipSheet, source_adapter: str, source_label: str) -> str:
    m = sheet.meeting
    parts = [
        f"<h1>海外 Overseas · {html.escape(m.date)} {html.escape(m.venue_name)} "
        f"({html.escape(m.venue)})</h1>",
        f'<p class="meta">Going: {html.escape(m.going)} · Surface: {html.escape(m.surface)} · '
        f"Config: {html.escape(sheet.config_path or 'weights_overseas.yaml')}</p>",
        f'<div class="source"><strong>資料來源 Source:</strong> '
        f"{html.escape(source_label or m.source)}<br/>"
        f"<strong>Source adapter:</strong> {html.escape(source_adapter)}</div>",
        f'<p class="meta">Generic draw heuristics — local HV/ST draw-bias tables do NOT apply.</p>',
    ]
    for sr in sheet.scored_races:
        race = sr.race
        conf_label = sr.race_confidence_label or "Med"
        parts.append(f"<h2>{html.escape(_race_label(sr))}</h2>")
        parts.append(
            f'<p class="meta">{html.escape(race.class_ or "n/a")} · '
            f"{race.distance_m}m · {html.escape(race.surface)} · "
            f"{html.escape(race.going)}</p>"
        )
        parts.append(
            f'<p class="source"><strong>Race confidence:</strong> '
            f"{sr.race_confidence:.0f}% ({html.escape(conf_label)})</p>"
        )
        parts.append(
            "<table><thead><tr>"
            '<th class="num">Rk</th><th class="num">No</th><th>馬名 Horse</th>'
            '<th class="num">Score</th><th class="num">Conf %</th>'
            '<th>Form</th><th class="num">Dr</th>'
            "<th>Jockey</th><th>Trainer</th>"
            '<th class="num">Rtg</th><th class="num">Wt</th>'
            "</tr></thead><tbody>"
        )
        for s in sr.scored:
            r = s.runner
            parts.append(
                "<tr>"
                f'<td class="num">{s.rank}</td><td class="num">{r.horse_no}</td>'
                f"<td>{html.escape(horse_label(r))}</td>"
                f'<td class="num">{s.total:.1f}</td>'
                f'<td class="num">{s.confidence:.1f}</td>'
                f"<td>{html.escape(r.form or '-')}</td>"
                f'<td class="num">{r.draw}</td>'
                f"<td>{html.escape(r.jockey)}</td>"
                f"<td>{html.escape(r.trainer)}</td>"
                f'<td class="num">{r.rating:g}</td>'
                f'<td class="num">{r.weight_kg:g}</td>'
                "</tr>"
            )
        parts.append("</tbody></table>")
        parts.append('<ul class="factors">')
        for s in sr.scored[:3]:
            f = s.factors
            parts.append(
                f"<li><strong>{html.escape(horse_label(s.runner))}</strong> "
                f"(score={s.total:.1f}, conf={s.confidence:.1f}%): "
                f"form={f.recent_form:.0f}, CD={f.course_distance_fit:.0f}, "
                f"draw={f.draw_bias:.0f}, jockey={f.jockey:.0f}, trainer={f.trainer:.0f}, "
                f"rtg={f.rating:.0f}</li>"
            )
        parts.append("</ul>")
    parts.append(
        f'<div class="disclaimer"><p>{html.escape(DISCLAIMER_ZH)}</p>'
        f"<p>{html.escape(sheet.disclaimer)}</p></div>"
    )
    return "\n".join(parts)


def render_overseas_html_page(
    sheet: TipSheet,
    *,
    source_adapter: str = "hkjc_simulcast",
    source_label: str = "",
) -> str:
    body = _sheet_to_html_body(sheet, source_adapter, source_label)
    title = f"海外 Overseas — {sheet.meeting.date} {sheet.meeting.venue}"
    return _page_shell(title, "overseas", body)


def render_local_html_page(
    *,
    tip_md_links: list[tuple[str, str]],
    tip_txt_preview: str = "",
    local_fixture_note: str = "",
    local_card_declared: bool = True,
) -> str:
    parts = [
        "<h1>本地 Local · 香港賽事</h1>",
        '<p class="meta">Local HKJC tip sheets (HV / ST). Separate from overseas.</p>',
    ]
    if not local_card_declared:
        note = local_fixture_note or (
            "No local ST/HV race card is currently declared in the active HKJC GraphQL schedule."
        )
        parts.append(
            f'<div class="source"><strong>Local card status:</strong> '
            f"{html.escape(note)}</div>"
        )
    elif local_fixture_note:
        parts.append(
            f'<p class="meta">{html.escape(local_fixture_note)}</p>'
        )
    if tip_md_links:
        parts.append("<h2>最新提示單 Latest tip sheets</h2>")
        for label, href in tip_md_links:
            parts.append(
                f'<a class="card-link" href="{html.escape(href)}">'
                f"{html.escape(label)}</a>"
            )
    else:
        parts.append(
            '<p class="meta">No local tip sheets found under output/ yet. '
            "Run <code>python -m hkjc_predictor --demo</code> or wait for a declared local card.</p>"
        )
    if tip_txt_preview:
        parts.append("<h2>Preview</h2>")
        parts.append(f"<pre>{html.escape(tip_txt_preview[:6000])}</pre>")
    parts.append(
        f'<div class="disclaimer"><p>{html.escape(DISCLAIMER_ZH)}</p>'
        f"<p>{html.escape(DISCLAIMER_EN)}</p></div>"
    )
    return _page_shell("本地 Local — HKJC", "local", "\n".join(parts))


def render_index_html() -> str:
    body = f"""
<h1>首頁 Home</h1>
<p class="meta">Choose a tip sheet page. Local and overseas use separate data paths.</p>
<a class="card-link" href="local.html">
  <strong>本地 Local</strong><br/>
  Hong Kong race meetings (Happy Valley / Sha Tin)
</a>
<a class="card-link" href="overseas.html">
  <strong>海外 Overseas</strong><br/>
  Simulcast / overseas meetings (separate sources &amp; weights)
</a>
<div class="disclaimer">
  <p>{html.escape(DISCLAIMER_ZH)}</p>
  <p>{html.escape(DISCLAIMER_EN)}</p>
</div>
"""
    return _page_shell("HKJC Predictor", "index", body)



def _try_rebuild_overseas_sheet(output_dir: Path) -> Optional[TipSheet]:
    """If overseas sample + weights exist, re-score for a full HTML page."""
    del output_dir  # reserved for future: pick meeting matching latest tip stem
    sample = Path(__file__).resolve().parents[3] / "data" / "sample_overseas_meeting.json"
    cfg_path = Path(__file__).resolve().parents[3] / "config" / "weights_overseas.yaml"
    if not sample.is_file() or not cfg_path.is_file():
        return None
    try:
        from hkjc_predictor.parse import load_meeting_json
        from hkjc_predictor.overseas.score_overseas import (
            load_overseas_weights,
            score_overseas_meeting,
        )

        meeting = load_meeting_json(sample)
        cfg = load_overseas_weights(cfg_path)
        return score_overseas_meeting(meeting, cfg, config_path=str(cfg_path))
    except Exception:  # noqa: BLE001
        return None


def build_pages(
    output_dir: str | Path,
    *,
    overseas_sheet: Optional[TipSheet] = None,
    source_adapter: str = "hkjc_simulcast",
    source_label: str = "",
    local_fixture_note: Optional[str] = None,
    local_card_declared: bool = True,
) -> dict[str, Path]:
    """Regenerate output/pages/index.html, local.html, overseas.html."""
    out = Path(output_dir)
    pages = out / "pages"
    pages.mkdir(parents=True, exist_ok=True)

    # Local tip sheet links (exclude overseas_* stems)
    local_links: list[tuple[str, str]] = []
    preview = ""
    for md in sorted(out.glob("tips_*.md"), reverse=True):
        if md.name.startswith("tips_overseas_"):
            continue
        local_links.append((md.name, f"../{md.name}"))
        txt = md.with_suffix(".txt")
        if not preview and txt.is_file():
            preview = txt.read_text(encoding="utf-8")

    index_path = pages / "index.html"
    local_path = pages / "local.html"
    overseas_path = pages / "overseas.html"

    index_path.write_text(render_index_html(), encoding="utf-8")
    local_path.write_text(
        render_local_html_page(
            tip_md_links=local_links,
            tip_txt_preview=preview,
            local_fixture_note=local_fixture_note or "",
            local_card_declared=local_card_declared,
        ),
        encoding="utf-8",
    )

    if overseas_sheet is None:
        # Rebuild from latest overseas tip stem by re-scoring demo sample if present
        overseas_sheet = _try_rebuild_overseas_sheet(out)

    if overseas_sheet is not None:
        overseas_path.write_text(
            render_overseas_html_page(
                overseas_sheet,
                source_adapter=source_adapter,
                source_label=source_label or overseas_sheet.meeting.source,
            ),
            encoding="utf-8",
        )
    else:
        body = f"""
<h1>海外 Overseas</h1>
<p class="meta">No overseas tip sheet yet. Run
<code>python -m hkjc_predictor --demo-overseas</code>.</p>
<div class="source"><strong>Source adapter:</strong> {html.escape(source_adapter)}</div>
<div class="disclaimer">
  <p>{html.escape(DISCLAIMER_ZH)}</p>
  <p>{html.escape(DISCLAIMER_EN)}</p>
</div>
"""
        overseas_path.write_text(
            _page_shell("海外 Overseas", "overseas", body), encoding="utf-8"
        )

    return {"index": index_path, "local": local_path, "overseas": overseas_path}


def generated_at_label() -> str:
    # Box clock is Asia/Hong_Kong
    return datetime.now().strftime("%Y-%m-%d %H:%M HKT")
