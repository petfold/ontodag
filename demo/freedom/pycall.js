// Calling Python from a page whose Python reads Swarm (BROWSER.md §15).
//
// Python's store calls are synchronous; Swarm reads are promises. Two ways:
// - "jspi": Python blocks on swarm.js's promises (pyodide.ffi.run_sync),
//   which works only for a call that entered Python asynchronously
//   (callPromising), and only where JSPI can suspend it;
// - "retry": where it cannot (Pyodide on iOS calls function pointers through
//   a JavaScript trampoline, and JSPI will not suspend across a JavaScript
//   frame), Python reads only blobs already fetched; a call that needs more
//   answers {need: [refs]} (ontodag.browser.RETRY, NeedBlobs), and the page
//   fetches them and runs the call again.
//
// loopmarket's page copies this file in (its build.py), as it does swarm.js.

const SUSPEND_FAILED = /Suspending|promising|suspend/i;

export class PythonCalls {
  // py: the Pyodide instance; blobs: swarm.js's BlobStore; onRetry: called
  // (async) when a call shows JSPI refusing, after which every call retries.
  constructor(py, blobs, { onRetry = async () => {} } = {}) {
    this.py = py;
    this.blobs = blobs;
    this.onRetry = onRetry;
    this.mode = "jspi";
  }

  // Pick the mode, without trying a suspension (a failed one is fatal to
  // Pyodide): ?bridge= names one; without WebAssembly.Suspending there is no
  // JSPI; and where Pyodide calls function pointers through its JavaScript
  // trampoline (its count-args helper is 0: on iOS, or without wasm-gc),
  // JSPI cannot suspend Python either.
  choose(named) {
    if (named === "retry" || named === "jspi") return (this.mode = named);
    if (!("Suspending" in WebAssembly)) return (this.mode = "retry");
    const module = this.py._module;
    if (module && module._PyEM_CountArgsPtr === 0) return (this.mode = "retry");
    return (this.mode = "jspi");
  }

  // The answer (JSON) of the Python function `name`.
  async call(name, ...args) {
    if (this.mode === "retry") this.blobs.forgetFailures();
    for (let run = 1; ; run++) {
      const fn = this.py.globals.get(name);
      let answer;
      try {
        answer = JSON.parse(this.mode === "jspi" ? await fn.callPromising(...args) : fn(...args));
      } catch (e) {
        // JSPI chosen but refused by a real call (where that is not fatal): retry from now on.
        if (this.mode !== "jspi" || !SUSPEND_FAILED.test(String(e && e.message))) throw e;
        console.warn("JSPI refused a call; reading by retrying from now on", e);
        this.mode = "retry";
        await this.onRetry();
        continue;
      } finally {
        fn.destroy();
      }
      if (!answer || !Array.isArray(answer.need)) return answer;
      if (run > 5000) throw new Error("the page kept needing more of the store; giving up");
      await this.blobs.fetch(answer.need);
    }
  }
}
