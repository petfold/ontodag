# Windows test round 3

Round 2 (2026-08-24) found 15 failures, **none of them a defect in the
library** — but two pointed at a real one, now fixed. This round has two
jobs: confirm the fixes on the machine that found them, and reach the parts
Windows has still never exercised.

Everything below is PowerShell, copy-pasteable. Where a command's *point* is
what it prints, the expected output is given — a difference is the finding,
so please paste what you actually got rather than summarising it.

Roughly 45 minutes for parts A–C, plus 20 for D if you have a browser free.

---

## 0. Start from the fixes

```powershell
cd C:\Users\bagoj\ontodag
git pull
python -m venv --clear .venv        # --clear matters: re-running over an
.\.venv\Scripts\Activate.ps1        # existing venv does NOT rebuild it
pip install --no-cache-dir -e ".[test]"
python --version
```

`--no-cache-dir` because round 2 hit a `Permission denied` under
`AppData\Local\pip\cache`. If it happens anyway, that is the wheel cache,
not us — `pip cache purge` clears it.

`[test]` now also installs pycryptodome (the encrypted-store tests were
failing for want of it, on your machine *and* in CI).

---

## A. The suite — the headline number

```powershell
python -m pytest -q -rs
```

**Expected: 0 failed.** Skips are fine and are the point of the round —
`-rs` prints a reason for each. Please paste the whole skip summary. The
reasons should only ever be of these kinds:

- `needs the Graphviz \`dot\` binary on PATH` (until part B)
- `needs dot2tex` / flask missing (both live in the `web` extra)
- `set BEE_API and BEE_BATCH…` (the live Bee tests — always skipped here)
- `Windows has no POSIX permission bits` (three of them; see A2)

**Anything else skipping is itself a finding** — a skip is a test that did
not run, and the whole risk of round 2 was tests that did not say what they
needed.

### A1. What changed, if you want to see it

The three previously-failing assertions were reading POSIX shapes into
platform-neutral behaviour (a leading `/` on an absolute path, `/` as a path
separator). They now ask `os.path.isabs` and `os.path.normpath`, so they
test the code rather than the platform.

### A2. The one that is a real limitation, not a test bug

`~\.ontodag\config` can hold `bee_signer`, a private key. On Linux and macOS
it is written `0600`. **On Windows that is not enforceable at all** —
`chmod` there toggles the read-only attribute and nothing else — so the file
is protected only by the ACL on your user profile. An administrator account
can read it. Those three tests now skip, and the guide says so; if you ever
put a real signing key on that machine, put it in `$env:BEE_SIGNER` instead.

---

## B. The bug round 2 actually found

`pip install "ontodag[viz]"` installs the *wrapper*; the `dot` program that
draws is a separate download. Before the fix, rendering imported fine and
then died inside graphviz with a thirty-line traceback.

### B1. Before installing Graphviz — the message

```powershell
odag put doc
odag visualize
```

**Expected: one line, then exit 1** (`$LASTEXITCODE` → `1`):

```
odag: rendering needs the Graphviz system program `dot`, which pip does not install:
  sudo apt install graphviz     # or: brew install graphviz
  winget install graphviz       # on Windows, then check `dot -V` in a NEW shell
(the `graphviz` package is only a wrapper — `dot` does the drawing. Nothing else needs it: only pictures fail.)
```

**A traceback here is a failure of the fix.** Note whether the winget line
is actually the right command on your machine — I could not verify the
package id from here, and a wrong command in an error message is worse than
none.

### B2. Install it, then check the picture is real

```powershell
winget install graphviz          # or the installer from graphviz.org
# NEW shell, then:
dot -V
.\.venv\Scripts\Activate.ps1
odag visualize
```

Open the PNG it names. **Look at it.** A file existing is not a pass — round
1 of the web work recorded an 83×59 pixel squiggle as a success.

### B3. Re-run the suite with `dot` present

```powershell
python -m pytest -q -rs
```

The four rendering tests and the graphviz consumer test should now **run**,
not skip. Expected: 0 failed, and the `dot` reasons gone from the skip list.

---

## C. What Windows has never been asked to do

These are the interesting ones. C1 and C4 are where I would bet on finding
something.

### C1. Text encoding, in both directions

Round 2 established that `odag get … > out.txt` mangles accented text and
`-o FILE` does not. That is PowerShell re-decoding our output with the
console codepage, not us. **What was never tested is the way back in**, and
it goes through the same machinery:

```powershell
odag put "árvíztűrő tükörfúrógép"
odag put "dokumentum" "árvíztűrő tükörfúrógép"
odag list -o names.txt
Get-Content names.txt -Encoding UTF8          # should read back correctly

# Now the input side — two routes, both should end up with the same names:
odag export store1.od
odag -f fresh1.od import store1.od
odag -f fresh1.od list -o back1.txt
Get-Content back1.txt -Encoding UTF8

# ...and the untested direction: text arriving on STDIN. `odag` with no
# command reads a batch of commands, so this is the input path in full:
"put ékezetes`nput másik ékezetes`nlist" | odag -f fresh2.od
odag -f fresh2.od list -o back2.txt
Get-Content back2.txt -Encoding UTF8
```

**What to report:** whether an accented name survives a round trip through
each route, and whether any of them raises a `UnicodeEncodeError` /
`UnicodeDecodeError`. A crash there is a real bug; mojibake through `>` is
the documented PowerShell behaviour.

### C2. Paths that are ordinary on Windows and awkward everywhere else

```powershell
odag -f "C:\Users\bagoj\My Documents\trips.od" put doc      # a space
odag -f "C:\Users\bagoj\ékezetes\trips.od" put doc          # an accent
odag -f rs:"C:\Users\bagoj\rsstore" put doc
odag -f rs:"C:\Users\bagoj\rsstore" list
odag set store rs:C:\Users\bagoj\rsstore
odag set                                    # what did it persist?
# NEW shell — does the setting survive, and mean the same thing?
odag list
```

**What to report:** the exact string `odag set` printed for `store`, and
whether the new shell found the same store. The spec is absolutised when
saved; on Windows that means a drive letter, which is the case the old test
could not express.

Then the long-path case, because `rs:` stores shard blobs into
subdirectories and Windows has a 260-character limit unless it is turned
off:

```powershell
$deep = "C:\Users\bagoj\" + ("verylongdirectoryname\" * 8) + "store"
odag -f "rs:$deep" put doc
odag -f "rs:$deep" list
```

### C3. Encrypted stores (new in `[test]` since round 2)

```powershell
$env:ONTODAG_STORE_KEY = "correct horse battery staple"
odag -f rs:C:\Users\bagoj\secretstore put Zebra
odag -f rs:C:\Users\bagoj\secretstore list
$env:ONTODAG_STORE_KEY = "wrong key"
odag -f rs:C:\Users\bagoj\secretstore list      # must REFUSE, not print junk
Remove-Item Env:\ONTODAG_STORE_KEY
odag -f rs:C:\Users\bagoj\secretstore list      # must refuse too
```

**Expected:** the last two refuse with a message about the key. Serving
garbage, or an empty list, would be the bug.

### C4. Is the terminal a terminal?

Two behaviours ask that question, and neither has ever been asked it on
Windows: friendly rendering (`time(2026)` instead of the 46-character
timestamp range) and the 50-line display cap. Both are on at a terminal and
off in a pipe, so that `odag get | odag put` round-trips.

```powershell
odag prelude
odag put "meeting" "time(2026)"
odag get "time(2026)"            # a terminal: expect the SHORT spelling
odag get "time(2026)" | Out-String   # a pipe: expect the canonical form

# the cap:
1..60 | ForEach-Object { odag put "item$_" }
odag get                         # expect 50 lines + a note on stderr
odag get -n 0                    # expect all of them
odag count                       # expect the complete number, never capped
```

**What to report:** whether the terminal/pipe distinction works at all in
PowerShell. If both come out canonical, or both come out rendered, that is a
real finding — `isatty` behaves differently there and nothing has ever
checked it.

### C5. The interactive prompt

```powershell
odag
```

Then at the `>` prompt: `put a`, `get a`, `?` (an alias for `below`),
`help`, `Ctrl-C`, `Ctrl-D` or `exit`. **What to report:** whether the prompt
appears at all, whether Ctrl-C leaves you at the shell cleanly, and whether
anything about it is unusable in the PowerShell window (line editing,
history, accented input).

### C6. Undo, and file replacement while things are open

Windows will not let you replace a file another handle has open, which is
the classic way a store's pointer write fails there.

```powershell
# -m is a LEADING flag: it labels whatever this invocation commits.
odag -f rs:C:\Users\bagoj\histstore -m "first" put a
odag -f rs:C:\Users\bagoj\histstore -m "second" put b
odag -f rs:C:\Users\bagoj\histstore history
odag -f rs:C:\Users\bagoj\histstore undo
odag -f rs:C:\Users\bagoj\histstore list        # b should be gone
odag -f rs:C:\Users\bagoj\histstore redo
```

### C7. The big untested risk: the Swarm extra

Nobody has ever tried this on Windows. `swarm-bee` needs `coincurve`, a
compiled secp256k1 binding.

```powershell
pip install --no-cache-dir "ontodag[swarm]"
```

**What to report:** whether it installs at all, and if not, the *first*
error (usually "Microsoft Visual C++ 14.0 or greater is required" or a
missing `coincurve` wheel). Then, whether it fails cleanly:

```powershell
odag swarm            # the doctor — should say what is missing, not crash
```

You do not need a Bee node. `odag swarm` is meant to be useful precisely
when there is nothing to talk to.

---

## D. The web app in a real browser

Only if you have the time — but it is worth it, because a browser has found
things HTTP checks could not three times now (the standing rule from
2026-08-02: **a 200 is not a pass**; two of those bugs returned a perfectly
valid PNG).

```powershell
pip install --no-cache-dir -e ".[test,web]"
odag web
```

Then at <http://127.0.0.1:5000/>:

1. Type `put Japan` in the console; the browse pane should update.
2. Click a category in the browse pane — the command it wrote should appear
   in the console, and the breadcrumb should be the query.
3. Click a node in the picture (focus), then use the breadcrumb to go back.
4. Type an accented name (`ékezetes`) and query for it — this is the URL
   encoding path.
5. Query for something with a `+` or `&` in the name.
6. Open `/classic` and try Add Item, Move Item, Delete + Contents, and a
   query export with **with context** ticked.
7. `/market` — the car demo; intersect Budget with ElectricVehicle.

**Report the browser's console errors** (F12 → Console) even if the page
looks right. And if any picture fails to draw, note whether the page said
something useful — the fix in part B should make a missing `dot` a 501 with
an instruction rather than a 500.

---

## How to report

For each part: what you ran, what you got. For failures, the whole pytest
block (the `FAILED …` summary lines are enough if there are many). Please
include:

```powershell
python --version
pip --version
[System.Environment]::OSVersion.Version
[Console]::OutputEncoding.WebName        # for part C1
$PSVersionTable.PSVersion                # 5.1 and 7.x behave differently
```

That last one matters more than it looks: Windows PowerShell 5.1 and
PowerShell 7 differ in exactly the redirection and encoding behaviour part
C1 is about, and round 2 was run on 5.1.
