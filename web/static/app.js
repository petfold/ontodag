/* OntoDAG — the browse-and-type interface.
 *
 * The design rule this file exists to implement (docs/plans/WEB_UI.md §3):
 *
 *   Every click writes its command into the console;
 *   every command updates the browse state.
 *
 * They are two inputs to one state, not two interfaces. That works here
 * because in OntoDAG a path IS a query: clicking a category to drill down
 * does not navigate somewhere else, it appends a term to a conjunction. So a
 * click is literally spelled `get Japan Flight`, and the console shows it —
 * which makes pointing at things the cheapest possible way to learn the
 * language, and means the two halves cannot drift.
 *
 * Preact + htm, vendored, no build step (see static/vendor/README.md).
 */
import { html, render, useState, useEffect, useRef, useCallback }
  from "/static/vendor/preact-htm.module.js";

/* ---------------------------------------------------------------- helpers */

/* Names are arbitrary text: `&`, `#` or `+` in one would split the query
 * string, truncate it, or arrive as a space. `,` and `|` are the separators,
 * so each term is encoded and they are joined afterwards. */
const catParam = (query) =>
  query.map((terms) => terms.map(encodeURIComponent).join(",")).join("|");

const isEmpty = (query) => query.length === 1 && query[0].length === 0;

/* The command a query spells. `get` with no terms is the empty query, which
 * is everything — the same one code path as `list` (see the empty-query work
 * in the core), which is why this page has one result list and not two. */
const queryLine = (query) =>
  isEmpty(query) ? "get" : "get " + query.map(quoteAll).join(" or ");

const quoteAll = (terms) => terms.map(quote).join(" ");
const quote = (term) => (/[\s"']/.test(term) ? JSON.stringify(term) : term);

/* The other direction of the rule: a `get` typed into the console moves the
 * breadcrumb. Flags are left alone — a line with `-n` or `--raw` still runs,
 * it just does not claim to be navigation. */
function queryOfLine(line) {
  let tokens;
  try {
    tokens = line.match(/"[^"]*"|'[^']*'|\S+/g) || [];
  } catch { return null; }
  if (!tokens.length || tokens[0] !== "get") return null;
  const args = tokens.slice(1).map((t) =>
    /^["']/.test(t) ? t.slice(1, -1) : t);
  if (args.some((a) => a.startsWith("-"))) return null;
  const query = [[]];
  for (const arg of args) {
    if (arg === "or") query.push([]);
    else query[query.length - 1].push(arg);
  }
  return query.some((d) => d.length === 0) && query.length > 1 ? null : query;
}

/* htm does not decode HTML entities, so `&gt;` in a template arrives on
 * screen as the four characters someone typed. Found by looking at the page,
 * which is the only way this class of bug is ever found. */
const PROMPT = ">";

const post = (url, body) =>
  fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => r.json());

/* ------------------------------------------------------------------ chrome */

function IdentityBar({ state, onReset, onExample, query }) {
  const cat = catParam(query);
  return html`
    <header class="bar">
      <span class="brand">OntoDAG</span>
      <span class="pill" title="This page's DAG lives in server memory for
your session: no store, no root, no Swarm. Pointing it at a real store is
docs/plans/WEB_UI.md §8a.">sandbox</span>
      <span class="stat"><b>${state.items ?? 0}</b> items</span>
      <span class="stat">registry ${state.registry ?? "?"}</span>
      <span class="spacer"></span>
      <details class="menu">
        <summary>Download</summary>
        <div class="menu-body">
          <p>Everything</p>
          ${["export", "export/omn", "export/dot", "export/tex"].map(
            (p, i) => html`<a href="/dag/${p}">${
              ["OWL", "Manchester", "DOT", "LaTeX"][i]}</a>`)}
          <p>This query${isEmpty(query) ? " (= everything)" : ""}</p>
          ${["export", "export/omn", "export/dot", "export/tex"].map(
            (p, i) => html`<a href="/dag/query/${p}?cat=${cat}&context=1">${
              ["OWL", "Manchester", "DOT", "LaTeX"][i]}</a>`)}
          <small>Query downloads are the <b>excerpt</b> with its context —
          the answer and the categories it hangs from, never the question.</small>
        </div>
      </details>
      <button onClick=${onExample} title="Load a small worked example">Example</button>
      <button onClick=${onReset} title="Throw this DAG away and start empty">Empty</button>
      <a class="classic" href="/classic">classic page</a>
    </header>`;
}

function Breadcrumb({ query, onNavigate }) {
  const single = query.length === 1;
  return html`
    <nav class="crumbs">
      <button class="crumb root" onClick=${() => onNavigate([[]])}
              title="Everything — the empty query">✱</button>
      ${query.map((terms, d) => html`
        ${d > 0 && html`<span class="or">or</span>`}
        ${terms.map((term) => html`
          <span class="crumb">
            ${term}
            ${single && html`<button class="x" title="Drop this term"
              onClick=${() => onNavigate([query[0].filter((t) => t !== term)])}
              >✕</button>`}
          </span>`)}`)}
      ${!single && html`<button class="crumb x-all"
        onClick=${() => onNavigate([[]])} title="Clear the union">✕</button>`}
    </nav>`;
}

/* -------------------------------------------------------------- the browse */

function Refine({ state, query, onNavigate }) {
  const [showVocab, setShowVocab] = useState(false);
  const all = state.refine || [];
  const things = all.filter((r) => !r.vocab);
  const vocab = all.filter((r) => r.vocab);
  const shown = showVocab ? things.concat(vocab) : things;

  /* Narrowing a union narrows every branch of it: (A or B) and C is
   * (A and C) or (B and C). So the term is appended to each disjunct. */
  const narrow = (name) => onNavigate(query.map((terms) => [...terms, name]));

  return html`
    <section class="pane refine">
      <h2>Refine by</h2>
      ${!all.length && html`<p class="empty">Nothing further divides this
        ${state.count === 1 ? "single item" : "answer"}.</p>`}
      <ul>
        ${shown.map((r) => html`
          <li><button onClick=${() => narrow(r.name)}
                      class=${r.vocab ? "vocab" : ""}>
            <span class="name">${r.display}</span>
            <span class="n">${r.matching}</span>
          </button></li>`)}
      </ul>
      ${vocab.length > 0 && html`
        <button class="link" onClick=${() => setShowVocab(!showVocab)}>
          ${showVocab ? "hide" : "show"} ${vocab.length} vocabulary
        </button>`}
      ${state.sampled && html`<p class="note">Choices computed from a sample
        of the answer — there may be more.</p>`}
    </section>`;
}

function Here({ state, focus, onFocus }) {
  const [showVocab, setShowVocab] = useState(false);
  const all = state.here || [];
  const things = all.filter((h) => !h.vocab);
  const vocab = all.filter((h) => h.vocab);
  const shown = showVocab ? things.concat(vocab) : things;

  return html`
    <section class="pane here">
      <h2>Here <span class="n">${state.count ?? 0}</span></h2>
      ${!all.length && html`<p class="empty">Nothing matches.</p>`}
      <ul>
        ${shown.map((h) => html`
          <li><button onClick=${() => onFocus(h.name)}
                class=${(h.name === focus ? "on " : "") + (h.vocab ? "vocab" : "")}>
            <span class="icon">${h.children ? "▸" : "·"}</span>
            <span class="name">${h.display}</span>
            ${h.count > 0 && html`<span class="n">${h.count}</span>`}
          </button></li>`)}
      </ul>
      ${vocab.length > 0 && html`
        <button class="link" onClick=${() => setShowVocab(!showVocab)}>
          ${showVocab ? "hide" : "show"} ${vocab.length} vocabulary
        </button>`}
    </section>`;
}

/* --------------------------------------------------------------- the focus */

function Picture({ query, focus, onFocus, epoch }) {
  const [state, setState] = useState({ loading: true });
  const box = useRef(null);

  /* `epoch` is in the dependencies because the query and the focus are not
   * the only things that change the picture: a `put`, a `remove`, a `move`,
   * loading the example — none of them touch either, and without this the
   * drawing silently stayed as it was. The classic page redrew after every
   * mutation by reflex, which is wasteful but was never wrong. */
  useEffect(() => {
    let live = true;
    const url = focus
      ? `/dag/picture?focus=${encodeURIComponent(focus)}&depth=1`
      : `/dag/picture?cat=${catParam(query)}`;
    setState({ loading: true });
    fetch(url).then((r) => r.json()).then((data) => {
      if (live) setState({ ...data, loading: false });
    }).catch(() => live && setState({ error: "could not draw", loading: false }));
    return () => { live = false; };
  }, [focus, JSON.stringify(query), epoch]);

  /* Graphviz writes viz.py's synthetic ids into the SVG as each shape's
   * <title>, so click-to-focus is one delegated handler and no graph
   * library. The ids map them back to names, which the labels could not:
   * labels carry counts and are rendered rather than canonical. */
  const click = useCallback((event) => {
    const group = event.target.closest("g.node");
    if (!group || !state.ids) return;
    const name = state.ids[group.querySelector("title")?.textContent];
    if (name) onFocus(name);
  }, [state.ids, onFocus]);

  if (state.loading) return html`<div class="picture loading">drawing…</div>`;
  if (state.error) return html`<div class="picture note">${state.error}</div>`;
  return html`<div class="picture" ref=${box} onClick=${click}
                   dangerouslySetInnerHTML=${{ __html: state.svg }}></div>`;
}

function Focus({ name, query, onFocus, onRun, onMenu, epoch }) {
  const [detail, setDetail] = useState(null);

  useEffect(() => {
    if (!name) return setDetail(null);
    let live = true;
    fetch(`/dag/node/${encodeURIComponent(name)}`)
      .then((r) => r.json())
      .then((d) => live && setDetail(d.error ? null : d));
    return () => { live = false; };
  }, [name]);

  if (!name) {
    return html`
      <aside class="pane focus">
        <h2>Nothing selected</h2>
        <p class="empty">Pick something on the left, or click a shape in the
        picture. Every click is echoed in the console as the command it means.</p>
        ${/* The whole store drawn at thumbnail size is a squiggle: legible
              for the twelve-node example and useless past it, which is the
              thing the classic page did on every keystroke. A picture is
              worth drawing when it is *scoped* — to a query, or to one
              item's neighbourhood — so with neither, draw nothing. */
          !isEmpty(query) && html`
            <${Picture} query=${query} focus=${null} onFocus=${onFocus}
                        epoch=${epoch} />`}
      </aside>`;
  }

  const ask = (line) => onRun(line);
  return html`
    <aside class="pane focus">
      <h2>${detail?.display ?? name}</h2>
      ${detail && detail.display !== detail.name &&
        html`<p class="canon">stored as <code>${detail.name}</code></p>`}
      ${detail && html`
        <dl>
          <dt>above</dt>
          <dd>${detail.above.length
            ? detail.above.map((p) => html`
                <button class="chip" onClick=${() => onFocus(p.name)}>${p.display}</button>`)
            : html`<span class="empty">top level</span>`}</dd>
          <dt>below</dt>
          <dd>${detail.below.length
            ? detail.below.map((c) => html`
                <button class="chip" onClick=${() => onFocus(c.name)}>${c.display}</button>`)
            : html`<span class="empty">nothing</span>`}</dd>
          <dt>under it</dt>
          <dd>${detail.count}</dd>
        </dl>
        <div class="actions">
          <button onClick=${() => ask(`get ${quote(name)}`)}>Everything under it</button>
          <button onClick=${() => ask(`put ${quote(name)} `)}>File under…</button>
          <button onClick=${() => ask(`move ${quote(name)} --to `)}>Move…</button>
          <button class="danger" onClick=${() => ask(`remove ${quote(name)}`)}>Remove</button>
          <button onClick=${onMenu} title="Everything else you can do with this"
                  >more…</button>
        </div>`}
      <${Picture} query=${query} focus=${name} onFocus=${onFocus}
                  epoch=${epoch} />
    </aside>`;
}

/* ------------------------------------------------------------- the console */

/* One suggestion list, contextual: the commands while you are typing the
 * verb, this store's names once you are past it.
 *
 * It is a *menu* as much as a completion — someone who has never met the
 * command language can open it and read what there is, which is the one
 * thing a console cannot do for itself. Making it the same list that
 * completion uses is what keeps it from costing a permanent menu bar: it is
 * on screen only while it is being used. */
function Suggestions({ items, selected, onPick }) {
  if (!items.length) return null;
  return html`
    <div class="suggest">
      ${items.map((item, i) => html`
        <button class=${"option" + (i === selected ? " on" : "")}
                onMouseDown=${(e) => { e.preventDefault(); onPick(item); }}>
          <span class="key">${item.name}</span>
          ${item.args && html`<span class="args">${item.args}</span>`}
          ${item.help && html`<span class="what">${item.help}</span>`}
        </button>`)}
    </div>`;
}

function Console({ transcript, onRun, onFocus, pending, subject, openMenu }) {
  const [line, setLine] = useState("");
  const [past, setPast] = useState([]);
  const [at, setAt] = useState(-1);
  const [menu, setMenu] = useState([]);
  const [items, setItems] = useState([]);
  const [selected, setSelected] = useState(0);
  const [dismissed, setDismissed] = useState(false);
  /* Asked for explicitly (the button, or Tab), as opposed to appearing
     because a verb is half-typed. */
  const [forced, setForced] = useState(false);
  const scroll = useRef(null);
  const input = useRef(null);

  useEffect(() => {
    fetch("/dag/commands").then((r) => r.json())
      .then((data) => setMenu(data.commands));
  }, []);

  useEffect(() => {
    if (scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight;
  }, [transcript.length, items.length, pending]);

  /* The verb is still being typed while no space has been entered. That is
   * the only moment the command list is useful, so it is the only moment it
   * appears — and once you know the language you never see it. */
  const typingVerb = !line.includes(" ");

  const commandsFor = (word) =>
    menu.filter((command) => command.name.startsWith(word.toLowerCase()));

  useEffect(() => {
    /* An EMPTY line does not open the menu by itself. It used to, and the
       consequence was worse than clutter: clear your line, press Enter, and
       the highlighted command was silently inserted instead of nothing
       happening. A menu that appears when you are not asking anything is
       also a menu in the way. */
    const word = line.trim();
    if (dismissed || !typingVerb || (!word && !forced)) return setItems([]);
    const matches = commandsFor(word);
    setItems(matches.length === 1 && matches[0].name === word ? [] : matches);
    setSelected(0);
  }, [line, menu, dismissed, forced]);

  const show = () => {
    setDismissed(false);
    setForced(true);
    setSelected(0);
    input.current?.focus();
  };

  /* Opening the menu from elsewhere on the page (the focus pane's "…") means
   * "what can I do with THIS", so the verb arrives with the item attached. */
  useEffect(() => {
    if (openMenu) show();
  }, [openMenu]);

  const pick = (item) => {
    if (item.kind === "name") {
      const parts = line.split(/\s+/);
      parts[parts.length - 1] = quote(item.name);
      setLine(parts.join(" ") + " ");
    } else {
      const withItem = item.takes_item && subject
        ? `${item.name} ${quote(subject)} ` : `${item.name} `;
      setLine(item.args || item.flags?.length ? withItem : item.name);
      if (!item.args && !item.flags?.length) return submit(item.name);
    }
    setItems([]);
    setForced(false);
    input.current?.focus();
  };

  const submit = (text) => {
    const value = (text ?? line).trim();
    if (!value) return;
    setPast([value, ...past]);
    setAt(-1);
    setLine("");
    setItems([]);
    setDismissed(false);
    setForced(false);
    onRun(value);
  };

  /* Past the verb, Tab asks the store for names — deliberately on demand
   * rather than as you type, since it is a round trip and the answer is
   * rarely short. */
  const completeName = async () => {
    const parts = line.split(/\s+/);
    const word = parts[parts.length - 1] || "";
    const { names } = await fetch(
      `/dag/names?prefix=${encodeURIComponent(word)}`).then((r) => r.json());
    if (names.length === 1) {
      parts[parts.length - 1] = quote(names[0]);
      setLine(parts.join(" ") + " ");
      setItems([]);
    } else {
      setItems(names.slice(0, 12).map((name) => ({ name, kind: "name" })));
      setSelected(0);
    }
  };

  const key = (event) => {
    const open = items.length > 0;
    if (event.key === "Escape") {
      setItems([]); setDismissed(true); setForced(false);
    } else if (event.key === "Enter") {
      event.preventDefault();
      open && items[selected] ? pick(items[selected]) : submit();
    } else if (event.key === "Tab") {
      event.preventDefault();
      if (open && items[selected]) pick(items[selected]);
      else if (!typingVerb) completeName();
      else show();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      // The list when it is open, the history when it is not — the usual
      // bargain, and the reason Escape has to close it.
      if (open) setSelected((i) => Math.max(0, i - 1));
      else if (past.length) {
        const next = Math.min(at + 1, past.length - 1);
        setAt(next); setLine(past[next]);
      }
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      if (open) setSelected((i) => Math.min(items.length - 1, i + 1));
      else { const next = at - 1; setAt(next); setLine(next < 0 ? "" : past[next]); }
    }
  };

  return html`
    <section class="console">
      <div class="transcript" ref=${scroll}>
        ${transcript.map((entry, i) => html`
          <div class="entry" key=${i}>
            ${/* A welcome is not something anybody typed, so it does not get
                  a prompt in front of it. */
              entry.line && html`
                <div class="cmd"><span class="prompt">${PROMPT}</span> ${entry.line}</div>`}
            ${entry.out && html`<${Output} text=${entry.out} onFocus=${onFocus} />`}
            ${entry.err && html`<pre class=${entry.code ? "err" : "note"}>${entry.err}</pre>`}
          </div>`)}
        ${pending && html`<div class="entry pending">…</div>`}
      </div>
      <${Suggestions} items=${items} selected=${selected} onPick=${pick} />
      <div class="input">
        <span class="prompt">${PROMPT}</span>
        <input ref=${input} value=${line} spellcheck="false" autocomplete="off"
               autofocus onInput=${(e) => setLine(e.target.value)}
               onKeyDown=${key}
               placeholder=${subject ? `type a command, or pick one for ${subject}`
                                     : "type a command, or pick one from the list"} />
        <button class="show-menu" onClick=${show} title="What can I type here?"
                >commands ▾</button>
      </div>
    </section>`;
}

/* Result lines are names; making them clickable is what joins the console
 * back to the browse pane. Anything that is not a bare name (a note, a table
 * from `show`) is left as text. */
function clickable(lines, onFocus) {
  return lines.map((line, i) => {
    const plain = /^[^\s]+$/.test(line);
    return html`${i > 0 && "\n"}${plain
      ? html`<button class="line-name" onClick=${() => onFocus(line)}>${line}</button>`
      : line}`;
  });
}

/* How much of a command's output to show.
 *
 * A `get` prints its answer — which is already the middle pane, in a form
 * you can click. Repeating thirty names underneath is noise that pushes the
 * thing you actually typed off the top of the console. So long output folds
 * to its first few lines and says how many it kept back; the fold opens if
 * you want it. The console's job is what you DID; the panes' job is what is
 * there. */
const FOLD_AT = 6;

function Output({ text, onFocus }) {
  const [open, setOpen] = useState(false);
  const lines = text.replace(/\n$/, "").split("\n");
  if (lines.length <= FOLD_AT || open) {
    return html`<pre class="out">${clickable(lines, onFocus)}${
      open && html`\n<button class="link" onClick=${() => setOpen(false)}
                    >fold</button>`}</pre>`;
  }
  return html`<pre class="out">${clickable(lines.slice(0, FOLD_AT), onFocus)}
<button class="link" onClick=${() => setOpen(true)}
        >${lines.length - FOLD_AT} more…</button></pre>`;
}

/* ------------------------------------------------------------------- shell */

function App() {
  const [state, setState] = useState({});
  const [query, setQuery] = useState([[]]);
  const [focus, setFocus] = useState(null);
  const [transcript, setTranscript] = useState([]);
  const [pending, setPending] = useState(false);
  const [drop, setDrop] = useState(false);
  /* Bumped whenever the store may have changed, so the picture redraws. */
  const [epoch, setEpoch] = useState(0);
  /* Bumped to ask the console to show its command list. */
  const [openMenu, setOpenMenu] = useState(0);

  /* One path for everything: a click and a typed line both come through
   * here, so the transcript is a true record and the two halves cannot
   * disagree about what happened. */
  const run = useCallback(async (line, forQuery) => {
    const target = forQuery ?? query;
    setPending(true);
    const answer = await post(
      `/dag/console?cat=${catParam(target)}`, { line });
    setPending(false);
    setTranscript((t) => [...t, { line, out: answer.out, err: answer.err,
                                  code: answer.code }].slice(-100));
    setState(answer);
    setEpoch((n) => n + 1);
    /* ...and the reverse direction: a `get` typed by hand moves the
     * breadcrumb, so the panes never describe a different query. */
    const typed = queryOfLine(line);
    if (typed && !forQuery) setQuery(typed);
    return answer;
  }, [query]);

  const navigate = useCallback((next) => {
    setQuery(next);
    setFocus(null);
    run(queryLine(next), next);
  }, [run]);

  const refresh = useCallback(() => {
    fetch(`/dag/browse?cat=${catParam(query)}`)
      .then((r) => r.json()).then(setState);
    setEpoch((n) => n + 1);
  }, [query]);

  /* Openings matter. Rather than dump the whole store into the transcript,
   * show three commands built from what is actually in this store — a
   * console is only unfriendly while you cannot see what to type. */
  const welcome = (view) => {
    const pick = (view.here || []).filter((h) => !h.vocab && h.children);
    const one = pick[0]?.name, two = pick[1]?.name;
    setTranscript([{
      line: null,
      out: [
        "Click things on the left — every click is echoed here as the",
        "command it means, so you can start typing them instead.",
        "",
        ...(one ? [`  get ${quote(one)}`] : []),
        ...(one && two ? [`  get ${quote(one)} ${quote(two)}`,
                          `  below ${quote(two)} ${quote(one)}`] : []),
        "  put my-note.txt " + (one ? quote(one) : ""),
        "  help",
        "",
      ].join("\n") + "\n",
      err: "", code: 0,
    }]);
  };

  useEffect(() => {
    /* First visit: an empty `*` is the worst first impression this system
     * can make — nothing to click and nothing for the browse pane to teach
     * with — so a store with nothing in it gets the worked example. */
    fetch("/dag/browse").then((r) => r.json()).then((first) => {
      if (first.items === 0) {
        post("/dag/example", {})
          .then(() => fetch("/dag/browse").then((r) => r.json()))
          .then((view) => { setState(view); welcome(view); setEpoch(1); });
      } else {
        setState(first);
        welcome(first);
      }
    });
  }, []);

  const example = () => post("/dag/example", {}).then(() => navigate([[]]));
  const reset = () => post("/dag", {}).then(() => {
    setTranscript([]);
    navigate([[]]);
  });

  const dropped = async (event) => {
    event.preventDefault();
    setDrop(false);
    const file = event.dataTransfer.files[0];
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    const answer = await fetch("/dag/import", { method: "POST", body: form })
      .then((r) => r.json());
    setTranscript((t) => [...t, {
      line: `import ${file.name}`,
      out: answer.message ? answer.message + "\n" : "",
      err: answer.error ? "odag: " + answer.error + "\n" : "",
      code: answer.error ? 1 : 0,
    }]);
    refresh();
  };

  return html`
    <div class=${"shell" + (drop ? " dropping" : "")}
         onDragOver=${(e) => { e.preventDefault(); setDrop(true); }}
         onDragLeave=${() => setDrop(false)}
         onDrop=${dropped}>
      <${IdentityBar} state=${state} query=${query}
                      onReset=${reset} onExample=${example} />
      <${Breadcrumb} query=${query} onNavigate=${navigate} />
      <main>
        <${Refine} state=${state} query=${query} onNavigate=${navigate} />
        <${Here} state=${state} focus=${focus} onFocus=${setFocus} />
        <${Focus} name=${focus} query=${query} onFocus=${setFocus}
                  epoch=${epoch} onMenu=${() => setOpenMenu((n) => n + 1)}
                  onRun=${(line) => {
                    if (line.endsWith(" ")) {
                      const box = document.querySelector(".console input");
                      box.value = line; box.focus();
                      box.dispatchEvent(new Event("input", { bubbles: true }));
                    } else run(line).then(refresh);
                  }} />
      </main>
      <${Console} transcript=${transcript} pending=${pending}
                  subject=${focus} openMenu=${openMenu}
                  onRun=${(line) => run(line)} onFocus=${setFocus} />
      ${drop && html`<div class="dropzone">drop to import</div>`}
    </div>`;
}

render(html`<${App} />`, document.getElementById("app"));
