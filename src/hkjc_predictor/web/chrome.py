"""Shared refresh chrome for FastAPI-injected pages and static Cloudflare Pages HTML.

Refresh POSTs to relative ``/api/refresh``:
- Local FastAPI: runs live GraphQL pipeline; returns ``{ok, meeting, races, refreshed_at, ...}``
- Cloudflare Pages Function: POSTs deploy hook; returns ``{ok, triggered}``
"""

from __future__ import annotations

WEB_CSS_EXTRA = """
.btn-refresh {
  appearance: none; cursor: pointer;
  padding: 0.45rem 1rem; border-radius: 999px;
  border: 1px solid var(--accent); background: transparent;
  color: var(--text); font: inherit; font-size: 0.9rem;
  margin-top: 0.5rem;
}
.btn-refresh:hover:not(:disabled) { background: var(--accent); color: #fff; }
.btn-refresh:disabled { opacity: 0.55; cursor: wait; }
.btn-refresh .spin {
  display: inline-block; width: 0.85em; height: 0.85em;
  border: 2px solid currentColor; border-right-color: transparent;
  border-radius: 50%; margin-right: 0.4em; vertical-align: -0.1em;
  animation: spin 0.7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.status-bar {
  margin: 0.75rem 0; padding: 0.6rem 0.8rem; background: var(--card);
  border-left: 3px solid var(--accent2); border-radius: 4px;
  color: var(--muted); font-size: 0.92rem;
}
.status-bar strong { color: var(--text); }
#refresh-status { margin-left: 0.5rem; color: var(--accent2); }
nav { gap: 0.75rem; }
"""

REFRESH_BTN = (
    '<button type="button" class="btn-refresh" data-refresh>'
    "🔄 Refresh live · 即時更新</button>"
    '<span id="refresh-status"></span>'
)

REFRESH_SCRIPT = """
<script>
(function () {
  function setBusy(busy, msg) {
    document.querySelectorAll("[data-refresh]").forEach(function (btn) {
      btn.disabled = busy;
      if (busy) {
        btn.dataset.label = btn.dataset.label || btn.innerHTML;
        btn.innerHTML = '<span class="spin"></span>' + (msg || 'Refreshing…');
      } else if (btn.dataset.label) {
        btn.innerHTML = btn.dataset.label;
      }
    });
    var st = document.getElementById("refresh-status");
    if (st) st.textContent = msg || "";
  }
  async function doRefresh() {
    setBusy(true, "Refreshing live…");
    try {
      var res = await fetch("/api/refresh", { method: "POST" });
      var data = await res.json();
      // Cloudflare Pages Function: deploy hook triggered → wait for rebuild
      if (data.triggered) {
        setBusy(true, "Rebuild triggered — new tip sheets deploy shortly. Reloading in ~45s…");
        setTimeout(function () { location.reload(); }, 45000);
        return;
      }
      if (!data.ok) {
        setBusy(false, "Error: " + (data.error || "refresh failed"));
        return;
      }
      // FastAPI local: pipeline finished
      setBusy(true, "Updated " + (data.refreshed_at || "") + " — reloading…");
      setTimeout(function () { location.reload(); }, 400);
    } catch (e) {
      setBusy(false, "Error: " + e);
    }
  }
  document.querySelectorAll("[data-refresh]").forEach(function (btn) {
    btn.addEventListener("click", function (ev) {
      ev.preventDefault();
      if (btn.disabled) return;
      doRefresh();
    });
  });
})();
</script>
"""


def inject_refresh_chrome(html: str) -> str:
    """Ensure static/generated HTML has refresh CSS, button, and script (idempotent)."""
    if "</style>" in html and "btn-refresh" not in html:
        html = html.replace("</style>", WEB_CSS_EXTRA + "\n</style>", 1)

    if "</nav>" in html and "data-refresh" not in html:
        html = html.replace("</nav>", "</nav>\n  " + REFRESH_BTN, 1)

    if "</body>" in html and "async function doRefresh" not in html:
        html = html.replace("</body>", REFRESH_SCRIPT + "\n</body>", 1)

    return html
