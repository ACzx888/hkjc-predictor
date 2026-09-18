#!/usr/bin/env python3
"""Assemble ``dist/`` for Cloudflare Pages from ``output/pages`` + tip sheets + web_state.

- Relative nav (index.html / local.html / overseas.html)
- Tip sheet links rewritten to same-directory ``tips_*.md``
- Refresh chrome ensured (POST /api/refresh)
- ``dist/status.json`` from ``data/web_state.json``
- Optional status bar injected into index.html
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"
PAGES = OUTPUT / "pages"
STATE = ROOT / "data" / "web_state.json"
DIST = ROOT / "dist"


def _load_state() -> dict:
    if not STATE.is_file():
        return {
            "ok": None,
            "meeting": "",
            "races": 0,
            "refreshed_at": None,
            "messages": ["No web_state.json yet"],
        }
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return {"ok": False, "error": f"web_state unreadable: {e}"}


def _rewrite_tip_links(html: str) -> str:
    # ../tips_foo.md -> tips_foo.md (co-located in dist/)
    html = re.sub(r'href="\.\./(tips_[^"]+)"', r'href="\1"', html)
    return html


def _status_bar_html(state: dict) -> str:
    refreshed = state.get("refreshed_at") or "n/a"
    meeting = state.get("meeting") or "—"
    races = state.get("races")
    ok = state.get("ok")
    ok_label = "ok" if ok is True else ("failed" if ok is False else "unknown")
    err = state.get("error") or ""
    err_bit = f" — {err}" if err and ok is False else ""
    return (
        '<div class="status-bar">'
        "<strong>狀態 Status</strong><br/>"
        f"Last refresh · 上次更新: <strong>{refreshed}</strong> · {ok_label}{err_bit}<br/>"
        f"Meeting · 賽事: <strong>{meeting}</strong>"
        + (f" · Races · 場次: <strong>{races}</strong>" if races is not None else "")
        + "<br/><span class=\"meta\">Refresh live triggers a Cloudflare rebuild (deploy hook).</span>"
        "</div>"
    )


def _inject_status_into_index(html: str, state: dict) -> str:
    bar = _status_bar_html(state)
    if "status-bar" in html:
        return html
    # Insert after first <h1>…</h1> inside main, or after <main>
    m = re.search(r"(<main[^>]*>\s*<h1[^>]*>.*?</h1>)", html, flags=re.DOTALL)
    if m:
        insert_at = m.end()
        return html[:insert_at] + "\n" + bar + html[insert_at:]
    if "<main>" in html:
        return html.replace("<main>", "<main>\n" + bar, 1)
    return html


def prepare_dist() -> Path:
    from hkjc_predictor.web.chrome import inject_refresh_chrome

    if not PAGES.is_dir() or not (PAGES / "index.html").is_file():
        raise SystemExit(
            f"Missing {PAGES}/index.html — run live/demo + pages first"
        )

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)

    state = _load_state()
    (DIST / "status.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    for name in ("index.html", "local.html", "overseas.html"):
        src = PAGES / name
        if not src.is_file():
            print(f"WARN: missing {src}", file=sys.stderr)
            continue
        html = src.read_text(encoding="utf-8")
        html = _rewrite_tip_links(html)
        html = inject_refresh_chrome(html)
        if name == "index.html":
            html = _inject_status_into_index(html, state)
        (DIST / name).write_text(html, encoding="utf-8")
        print(f"Wrote {DIST / name}")

    # Tip sheets next to HTML so relative links work
    for path in sorted(OUTPUT.glob("tips_*.md")) + sorted(OUTPUT.glob("tips_*.txt")):
        dest = DIST / path.name
        shutil.copy2(path, dest)
        print(f"Copied {dest.name}")

    # _headers optional: cache status short
    (DIST / "_headers").write_text(
        "/status.json\n  Cache-Control: public, max-age=60\n"
        "/*.html\n  Cache-Control: public, max-age=120\n",
        encoding="utf-8",
    )
    print(f"Dist ready: {DIST}")
    return DIST


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "src"))
    prepare_dist()
