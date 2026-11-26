/*
 * Rental Matcher: the panel (v1.26; v1.32: in Chrome's side panel; v1.33:
 * docked over the page you're on again).
 *
 * Its own shadow DOM, in the user's language and direction: docked left in
 * English, right in Hebrew, with a border, and as wide as you drag its
 * inner edge (`resizable`, v1.33). The toolbar button puts it on the tab
 * you're on (overlay.js); where Chrome doesn't let an extension onto a
 * page, Chrome's side panel shows the same panel (sidepanel.html,
 * `embedded`). Listing cards come from cards.js; everything from a listing
 * is put in as text, never HTML.
 */
(function (root) {
  "use strict";

  const CSS = `
  :host { all: initial; }
  * { box-sizing: border-box; font-family: system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif; }
  .wrap { unicode-bidi: isolate; }
  .fab { position: fixed; inset-inline-start: 16px; bottom: 16px; z-index: 2147483646; background: #1f6feb; color: #fff; border: 0;
    border-radius: 999px; padding: 10px 16px; font-size: 14px; font-weight: 600; cursor: pointer; box-shadow: 0 4px 14px rgba(31,111,235,.35); }
  .fab[hidden] { display: none; }
  .panel { position: fixed; inset-inline-start: 0; top: 0; bottom: 0; width: min(var(--w, 440px), 100vw); z-index: 2147483647; background: #f6f7f9;
    color: #1d2125; box-shadow: 0 0 24px rgba(16,24,40,.18); display: flex; flex-direction: column; font-size: 13px; line-height: 1.45;
    transition: width .2s ease; border-inline-end: 1px solid #c9d1d9; }
  .panel.sizing { transition: none; user-select: none; }
  /* v1.33: drag the inner edge to make it wider or narrower */
  .grip { position: absolute; top: 0; bottom: 0; inset-inline-end: -5px; width: 10px; cursor: ew-resize; z-index: 3; }
  .grip::after { content: ""; position: absolute; top: 50%; inset-inline-start: 3px; width: 4px; height: 44px; margin-top: -22px; border-radius: 3px;
    background: #c9d1d9; opacity: 0; transition: opacity .15s; }
  .grip:hover::after, .panel.sizing .grip::after { opacity: 1; background: #1f6feb; }
  .panel.wide { --w: 880px; }
  .panel[hidden] { display: none; }
  header { background: #fff; padding: 12px 14px; border-bottom: 1px solid #e3e6ea; }
  .row { display: flex; align-items: center; gap: 6px; }
  .brand { display: flex; align-items: center; gap: 8px; flex: 1; font-size: 15px; font-weight: 700; }
  .brand i { width: 22px; height: 22px; border-radius: 6px; background: #1f6feb; display: inline-block; position: relative; }
  .brand i::after { content: ""; position: absolute; left: 5px; top: 6px; width: 12px; height: 10px; background: #fff;
    clip-path: polygon(50% 0, 100% 45%, 100% 100%, 0 100%, 0 45%); }
  .icon { border: 1px solid transparent; background: none; border-radius: 8px; height: 30px; min-width: 30px; padding: 0 8px; font-size: 13px;
    cursor: pointer; color: #3d444d; white-space: nowrap; }
  .icon:hover { background: #f1f3f5; border-color: #e3e6ea; }
  .icon.on { background: #eef4ff; color: #1f6feb; border-color: #c9dbff; }
  .go { margin-top: 10px; display: grid; grid-template-columns: auto 1fr; gap: 10px; align-items: center; }
  button.act { border: 1px solid #1f6feb; background: #1f6feb; color: #fff; border-radius: 8px; padding: 7px 16px; font-size: 14px;
    font-weight: 600; cursor: pointer; white-space: nowrap; }
  button.act.stop { background: #fff; color: #b42318; border-color: #e5a29b; }
  button.act[hidden] { display: none; }
  button.act:disabled { opacity: .5; cursor: default; }
  .status { color: #3d444d; }
  .status small { display: block; color: #6e7781; }
  .bar { height: 4px; background: #e3e6ea; border-radius: 2px; margin-top: 10px; overflow: hidden; }
  .bar > div { height: 100%; background: #1f6feb; width: 0; transition: width .3s; }
  .body { overflow-y: auto; flex: 1; padding: 12px 12px 24px; }
  .box { background: #fff; border: 1px solid #e3e6ea; border-radius: 12px; padding: 12px 14px; margin: 0 0 12px; }
  .box[hidden] { display: none; }
  .note { background: #fff8e6; border-color: #f0d58a; }
  .note.err { background: #fdecea; border-color: #f3b8b1; }
  .ycheck { background: #fff4e8; border: 2px solid #e8833a; }
  .ycheck strong { display: block; font-size: 14px; margin-bottom: 4px; }
  .sum { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  /* v1.41: the count, the view, the sort and "more options" stay in view while the list scrolls */
  .stick { position: sticky; top: -12px; z-index: 2; background: #f6f7f9; margin: -12px -12px 8px; padding: 12px 12px 8px;
    border-bottom: 1px solid transparent; }
  .stick.stuck { border-bottom-color: #e3e6ea; box-shadow: 0 4px 10px -8px rgba(16,24,40,.35); }
  .stick:empty, .stick.none { display: none; }
  .stick > div:empty { display: none; }
  .stick .sum + div:not(:empty) { margin-top: 8px; }
  .pill { border-radius: 999px; background: #fff; border: 1px solid #e3e6ea; padding: 3px 10px; font-size: 12px; color: #3d444d; }
  .pill.main { background: #e9f7ef; border-color: #b7e1c4; color: #1a7f37; font-weight: 600; }
  .sum .sp { flex: 1; }
  .seg { display: inline-flex; background: #eef1f5; border-radius: 9px; padding: 2px; }
  .seg button { border: 0; background: none; font: inherit; font-size: 12px; padding: 3px 10px; border-radius: 7px; cursor: pointer; color: #57606a; }
  .seg button.on { background: #fff; color: #1d2125; font-weight: 600; box-shadow: 0 1px 2px rgba(16,24,40,.12); }
  .grid .rm-simple { --ph-ratio: 16 / 10; }
  /* v1.32: in Chrome's side panel: the whole page, as wide as the user drags it */
  .panel.embedded { position: static; width: auto; height: 100vh; box-shadow: none; }
  .panel.embedded .grid, .panel.resizable .grid { grid-template-columns: repeat(auto-fill, minmax(min(100%, 340px), 1fr)); }
  .est { color: #57606a; font-size: 12px; margin-top: 6px; }
  .est small { display: block; color: #8a94a3; }
  .est[hidden] { display: none; }
  select { border: 1px solid #d0d7de; border-radius: 8px; padding: 4px 8px; font-size: 12px; background: #fff; color: #1d2125; font-family: inherit; }
  .h { font-size: 11px; font-weight: 600; letter-spacing: .05em; text-transform: uppercase; color: #6e7781; margin: 16px 2px 8px; }
  .grid { display: grid; grid-template-columns: 1fr; gap: 0 12px; align-items: start; }
  .panel.wide .grid { grid-template-columns: 1fr 1fr; }
  details.box > summary { cursor: pointer; font-weight: 600; list-style: none; }
  details.box > summary::before { content: "▸ "; color: #6e7781; }
  .wrap[dir=rtl] details.box > summary::before { content: "◂ "; }
  .wrap[dir=rtl] details.box[open] > summary::before { content: "▾ "; }
  details.box[open] > summary::before { content: "▾ "; }
  details.box[open] > summary { margin-bottom: 10px; }
  ul.plain { margin: 6px 0 0; padding-inline-start: 18px; }
  ul.plain li { margin: 2px 0; }
  a { color: #1f6feb; text-decoration: none; }
  a:hover { text-decoration: underline; }
  .muted { color: #6e7781; }
  .empty { text-align: center; color: #6e7781; padding: 24px 8px; }
  bdi { unicode-bidi: isolate; }
  `;

  const CSS_ESCAPE = (v) => (root.CSS && root.CSS.escape ? root.CSS.escape(v) : String(v).replace(/["\\]/g, "\\$&"));

  function create(doc, opts) {
    opts = opts || {};
    const Cards = opts.Cards || root.RentalCards;
    const I = opts.I || root.RentalI18n;
    const t = I.t;
    const host = doc.createElement("div");
    host.id = "rental-matcher-root";
    const sh = host.attachShadow({ mode: "open" });
    const el = (tag, cls, text) => {
      const e = doc.createElement(tag);
      if (cls) e.className = cls;
      if (text != null) e.textContent = String(text);
      return e;
    };
    // v1.34: a constructed stylesheet where the browser has them: a page's Content-Security-Policy can
    // refuse a <style> element added to it, and the panel now goes on any page
    let style = null;
    try {
      const sheet = new (doc.defaultView || root).CSSStyleSheet();
      sheet.replaceSync(CSS + Cards.CSS);
      sh.adoptedStyleSheets = [sheet];
    } catch (e) {
      style = el("style");
      style.textContent = CSS + Cards.CSS;
    }
    const wrap = el("div", "wrap");
    const fab = el("button", "fab");
    const panel = el("div", "panel");
    let noPhotosHidden = true; // v1.40: listings with no photos are left out unless the setting is off
    const embedded = !!opts.embedded;
    panel.hidden = !embedded && !opts.open;
    if (embedded) {
      panel.classList.add("embedded");
      fab.hidden = true;
    }
    if (opts.noFab) fab.hidden = true;
    const resizable = !embedded && !!opts.resizable;
    if (resizable) {
      panel.classList.add("resizable");
      const grip = el("div", "grip");
      grip.title = I.t("drag_width");
      panel.append(grip);
      let start = null;
      grip.addEventListener("pointerdown", (e) => {
        e.preventDefault();
        grip.setPointerCapture(e.pointerId);
        start = { x: e.clientX, w: panel.getBoundingClientRect().width };
        panel.classList.add("sizing");
      });
      grip.addEventListener("pointermove", (e) => {
        if (!start) return;
        const rtl = I.dir() === "rtl";
        const dx = (e.clientX - start.x) * (rtl ? -1 : 1);
        panel.style.setProperty("--w", `${Math.round(Math.max(340, Math.min(start.w + dx, (doc.defaultView || root).innerWidth - 40)))}px`);
      });
      const done = () => {
        if (!start) return;
        start = null;
        panel.classList.remove("sizing");
        if (opts.onWidth) opts.onWidth(Math.round(panel.getBoundingClientRect().width));
      };
      grip.addEventListener("pointerup", done);
      grip.addEventListener("pointercancel", done);
      if (opts.width) panel.style.setProperty("--w", `${opts.width}px`);
    }

    const header = el("header");
    const r1 = el("div", "row");
    const brand = el("div", "brand");
    brand.append(el("i"), el("span", null, t("app")));
    const wideBtn = el("button", "icon");
    const allBtn = el("button", "icon");
    const setBtn = el("button", "icon", "⚙");
    const close = el("button", "icon", "×");
    const langBtn = el("button", "icon");
    if (embedded) r1.append(brand, allBtn, langBtn, setBtn);
    else if (resizable) r1.append(brand, allBtn, langBtn, setBtn, close);
    else r1.append(brand, wideBtn, allBtn, setBtn, close);
    const go = el("div", "go");
    const pull = el("button", "act");
    const stop = el("button", "act stop");
    stop.hidden = true;
    const btns = el("div");
    btns.append(pull, stop);
    const status = el("div", "status");
    go.append(btns, status);
    const bar = el("div", "bar");
    const fill = el("div");
    bar.append(fill);
    const est = el("div", "est");
    est.hidden = true;
    header.append(r1, go, est, bar);

    const body = el("div", "body");
    const check = el("div", "box ycheck");
    check.hidden = true;
    const note = el("div", "box note");
    note.hidden = true;
    const sum = el("div", "sum");
    const sortSel = el("select");
    // v1.31: simple cards by default, detailed on a click
    const viewSeg = el("div", "seg");
    const vSimple = el("button");
    const vDetail = el("button");
    viewSeg.append(vSimple, vDetail);
    const more = el("div");
    const list = el("div");
    const stick = el("div", "stick");
    stick.append(sum, more);
    body.append(check, note, stick, list);
    // a line under it once the list has scrolled beneath it
    body.addEventListener("scroll", () => stick.classList.toggle("stuck", body.scrollTop > 4), { passive: true });
    panel.append(header, body);
    wrap.append(fab, panel);
    if (style) sh.append(style, wrap);
    else sh.append(wrap);
    (doc.body || doc.documentElement).append(host);

    let onPull = () => {};
    let onStop = () => {};
    let onMark = null;
    let onWide = () => {};
    let onSort = () => {};
    let onDetail = () => {};
    let detail = false;
    let onApply = null;
    let marks = {};
    let last = null;
    let pending = false;
    let sortBy = "match";
    let wide = false;
    const show = () => { panel.hidden = false; fab.hidden = true; };
    fab.addEventListener("click", show);
    close.addEventListener("click", () => {
      panel.hidden = true;
      fab.hidden = !!opts.noFab;
      if (opts.onClose) opts.onClose();
    });
    pull.addEventListener("click", () => onPull());
    stop.addEventListener("click", () => { stop.disabled = true; onStop(); });
    wideBtn.addEventListener("click", () => setWide(!wide, true));
    allBtn.addEventListener("click", () => opts.openResults && opts.openResults());
    setBtn.addEventListener("click", () => opts.openSettings && opts.openSettings());
    langBtn.addEventListener("click", () => opts.toggleLang && opts.toggleLang());
    let running = false;
    const setDetail = (on, byUser) => {
      detail = !!on;
      vSimple.classList.toggle("on", !detail);
      vDetail.classList.toggle("on", detail);
      if (byUser) onDetail(detail);
      if (last) render(last);
    };
    vSimple.addEventListener("click", () => setDetail(false, true));
    vDetail.addEventListener("click", () => setDetail(true, true));
    sortSel.addEventListener("change", () => {
      sortBy = sortSel.value;
      onSort(sortBy);
      if (last) render(last);
    });
    // a re-render mid-typing (a viewing date) waits until the field is left
    list.addEventListener("focusout", () => setTimeout(() => { if (pending && last) render(last); }, 0));

    /** Words and direction for the language in use; called again when it changes. */
    function words() {
      wrap.dir = I.dir();
      host.dir = I.dir();
      fab.textContent = t("app");
      wideBtn.title = t("wider");
      allBtn.textContent = t("all_listings");
      setBtn.title = t("setup");
      langBtn.textContent = I.lang === "he" ? "EN" : "עב";
      langBtn.title = t("language");
      close.title = t("close");
      pull.textContent = t("pull");
      stop.textContent = t("stop");
      sortSel.replaceChildren();
      for (const k of ["match", "price", "commute"]) {
        const o = el("option", null, t(`sort_${k}`));
        o.value = k;
        o.selected = k === sortBy;
        sortSel.append(o);
      }
      sortSel.title = t("sort_by");
      vSimple.textContent = t("view_simple");
      vDetail.textContent = t("view_detailed");
      viewSeg.title = t("view_label");
      vSimple.classList.toggle("on", !detail);
      vDetail.classList.toggle("on", detail);
      setWide(wide, false);
      if (last) render(last);
      else status.textContent = t("st_idle");
    }

    function setWide(on, byUser) {
      wide = !!on;
      panel.classList.toggle("wide", wide);
      wideBtn.classList.toggle("on", wide);
      wideBtn.textContent = `⇔ ${wide ? t("narrower") : t("wider")}`;
      if (byUser) onWide(wide);
    }

    function link(url, text) {
      if (!Cards.SAFE_LINK.test(url || "")) return el("span", null, text);
      const a = el("a", null, text);
      a.href = url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      return a;
    }

    const commuteOf = (x) => {
      const v = (x.trips || []).map((c) => (c.minutes != null ? c.minutes : c.about)).filter((m) => typeof m === "number");
      return v.length ? Math.max(...v) : Infinity;
    };
    const SORT = {
      match: null, // the helper's order: the expected match and the chance a must-have fails
      price: (a, b) => (a.price || Infinity) - (b.price || Infinity),
      commute: (a, b) => commuteOf(a) - commuteOf(b),
    };

    function cardFor(x, s) {
      return Cards.render(doc, x, { I, mark: marks[x.id], onMark, prefs: s.prefs || {}, readAt: s.readAt && s.readAt[x.id], detail,
        now: s.startedAt || Date.now(), isNew: (s.newIds || []).includes(x.id) });
    }

    function stageText(s) {
      const r = s.read || { done: 0, asked: 0, fromCache: 0 };
      switch (s.stage) {
        case "search": return s.searching ? t("st_search_x", { x: I.lang === "he" ? s.searchingHe || s.searching : s.searching }) : t("st_search");
        case "sites": return s.searching ? t("st_sites_x", { x: s.searching }) : t("st_sites");
        case "read": return t("st_read", { done: r.done, asked: r.asked }) + (r.fromCache ? t("st_read_cache", { n: r.fromCache }) : "");
        case "done": return t("st_done", { t: I.elapsed(s.elapsed) });
        default: return t(`st_${s.stage || "idle"}`);
      }
    }

    function render(s) {
      last = s;
      const typing = sh.activeElement && sh.activeElement.tagName === "INPUT";
      status.replaceChildren(el("span", null, stageText(s)));
      if (s.stage !== "done" && s.stage !== "check" && s.stage !== "cooldown") {
        status.append(el("small", null, [I.elapsed(s.elapsed), I.timeLeft(s.eta)].filter(Boolean).join(" · ")));
      } else if (s.stage === "done" && s.finishedAt) {
        status.append(el("small", null, t("st_last", { when: I.when(s.finishedAt) })));
      }
      const read = s.read || { asked: 0, done: 0 };
      fill.style.width = read.asked ? `${Math.round((100 * read.done) / read.asked)}%` : (s.stage === "done" ? "100%" : "4%");
      const msg = s.error ? (typeof s.error === "string" ? t("e_generic", { detail: s.error }) : I.msg(s.error)) : I.msg(s.message);
      note.hidden = !msg;
      note.className = s.error ? "box note err" : "box note";
      note.textContent = msg || "";
      if (typing) {
        pending = true;
        return;
      }
      pending = false;
      const results = s.results || [];
      const rejected = results.filter((x) => marks[x.id] && marks[x.id].status === "rejected");
      let shown = results.filter((x) => !x.excluded && !(marks[x.id] && marks[x.id].status === "rejected")
        && !(noPhotosHidden && Cards.photoless(x))); // v1.40: the setup page's switch
      if (SORT[sortBy]) shown = shown.slice().sort(SORT[sortBy]);
      const hidden = results.filter((x) => x.excluded);
      const byTopic = s.skippedByTopic || {};
      const skipped = Object.keys(s.skippedRows || {}).length;
      sum.replaceChildren();
      if (s.plan) {
        sum.append(el("span", "pill main", shown.length === 1 ? t("n_match") : t("n_matches", { n: shown.length })),
          el("span", "pill", t("n_checked", { n: s.plan.rows })), el("span", "sp"), viewSeg, sortSel);
      }
      // ways to see more: one line, the options on hover (v1.32)
      const line = s.stage === "done" ? Cards.moreLine(doc, I, s.suggestions, onApply && (async (x) => ({ ok: await onApply(x) }))) : null;
      more.replaceChildren(...(line ? [line] : []));
      stick.classList.toggle("none", !sum.childNodes.length && !more.childNodes.length);

      // v1.33: keep the card you're looking at where it is while results come in (they re-sort as the
      // search goes, which used to scroll the list under you)
      const anchor = (() => {
        const top = body.getBoundingClientRect().top;
        for (const c of list.querySelectorAll("article.rm-card[data-id]")) {
          const r = c.getBoundingClientRect();
          if (r.bottom > top + 8) return { id: c.dataset.id, off: r.top - top };
        }
        return null;
      })();
      const before = body.scrollTop;
      list.replaceChildren();
      if (!shown.length && s.stage === "done" && s.plan) list.append(el("div", "box empty", t("empty_now")));
      if (shown.length) {
        list.append(el("div", "h", t("matches_best")));
        const g = el("div", "grid");
        for (const x of shown) g.append(cardFor(x, s));
        list.append(g);
      }
      const section = (title, open, f) => {
        const d = el("details", "box");
        d.open = !!open;
        d.append(el("summary", null, title));
        f(d);
        list.append(d);
      };
      if (rejected.length) section(t("sec_rejected", { n: rejected.length }), false, (d) => { for (const x of rejected) d.append(cardFor(x, s)); });
      if (hidden.length) section(t("sec_hidden", { n: hidden.length }), false, (d) => { for (const x of hidden) d.append(cardFor(x, s)); });
      if (skipped) {
        section(t("sec_skipped", { n: skipped }), false, (d) => {
          const u = el("ul", "plain");
          for (const [name, n] of Object.entries(byTopic)) u.append(el("li", null, `${I.why(name, (s.prefs || {})[name])}: ${n}`));
          d.append(u, el("div", "muted", t("sec_skipped_see"))); // v1.40: each one, with its reason and link
        });
      }
      if ((s.notOpened || []).length) {
        section(t("sec_notopened", { n: s.notOpened.length }), true, (d) => {
          const u = el("ul", "plain");
          for (const x of s.notOpened) {
            const li = el("li");
            li.append(link(x.url, x.url ? x.url.replace(/^https:\/\/www\./, "") : x.id));
            u.append(li);
          }
          d.append(u);
        });
      }
      fab.textContent = shown.length ? `${t("app")} · ${shown.length}` : t("app");
      if (anchor && before > 0) {
        const c = list.querySelector(`article.rm-card[data-id="${CSS_ESCAPE(anchor.id)}"]`);
        if (c) body.scrollTop += c.getBoundingClientRect().top - body.getBoundingClientRect().top - anchor.off;
        else body.scrollTop = before;
      }
    }

    words();
    return {
      host,
      render,
      words,
      open: show,
      close() { panel.hidden = true; },
      isOpen: () => !panel.hidden,
      onPull(f) { onPull = f; },
      onStop(f) { onStop = f; },
      onMark(f) { onMark = f; },
      onWide(f) { onWide = f; },
      onSort(f) { onSort = f; },
      onDetail(f) { onDetail = f; },
      setDetail(on) { setDetail(on, false); },
      onApply(f) { onApply = f; },
      setSort(k) {
        if (SORT[k] !== undefined) sortBy = k;
        words();
      },
      setWide,
      setMarks(m) {
        marks = m || {};
        if (last) render(last);
      },
      setHideNoPhotos(on) {
        noPhotosHidden = !!on;
        if (last) render(last);
      },
      showCheck({ title, text, button, onButton }) {
        check.replaceChildren(el("strong", null, title), el("div", null, text));
        if (button) {
          const b = el("button", "act", button);
          b.addEventListener("click", () => onButton());
          check.append(b);
        }
        check.hidden = false;
        show();
      },
      clearCheck() { check.hidden = true; },
      /** v1.32: how long a search takes, under the button while idle. */
      setEstimate(text, small, blocked) {
        est.replaceChildren(doc.createTextNode(text || ""));
        if (small) est.append(el("small", null, small));
        est.hidden = !text || running;
        pull.disabled = !!blocked;
      },
      setRunning(on) {
        running = !!on;
        est.hidden = running || !est.textContent;
        pull.hidden = on;
        stop.hidden = !on;
        stop.disabled = false;
      },
    };
  }

  const api = { create };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.RentalPanel = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
