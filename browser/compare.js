/*
 * Rental Matcher: "Teach it your taste" (v1.32; named so in v1.33): tune the
 * ranking by picking between two listings.
 *
 * Two listings from the last search, side by side; you pick the one you'd
 * rather live in (or "Can't decide"). The pairs are chosen to teach the
 * most: listings the ranking puts close together but that differ in what
 * they have. Each pick is kept with both listings' per-criterion
 * satisfaction (`sat`, from the helper), so it stays a fair comparison
 * even after the next search. After a few picks, the helper fits the
 * weights to them (rental_matcher/calibrate.py) and says how often the
 * current weights and the suggested ones agree with you, including on
 * picks the fit didn't see. Applying saves the new weights to the
 * preferences file (with a backup, like any change); the next search uses
 * them.
 */
(function (root) {
  "use strict";

  const SESSION = 10; // picks per round (v1.33: 20 was too many)
  const MAX_PICKS = 200; // kept

  const rankValue = (x) => ((x.match_expected || 0) / 100) * (1 - (x.fail_risk || 0));
  const key = (a, b) => [a, b].sort().join("|");

  /**
   * The next pair to ask about: two listings the ranking finds close, that
   * differ most in what they have; never one already asked; a listing that
   * has been in many pairs is used less. rnd: a 0-1 random function.
   */
  function nextPair(listings, picks, rnd) {
    const xs = listings.filter((x) => x && x.sat && Object.keys(x.sat).length && !x.excluded).slice(0, 40);
    const asked = new Set(picks.map((p) => key(p.a.id, p.b.id)));
    const used = {};
    for (const p of picks) for (const id of [p.a.id, p.b.id]) used[id] = (used[id] || 0) + 1;
    const cands = [];
    for (let i = 0; i < xs.length; i++) {
      for (let j = i + 1; j < xs.length; j++) {
        const a = xs[i];
        const b = xs[j];
        if (asked.has(key(a.id, b.id))) continue;
        const names = new Set([...Object.keys(a.sat), ...Object.keys(b.sat)]);
        let diff = 0;
        for (const n of names) diff += Math.abs((a.sat[n] ?? 0.5) - (b.sat[n] ?? 0.5));
        const score = diff - 6 * Math.abs(rankValue(a) - rankValue(b)) - 0.4 * ((used[a.id] || 0) + (used[b.id] || 0));
        cands.push([score, a, b]);
      }
    }
    if (!cands.length) return null;
    cands.sort((p, q) => q[0] - p[0]);
    const top = cands.slice(0, Math.min(5, cands.length));
    const [, a, b] = top[Math.floor((rnd || Math.random)() * top.length)];
    return (rnd || Math.random)() < 0.5 ? [a, b] : [b, a];
  }

  /** What a pick keeps of a listing: enough to fit the weights, and to say which one it was. */
  const keep = (x) => ({ id: x.id, sat: x.sat, fail: x.fail_risk || 0, price: x.price, street: x.street, city: x.city });

  const api = { nextPair, keep, rankValue, SESSION };
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
    return;
  }
  root.RentalCompare = api;
  if (typeof document === "undefined" || !document.getElementById("stage")) return;

  // ---- the page ---------------------------------------------------------------------------

  const $ = (id) => document.getElementById(id);
  const I = RentalI18n;
  const t = I.t;
  const store = RentalStore.make(chrome.storage.local);
  $("cards-css").textContent = RentalCards.CSS;
  let results = null;
  let picks = [];
  let round = 0; // picks made on this visit
  let current = null;
  let keepPair = -1; // the picks count the current pair was chosen at
  let detail = false; // v1.36: Simple or Detailed cards, as on the results page
  let marks = {};
  let ui = {};

  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = String(text);
    return e;
  };
  const helper = (path, body) => chrome.runtime.sendMessage({ type: "helper", path, body }).catch(() => null);

  function progress() {
    const n = picks.filter((p) => p.pick === "a" || p.pick === "b" || p.pick === "neither").length;
    $("count").textContent = t("cp_count", { n, r: Math.min(round, SESSION), of: SESSION });
    $("fill").style.width = `${Math.min(100, (100 * round) / SESSION)}%`;
    $("result").textContent = t("cp_result");
    $("result").disabled = n < 8;
    $("result").title = n < 8 ? t("cp_need", { n: 8 - n }) : "";
  }

  function show() {
    progress();
    const stage = $("stage");
    // v1.36: not a listing you said "Not for me" to; the same pair stays when you switch Simple/Detailed
    const shown = ((results && results.results) || []).filter((x) => !x.excluded && !((marks[x.id] || {}).status === "rejected")
      && !(RentalCards.hidesPhotoless(ui) && RentalCards.photoless(x))); // v1.40: no photos, nothing to judge it by
    if (!current || keepPair !== picks.length) current = nextPair(shown, picks);
    keepPair = picks.length;
    if (!current) {
      stage.replaceChildren(el("div", "empty", shown.length < 2 ? t("cp_none") : t("cp_all_asked")));
      return;
    }
    if (round >= SESSION) {
      stage.replaceChildren(el("div", "empty", t("cp_round_done")));
      const more = el("button", "btn", t("cp_more"));
      more.addEventListener("click", () => { round = 0; show(); });
      stage.append(el("div", "row"));
      stage.lastChild.append(more);
      return report();
    }
    const pair = el("div", "pair");
    const fresh = new Set(results.newIds || []);
    const side = (x, which) => {
      const d = el("div", "side");
      d.append(RentalCards.render(document, x, { I, prefs: results.prefs || {}, isNew: fresh.has(x.id), detail }));
      const b = el("button", "pick", t("cp_this"));
      b.addEventListener("click", () => choose(which));
      d.append(b);
      return d;
    };
    pair.append(side(current[0], "a"), el("div", "vs", t("cp_or")), side(current[1], "b"));
    const row = el("div", "row");
    const same = el("button", "btn", t("cp_same"));
    same.addEventListener("click", () => choose("same"));
    // "Neither": you wouldn't live in either. It doesn't touch your listings (v1.37 put both in "Not for
    // me"); v1.41: it teaches the fit that both rank below the listings you do pick (calibrate._pairs).
    const neither = el("button", "btn", t("cp_neither"));
    neither.title = t("cp_neither_x");
    neither.addEventListener("click", () => choose("neither"));
    row.append(same, neither);
    stage.replaceChildren(pair, row);
  }

  async function choose(which) {
    if (!current) return;
    picks.push({ a: keep(current[0]), b: keep(current[1]), pick: which, at: Date.now() });
    picks = picks.slice(-MAX_PICKS);
    round++;
    await store.set("tune", { picks });
    window.scrollTo({ top: 0 });
    show();
  }

  const pct = (v) => (v == null ? "–" : `${Math.round(100 * v)}%`);

  async function report() {
    const box = $("report");
    box.hidden = false;
    box.replaceChildren(el("div", "muted", t("cp_working")));
    box.scrollIntoView({ behavior: "smooth", block: "start" });
    const r = await helper("/calibrate", { pairs: picks });
    if (!r || !r.ok) {
      box.replaceChildren(el("div", "muted", t("e_generic", { detail: (r && r.body && r.body.error) || "" })));
      return;
    }
    const o = r.body;
    box.replaceChildren(el("h2", null, t("cp_report_title", { n: o.picks })));
    if (!o.enough) {
      box.append(el("p", "muted", t("cp_need", { n: o.min_picks - o.picks })));
      return;
    }
    const nums = el("div", "nums");
    const num = (v, label) => {
      const d = el("div", "num");
      d.append(el("b", null, pct(v)), el("span", null, label));
      return d;
    };
    nums.append(num(o.before, t("cp_before")), num(o.held_out, t("cp_held")), num(o.after, t("cp_after")));
    box.append(el("p", "muted", t("cp_explain")), nums);
    const tb = el("table");
    const hr = el("tr");
    for (const k of ["cp_crit", "cp_now", "cp_new"]) hr.append(el("th", null, t(k)));
    tb.append(hr);
    for (const c of o.criteria) {
      const tr = el("tr");
      const info = ((results && results.prefs) || {})[c.name];
      const name = (info && I.topicTitle(info)) || c.label;
      // v1.40: a must-have's weight is locked: never suggested, never changed
      tr.append(el("td", null, c.locked ? `🔒 ${name}` : name), el("td", null, c.before),
        el("td", c.locked ? "muted" : c.after > c.before ? "up" : c.after < c.before ? "down" : "", c.locked ? t("cp_locked") : c.after));
      tb.append(tr);
    }
    box.append(tb);
    if (o.criteria.some((c) => c.locked)) box.append(el("p", "muted", t("cp_locked_x")));
    if (!o.suggest) {
      box.append(el("p", null, t("cp_keep")));
      return;
    }
    const row = el("div", "row");
    const apply = el("button", "btn primary", t("cp_apply"));
    apply.addEventListener("click", async () => {
      apply.disabled = true;
      const w = Object.fromEntries(o.criteria.filter((c) => !c.locked).map((c) => [c.name, c.after]));
      const s = await helper("/reweigh", { weights: w });
      row.replaceChildren(el("span", null, s && s.ok && s.body && s.body.saved ? t("cp_applied") : t("e_generic", { detail: (s && s.body && (s.body.error || (s.body.errors || []).join("; "))) || "" })));
    });
    row.append(apply);
    box.append(row);
  }

  $("result").addEventListener("click", report);
  $("detail").addEventListener("click", (e) => {
    const d = e.target.dataset && e.target.dataset.d;
    if (d == null) return;
    detail = d === "1";
    for (const b of $("detail").children) b.classList.toggle("on", (b.dataset.d === "1") === detail);
    store.get("ui", {}).then((ui) => store.set("ui", Object.assign(ui, { detail })));
    show();
  });
  $("back").addEventListener("click", () => { location.href = "results.html"; });

  (async () => {
    await I.load(chrome.storage.local);
    I.apply(document);
    document.title = t("cp_title");
    $("lead").replaceChildren(document.createTextNode(t("cp_lead")), el("small", null, t("cp_lead_x")));
    results = await store.get("results", null);
    picks = ((await store.get("tune", {})).picks || []);
    await store.undoNeither(); // v1.40's clean-up, in case the update hook didn't run
    marks = await store.get("marks", {});
    ui = await store.get("ui", {});
    detail = !!ui.detail;
    for (const b of $("detail").children) b.classList.toggle("on", (b.dataset.d === "1") === detail);
    show();
  })();
})(typeof globalThis !== "undefined" ? globalThis : this);
