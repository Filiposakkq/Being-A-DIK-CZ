"""Run the UI self-test (prehled/ui/selftest.js) in a real browser, headless, and fail when anything fails.

Used by CI (see .github/workflows/translation-manager.yml); it also works locally when Playwright and a Chromium based
browser are available:

    py -m pip install playwright
    py tests\\ui\\run_selftest_ci.py                  (uses Microsoft Edge; set BADIK_BROWSER=chrome for Chrome, or "" for
                                                      Playwright's own Chromium after `py -m playwright install chromium`)

Exit code 0 = every check passed, 1 = a check failed or the page reported a JavaScript error, 2 = Playwright missing.
"""
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE.parent))
TIMEOUT_MS = 240_000


def load_serve_module():
    spec = importlib.util.spec_from_file_location("serve_selftest", HERE / "serve_selftest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed: py -m pip install playwright")
        return 2
    _srv, _app, url, cleanup = load_serve_module().start_synthetic()
    channel = os.environ.get("BADIK_BROWSER", "msedge")
    page_errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel=channel) if channel else p.chromium.launch()
            # The app sends a strict Content-Security-Policy (no eval). Playwright's wait_for_function is evaluated inside the
            # page, so the policy is bypassed for THIS test context only; the checks themselves do not depend on it.
            ctx = browser.new_context(viewport={"width": 1400, "height": 900}, bypass_csp=True)
            page = ctx.new_page()
            page.on("pageerror", lambda e: page_errors.append(str(e)))
            page.goto(url)
            deadline = time.time() + TIMEOUT_MS / 1000
            while not page.evaluate("Boolean(window.__selftest && window.__selftest.done)"):
                if time.time() > deadline:
                    raise TimeoutError("The UI self-test did not finish in time.")
                time.sleep(1)
            result = page.evaluate("window.__selftest")
            page.screenshot(path=str(HERE / "selftest-result.png"))
            browser.close()
    finally:
        cleanup()
    results = result["results"]
    failed = [r for r in results if not r["pass"]]
    print(f"UI self-test: {len(results) - len(failed)}/{len(results)} checks passed")
    for r in failed:
        print(f"  FAIL  {r['name']}  {r.get('detail', '')}")
    for e in result.get("errors", []) + page_errors:
        print(f"  JS ERROR  {e}")
    if failed or result.get("errors") or page_errors:
        print(json.dumps(result.get("errors", []))[:500])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
