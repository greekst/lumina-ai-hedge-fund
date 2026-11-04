"""Headless Playwright smoke test of the Streamlit dashboard.

Runs when LUMINA_UI_SMOKE=1 (CI job `ui-smoke`). Starts `streamlit run app.py` in mock
LLM mode, loads the page in Chromium, and checks the main panels render without errors
and that no server-side secret is sent to the browser.
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

pytestmark = pytest.mark.skipif(os.getenv("LUMINA_UI_SMOKE") != "1", reason="set LUMINA_UI_SMOKE=1")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANARY = "canary-secret-value-do-not-render-123"


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    port = _free_port()
    env = dict(os.environ, LUMINA_LLM_MODE="mock", GEMINI_API_KEY=CANARY,
               LUMINA_DATA_DIR=str(tmp_path_factory.mktemp("ui")))
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py", "--server.headless", "true",
         "--server.port", str(port), "--browser.gatherUsageStats", "false"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            if urllib.request.urlopen(url + "/_stcore/health", timeout=2).read().strip() == b"ok":
                break
        except Exception:
            time.sleep(1)
    yield url
    proc.terminate()
    proc.wait(timeout=10)


def test_dashboard_renders(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page_errors = []
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.goto(server, wait_until="networkidle")
        page.wait_for_selector('[data-testid="stApp"]', timeout=60_000)
        page.get_by_text("Lumina AI Hedge Fund").first.wait_for(timeout=60_000)
        page.wait_for_timeout(3000)
        tabs = page.get_by_role("tab").all_inner_texts()
        html = page.content() + "\n".join(page.eval_on_selector_all("input", "els => els.map(e => e.value)"))
        exc = page.locator('[data-testid="stException"]').count()
        browser.close()
    assert exc == 0, "Streamlit rendered an exception block"
    assert not page_errors, page_errors
    for label in ("AI Investment Council", "Portfolio", "Fund Memory", "Content Studio"):
        assert any(label in t for t in tabs), (label, tabs)
    assert CANARY not in html, "server-side API key leaked into the page"
