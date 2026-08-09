#!/usr/bin/env python3
"""Drive the page in a real browser and assert what it shows.

Not part of the test suite: it needs a running server and a downloaded
browser, and it is here because this repo has paid twice for the lesson that
*a 200 is not a pass*. Three bugs shipped in 2026-08-02 behind responses that
were `200` with wrong or empty content — one of them a valid 83x59 PNG
recorded as success. Static wiring checks (tests/test_web.py) catch dead
buttons; only this catches a picture that disagrees with the list beside it,
or a template entity rendered as four literal characters.

    pip install playwright && python3 -m playwright install chromium
    python3 web/app.py &
    python3 web/browser_check.py [--url http://127.0.0.1:5000] [--shots DIR]
"""

import argparse
import sys

from playwright.sync_api import sync_playwright


class Check:
    def __init__(self):
        self.failures = []
        self.done = 0

    def that(self, condition, description):
        self.done += 1
        if condition:
            print(f"  ok   {description}")
        else:
            print(f"  FAIL {description}")
            self.failures.append(description)


def names_in(page, pane):
    return [element.inner_text().strip()
            for element in page.query_selector_all(f".{pane} li .name")]


def transcript(page):
    return page.inner_text(".transcript")


def run(url, shots):
    check = Check()
    with sync_playwright() as play:
        browser = play.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 950})

        errors = []
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(url)
        page.wait_for_selector(".here li", timeout=15000)

        # --- what a stranger sees first ---------------------------------- #
        check.that("32" in page.inner_text(".bar"), "identity bar counts items")
        # `page.content()` re-escapes text nodes, so ask for the rendered
        # text: htm not decoding `&gt;` showed up as four literal characters.
        check.that(page.inner_text(".console .input .prompt").strip() == ">",
                   "the console prompt is a > and not an entity")
        check.that("get " in transcript(page),
                   "the transcript opens with commands to try")
        here = names_in(page, "here")
        check.that("JAL7" in here, "the example's items are listed")
        check.that("weight" not in here,
                   "declarations are not mixed in with things")

        # Rendered, not canonical: the fault this whole page exists to fix.
        check.that(any(n == "time(2026-08-15)" for n in here),
                   "typed values are shown as a person would write them")
        check.that("00:00:00Z" not in page.inner_text(".here"),
                   "the canonical timestamp is not on screen")

        # --- clicking is querying ---------------------------------------- #
        page.click(".refine li:has-text('Japan') button")
        # The crumb updates as soon as the click is handled; the transcript
        # waits on the round trip, so wait for the slower of the two.
        page.wait_for_function(
            "() => document.querySelector('.transcript').innerText"
            ".includes('get Japan')", timeout=10000)
        check.that("get Japan" in transcript(page),
                   "a click writes its command into the console")
        after = names_in(page, "here")
        check.that("JAL7" in after and "BA1" not in after,
                   "the click actually narrowed the answer")

        matching = page.inner_text(".refine li:first-child .n")
        page.click(".refine li:first-child button")
        page.wait_for_timeout(700)
        check.that(page.inner_text(".here h2 .n") == matching,
                   "the count beside a refinement is what the click returns")

        # --- typing is navigating ---------------------------------------- #
        page.fill(".console input", "get Flight")
        page.press(".console input", "Enter")
        page.wait_for_function(
            "() => document.querySelector('.crumbs').innerText.includes('Flight')"
            " && !document.querySelector('.crumbs').innerText.includes('Japan')")
        check.that("Flight" in page.inner_text(".crumbs"),
                   "a typed `get` moves the breadcrumb")

        # --- the picture agrees with the answer --------------------------- #
        page.click(".here li:has-text('JAL7') button")
        # Waiting on `svg g.node` alone matches the PREVIOUS picture, which is
        # still mounted at the moment the click returns — the wait has to name
        # something only the new one satisfies.
        page.wait_for_function(
            "() => document.querySelector('.focus h2')?.innerText.trim() === 'JAL7'"
            " && document.querySelector('.focus .picture svg')?.textContent"
            "     .includes('JAL7')", timeout=15000)
        check.that("JAL7" in page.inner_text(".focus h2"),
                   "the focus pane names what was clicked")
        # SVG elements are not HTMLElements, so `inner_text` is unavailable.
        drawn = {g.text_content().split("\n")[3].split("\xa0")[0].strip()
                 for g in page.query_selector_all(".focus .picture svg g.node")}
        check.that({"JAL7", "Flight", "Japan", "boarding-pass.pdf"} <= drawn,
                   f"the picture draws the item's neighbours ({sorted(drawn)})")
        check.that(len(drawn) < 10,
                   f"the picture is a neighbourhood, not the store ({len(drawn)})")

        # Clicking a shape focuses it — the reason the SVG carries ids.
        page.wait_for_function(
            "() => [...document.querySelectorAll('.focus .picture svg g.node')]"
            "        .some(g => g.textContent.includes('Flight'))", timeout=10000)
        target = next(g for g in page.query_selector_all(
            ".focus .picture svg g.node") if "Flight" in g.text_content())
        target.click()
        page.wait_for_function(
            "() => document.querySelector('.focus h2').innerText.trim() === 'Flight'",
            timeout=10000)
        check.that(page.inner_text(".focus h2").strip() == "Flight",
                   "clicking a node in the picture focuses it")

        # --- a mutation redraws everything -------------------------------- #
        items = page.inner_text(".bar").split(" items")[0].split()[-1]
        page.fill(".console input", "put ANA-lounge Flight")
        page.press(".console input", "Enter")
        page.wait_for_function(
            f"() => !document.querySelector('.bar').innerText"
            f".includes('{items} items')", timeout=10000)
        # Deliberately a fixed settle rather than a wait on the thing being
        # asserted: the bug this catches is a picture that never redraws, and
        # waiting for it to redraw would wait forever and then pass nothing.
        page.wait_for_timeout(2000)
        check.that("ANA-lounge" in page.text_content(".focus .picture"),
                   "the picture redraws after a mutation that changed neither "
                   "the query nor the focus")

        # --- the reference: everything OntoDAG can do --------------------- #
        page.click(".bar button:has-text('Commands')")
        page.wait_for_selector(".sheet .row", timeout=5000)
        rows = page.query_selector_all(".sheet .row")
        greyed = page.query_selector_all(".sheet .row.off")
        check.that(len(rows) == 26,
                   f"the sheet lists every OntoDAG command ({len(rows)})")
        check.that(len(greyed) == 13,
                   f"and marks the ones a browser cannot run ({len(greyed)})")
        check.that(all(r.text_content().strip()
                       for r in page.query_selector_all(".sheet .row.off .why")),
                   "each of those says why, rather than just being greyed")
        check.that("13 of 26 run in the browser" in page.inner_text(".sheet header"),
                   "the sheet header counts them without mangling the spacing")

        page.click(".sheet .row:has-text('move')")
        page.wait_for_function(
            "() => !document.querySelector('.sheet')", timeout=5000)
        check.that(page.input_value(".console input").startswith("move "),
                   "picking one from the sheet puts it in the console")

        page.click(".bar button:has-text('Commands')")
        page.wait_for_selector(".sheet", timeout=5000)
        page.keyboard.press("Escape")
        page.wait_for_function(
            "() => !document.querySelector('.sheet')", timeout=5000)
        check.that(page.query_selector(".sheet") is None,
                   "Escape closes the sheet")
        page.fill(".console input", "")

        # --- the menu: what someone who knows no commands does ------------ #
        page.click(".show-menu")
        page.wait_for_selector(".suggest .option:not(.all)", timeout=5000)
        offered = [o.inner_text().split("\n")[0]
                   for o in page.query_selector_all(".suggest .option:not(.all)")]
        check.that({"put", "get", "move", "remove"} <= set(offered),
                   f"the menu lists the verbs ({len(offered)} of them)")
        check.that(all(o.inner_text().count("\n") >= 1
                       for o in page.query_selector_all(".suggest .option:not(.all)")),
                   "each entry says what it does, not just its name")

        # Chosen while something is selected, it arrives with that something.
        page.click(".suggest .option:not(.all):has-text('move')")
        check.that(page.input_value(".console input").startswith("move Flight"),
                   "the menu fills in the item you are looking at")

        page.fill(".console input", "")
        check.that(page.query_selector(".suggest .option:not(.all)") is None,
                   "an empty line does not pop the menu open by itself")
        page.fill(".console input", "rem")
        page.wait_for_function(
            "() => document.querySelectorAll('.suggest .option:not(.all)').length === 1",
            timeout=5000)
        narrowed = [o.inner_text().split("\n")[0]
                    for o in page.query_selector_all(".suggest .option:not(.all)")]
        check.that(narrowed == ["remove"],
                   f"typing narrows the menu ({narrowed})")
        page.press(".console input", "Escape")
        check.that(page.query_selector(".suggest .option:not(.all)") is None,
                   "Escape puts the menu away")

        # Arrow keys are the list while it is open and the history when it is
        # not — so dismissing it has to hand them back.
        page.press(".console input", "ArrowUp")
        check.that(page.input_value(".console input") != "rem",
                   "with the menu closed, Up walks the history")
        page.fill(".console input", "")

        # --- refusals are visible, not silent ----------------------------- #
        page.fill(".console input", "import /etc/passwd")
        page.press(".console input", "Enter")
        page.wait_for_function(
            "() => document.querySelector('.transcript').innerText"
            ".includes('drop a file')")
        check.that("drop a file" in transcript(page),
                   "a refused command explains itself in the transcript")

        # --- the canonical form is still reachable ------------------------ #
        page.fill(".console input", "canon 'weight(500g)'")
        page.press(".console input", "Enter")
        page.wait_for_function(
            "() => document.querySelector('.transcript').innerText"
            ".includes('kg')", timeout=10000)
        check.that("weight(1/2kg)" in transcript(page),
                   "`canon` shows what a spelling would store")

        if shots:
            page.click(".crumb.root")
            page.wait_for_timeout(900)
            page.screenshot(path=f"{shots}/overview.png")
            page.click(".here li:has-text('Japan') button")
            page.wait_for_selector(".focus .picture svg", timeout=15000)
            page.screenshot(path=f"{shots}/focus.png")
            print(f"  ..   screenshots in {shots}")

        check.that(not errors, f"no console errors ({errors[:3]})")
        browser.close()

    print(f"\n{check.done - len(check.failures)}/{check.done} checks passed")
    return 1 if check.failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:5000")
    parser.add_argument("--shots")
    options = parser.parse_args()
    sys.exit(run(options.url, options.shots))
