"""FastAPI app: dashboard, tip sheets, live refresh API."""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from hkjc_predictor.overseas.report_overseas import DISCLAIMER_EN, DISCLAIMER_ZH
from hkjc_predictor.web.chrome import (
    REFRESH_BTN,
    REFRESH_SCRIPT,
    WEB_CSS_EXTRA,
    inject_refresh_chrome,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = PACKAGE_ROOT / "output"
PAGES_DIR = OUTPUT_DIR / "pages"
DATA_DIR = PACKAGE_ROOT / "data"
STATE_PATH = DATA_DIR / "web_state.json"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

_refresh_lock = threading.Lock()
_refreshing = False


def _now_hkt() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S HKT")


def load_state() -> dict[str, Any]:
    if not STATE_PATH.is_file():
        return {
            "ok": None,
            "meeting": "",
            "races": 0,
            "refreshed_at": None,
            "local_declared": None,
            "overseas_declared": None,
            "meetings": [],
            "messages": [],
            "refreshing": False,
        }
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    data.setdefault("refreshing", False)
    return data


def save_state(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _rewrite_nav(html: str) -> str:
    """Map static *.html nav links to FastAPI routes."""
    repl = {
        'href="index.html"': 'href="/"',
        "href='index.html'": "href='/'",
        'href="local.html"': 'href="/local"',
        "href='local.html'": "href='/local'",
        'href="overseas.html"': 'href="/overseas"',
        "href='overseas.html'": "href='/overseas'",
    }
    for a, b in repl.items():
        html = html.replace(a, b)
    # Tip sheet relative links ../tips_*.md — serve via /tips/
    html = re.sub(
        r'href="\.\./(tips_[^"]+)"',
        r'href="/tips/\1"',
        html,
    )
    # Also tip sheets co-located in dist style: tips_*.md at same level
    html = re.sub(
        r'href="(tips_[^"/]+)"',
        r'href="/tips/\1"',
        html,
    )
    return html


def _inject_web_chrome(html: str, *, active: str) -> str:
    """Rewrite nav for FastAPI routes and ensure refresh chrome is present."""
    del active  # reserved for future active-tab tweaks
    html = _rewrite_nav(html)
    html = inject_refresh_chrome(html)
    return html


def _read_page(name: str) -> Optional[str]:
    path = PAGES_DIR / name
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def create_app() -> FastAPI:
    app = FastAPI(
        title="HKJC Predictor",
        description="Fundamental tip sheets (no odds) with live GraphQL refresh",
        version="0.1.0",
    )
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    # Tip sheet markdown/txt under /tips/
    if OUTPUT_DIR.is_dir():
        app.mount("/tips", StaticFiles(directory=str(OUTPUT_DIR)), name="tips")

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request) -> HTMLResponse:
        state = load_state()
        state["refreshing"] = _refreshing
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "state": state,
                "disclaimer_zh": DISCLAIMER_ZH,
                "disclaimer_en": DISCLAIMER_EN,
                "active": "home",
            },
        )

    @app.get("/local", response_class=HTMLResponse)
    async def local_page() -> HTMLResponse:
        raw = _read_page("local.html")
        if raw is None:
            body = (
                "<h1>本地 Local</h1>"
                "<p class='meta'>No local page yet. Click Refresh live.</p>"
            )
            return HTMLResponse(_fallback_shell("本地 Local", "local", body))
        return HTMLResponse(_inject_web_chrome(raw, active="local"))

    @app.get("/overseas", response_class=HTMLResponse)
    async def overseas_page() -> HTMLResponse:
        raw = _read_page("overseas.html")
        if raw is None:
            body = (
                "<h1>海外 Overseas</h1>"
                "<p class='meta'>No overseas page yet. Click Refresh live.</p>"
            )
            return HTMLResponse(_fallback_shell("海外 Overseas", "overseas", body))
        return HTMLResponse(_inject_web_chrome(raw, active="overseas"))

    @app.get("/api/status")
    async def api_status() -> JSONResponse:
        state = load_state()
        state["refreshing"] = _refreshing
        return JSONResponse(state)

    @app.post("/api/refresh")
    async def api_refresh() -> JSONResponse:
        global _refreshing
        if not _refresh_lock.acquire(blocking=False):
            return JSONResponse(
                {
                    "ok": False,
                    "meeting": "",
                    "races": 0,
                    "refreshed_at": _now_hkt(),
                    "error": "Refresh already in progress",
                    "refreshing": True,
                },
                status_code=409,
            )
        try:
            _refreshing = True
            from hkjc_predictor.live import run_live_pipeline

            result = run_live_pipeline(
                output_dir=OUTPUT_DIR,
                quiet=True,
            )
            payload = result.to_api_dict()
            payload["refreshing"] = False
            save_state(payload)
            status = 200 if result.ok else 502
            return JSONResponse(payload, status_code=status)
        except Exception as e:  # noqa: BLE001
            payload = {
                "ok": False,
                "meeting": "",
                "races": 0,
                "refreshed_at": _now_hkt(),
                "error": str(e),
                "refreshing": False,
            }
            save_state(payload)
            return JSONResponse(payload, status_code=500)
        finally:
            _refreshing = False
            _refresh_lock.release()

    return app


def _fallback_shell(title: str, active: str, body: str) -> str:
    from hkjc_predictor.overseas.report_overseas import CSS

    tabs = {
        "home": ("/", "首頁 Home"),
        "local": ("/local", "本地 Local"),
        "overseas": ("/overseas", "海外 Overseas"),
    }
    nav_bits = []
    for key, (href, label) in tabs.items():
        cls = "tab active" if key == active else "tab"
        nav_bits.append(f'<a class="{cls}" href="{href}">{label}</a>')
    nav = "\n".join(nav_bits)
    html = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title}</title>
<style>{CSS}
{WEB_CSS_EXTRA}
</style>
</head>
<body>
<header>
  <h1>HKJC Predictor · 基本面提示單</h1>
  <p class="meta">Fundamentals only · 不含賠率 No odds</p>
  <nav>{nav}</nav>
  {REFRESH_BTN}
</header>
<main>
{body}
<div class="disclaimer"><p>{DISCLAIMER_ZH}</p><p>{DISCLAIMER_EN}</p></div>
</main>
<footer>
  <p>{DISCLAIMER_ZH}</p>
  <p>{DISCLAIMER_EN}</p>
</footer>
{REFRESH_SCRIPT}
</body>
</html>
"""
    return html


app = create_app()
