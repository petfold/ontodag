#!/usr/bin/env python3
"""Drive demo/pyodide/index.html in a real headless browser (Playwright,
not part of the test suite — it needs the network, Chromium, and ~20 s):
serve the directory, wait for Pyodide + the PyPI install, click the
London→Rome example, and check the root the page prints is the pinned
peer root. The HTTP checks cannot see the page; this does.

    pip install playwright && python3 -m playwright install chromium
    python3 demo/pyodide/browser_check.py
"""
import http.server
import os
import re
import sys
import threading

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
EXPECTED = "be7afb84b0a8a43252c2b46048b19d6c2e548a79bb0f2c04bcf2f7b329784ac3"


def main():
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(
        *a, directory=HERE, **k)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/index.html"
    errors = []
    with sync_playwright() as play:
        browser = play.chromium.launch()
        page = browser.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text)
                if m.type == "error" else None)
        page.goto(url)
        page.wait_for_selector("#status.ok, #status.bad", timeout=180_000)
        status = page.text_content("#status")
        print("status:", status)
        if "failed" in status:
            return 1
        page.click("#example")
        page.wait_for_function(
            "document.getElementById('out').textContent.includes('root = ')")
        out = page.text_content("#out")
        page.fill("#in", "get transport from(EU-UK)")
        page.click("#go")
        page.wait_for_function(
            "document.getElementById('out').textContent.includes('N42')")
        browser.close()
    root = re.search(r"root = ([0-9a-f]{64})", out).group(1)
    print("answer lines:", [l for l in out.splitlines()
                            if l in ("BA2551", "true", "duration(9300s)")])
    print("root:", root, "== expected" if root == EXPECTED else "!= expected")
    if errors:
        print("console errors:", errors)
    ok = root == EXPECTED and not errors
    print("PAGE OK" if ok else "PAGE FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
