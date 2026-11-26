/*
 * Rental Matcher: the page side of a search (v1.27; v1.32: no panel here).
 *
 * It runs on every Yad2 page, but only the one tab the background chose
 * searches: on load the page says hello, and the background answers whether
 * this tab should start (or go on after Yad2's check). Other Yad2 tabs -- a
 * listing opened from the panel, say -- never start a search of their own,
 * so there's only ever one, at one pace. Since v1.32 nothing is added to
 * Yad2's page: the panel is Chrome's side panel (sidepanel.js), and this
 * page sends it its progress ("live" messages).
 *
 * The search's tab is a background tab, and Chrome slows a background
 * tab's timers (to once a minute after five minutes). So the waits between
 * requests are kept by the background (a "sleep" message), which Chrome
 * doesn't slow; the requests themselves are this page's, as before.
 *
 * If Yad2 pushes back, the page tells the background, which reloads this
 * tab: if Yad2 wants its check, the real check is on screen then, with a
 * window saying what to do; if not, the search pauses a minute and goes on
 * at half the pace.
 */
(function () {
  "use strict";
  if (window.__rentalMatcher) return;
  window.__rentalMatcher = true;

  const I = RentalI18n;
  const t = I.t;
  const store = RentalStore.make(chrome.storage.local);
  const send = (msg) => chrome.runtime.sendMessage(msg).catch(() => null);
  let running = false;
  let stop = false;
  let lastStatus = 0;

  /** Is this page Yad2's bot check instead of Yad2? */
  function isCheckPage() {
    if (document.getElementById("__NEXT_DATA__")) return false;
    return RentalPull.looksBlocked(200, document.documentElement.outerHTML.slice(0, 300000));
  }
  // Yad2's check page is left exactly as it is: no panel on it, nothing added
  if (isCheckPage()) {
    send({ type: "hello", checkPage: true });
    return;
  }

  // v1.32: what the side panel shows, sent to it as it changes (at most every 300 ms)
  const liveNow = { state: null, running: false, check: null };
  let liveTimer = null;
  function pushLive(now) {
    if (now) {
      clearTimeout(liveTimer);
      liveTimer = null;
      send(Object.assign({ type: "live" }, liveNow));
      return;
    }
    if (liveTimer) return;
    liveTimer = setTimeout(() => { liveTimer = null; send(Object.assign({ type: "live" }, liveNow)); }, 300);
  }
  const panel = {
    render(st) { liveNow.state = st; pushLive(st && (st.stage === "done" || st.stage === "check")); },
    showCheck(c) { liveNow.check = { title: c.title, text: c.text }; pushLive(true); },
    clearCheck() { if (liveNow.check) { liveNow.check = null; pushLive(true); } },
    setRunning(on) { liveNow.running = !!on; pushLive(true); },
    open() {},
  };
  /** A wait the background keeps (Chrome slows a background tab's own timers); a plain timer if it can't. */
  const timer = (ms) => new Promise((r) => setTimeout(r, ms));
  const sleep = (ms) => {
    if (!(ms > 0)) return Promise.resolve();
    if (!document.hidden || ms < 20) return timer(ms);
    return chrome.runtime.sendMessage({ type: "sleep", ms }).then((r) => (r && r.ok ? null : timer(ms)), () => timer(ms));
  };

  function status(s, force) {
    const now = Date.now();
    if (!force && now - lastStatus < 300) return;
    lastStatus = now;
    chrome.storage.local.set({ status: {
      running, stage: s.stage, searching: s.searching || null, searchingHe: s.searchingHe || null, asked: s.read ? s.read.asked : 0,
      done: s.read ? s.read.done : 0, shown: s.plan ? s.shown : null, eta: s.eta, elapsed: s.elapsed, message: s.message || null,
      error: s.error || null, at: now,
    } });
  }

  /** What's kept of a finished search for the results page and the next visit. */
  function keep(s, newIds) {
    return {
      stage: "done", message: s.message, error: s.error, plan: s.plan, read: s.read, results: s.results, shown: s.shown, hidden: s.hidden,
      skippedRows: s.skippedRows, skippedInfo: s.skippedInfo || {}, merged: s.merged || {}, outside: s.outside || {}, skippedByReason: s.skippedByReason, skippedByTopic: s.skippedByTopic, notOpened: s.notOpened,
      readAt: s.readAt, startedAt: s.startedAt, elapsed: s.elapsed, finishedAt: Date.now(), searches: s.searches, prefs: s.prefs,
      suggestions: s.suggestions || [], newIds, bySource: s.bySource || null, sites: s.sites || null,
    };
  }

  async function pull(opts) {
    if (running) return;
    running = true;
    stop = false;
    panel.open();
    panel.clearCheck();
    panel.setRunning(true);
    const marks = await store.get("marks", {});
    const skip = Object.keys(marks).filter((id) => marks[id].status === "rejected");
    const prefer = Object.keys(marks).filter((id) => marks[id].status && marks[id].status !== "rejected"); // v1.38: a merge keeps these
    const tuning = await store.get("tuning", {}); // tests only: shorter waits
    const [pool, sources] = await Promise.all([store.get("pool", { rows: {}, items: {} }), store.get("sources", {})]);
    let s = null;
    try {
      s = await RentalRunner.runPull({
        searchPath: location.pathname + location.search,
        pathname: location.pathname,
        P: RentalPull,
        cache: { listings: RentalPull.idbCache("listings"), routes: RentalPull.idbCache("routes"), searches: RentalPull.idbCache("searches") },
        call: (path, body) => send({ type: "helper", path, body }),
        onUpdate: (st) => {
          panel.render(st);
          status(st, false);
        },
        shouldStop: () => stop,
        pullOpts: Object.assign(opts.slow ? { minGapMs: tuning.slowGapMs || 2400 } : {}, { sleep }),
        sleep,
        reuseSearchMs: opts.reuseSearchMs || 0,
        suggest: !tuning.noSuggest,
        skip,
        prefer,
        // v1.27: Komo (its public pages, fetched by the background) and what the user opened on Komo and Madlan
        S: RentalSites,
        siteGet: (url) => send({ type: "site", url }),
        siteGapMs: tuning.siteGapMs,
        pool,
        sources,
        onExtracts: (x) => store.keepForLabels(x, RentalSites.scrub),
      });
    } finally {
      running = false;
      panel.setRunning(false);
    }
    if (!s) return;
    if (RentalRunner.isCheck(s.stoppedBecause)) {
      // what Yad2 said goes to the log; the background reloads this tab to see what it wants
      s.message = { key: "ck_reload" };
      s.stage = "check";
      panel.render(s);
      status(s, true);
      await send({ type: "pushback", detail: Object.assign({}, s.pushback, { elapsedMs: s.elapsed, requests: s.requests, slow: !!opts.slow }) });
      return;
    }
    const newIds = await store.markSeen((s.results || []).filter((x) => !x.excluded).map((x) => x.id));
    s.newIds = newIds;
    // v1.30: a lower rent than last time is a price drop
    const drops = await store.notePrices(s.results || []);
    for (const x of s.results || []) if (drops[x.id]) x.drop = drops[x.id];
    s.finishedAt = Date.now();
    panel.render(s);
    // v1.34: a search that failed or was stopped before it showed anything doesn't wipe out the last one's
    // listings (the helper not answering used to leave the panel and "All listings" empty); what went wrong
    // goes to the status, and the last results stay, with the message
    const empty = !(s.results || []).length && (s.error || s.stoppedBecause);
    if (empty) {
      const prev = await store.get("results", null);
      if (prev) await chrome.storage.local.set({ results: Object.assign(prev, { message: s.message || null, error: s.error || null }) });
      else await chrome.storage.local.set({ results: keep(s, newIds) });
    } else await chrome.storage.local.set({ results: keep(s, newIds) });
    status(s, true);
    await send({ type: "finished", summary: {
      ms: s.elapsed, complete: !s.stoppedBecause && !s.error, stopped: s.stoppedBecause ? true : null, error: s.error ? true : null,
      searches: (s.searches || []).length, rows: s.plan ? s.plan.rows : 0, opened: s.read.done - s.read.fromCache, fromCache: s.read.fromCache,
      requests: s.requests, shown: s.shown, searchesFromCache: s.searchesFromCache, fresh: newIds.length,
    } });
  }

  // v1.34: the pause counts down with the background's waits (sleep): this tab is in the background, and
  // Chrome runs a background tab's chained one-second timers once a minute after five minutes, which made
  // a one-minute pause late in a long search last an hour
  async function countdown(ms, why) {
    const end = Date.now() + ms;
    for (;;) {
      const left = Math.max(0, Math.ceil((end - Date.now()) / 1000));
      const text = t("ck_countdown", { why, n: left });
      panel.showCheck({ title: t("ck_pause_title"), text });
      status({ stage: "cooldown", read: null, message: text }, true);
      if (left <= 0) break;
      await sleep(Math.min(1000, end - Date.now()));
    }
    panel.clearCheck();
  }

  async function act(r) {
    if (!r) return;
    if (r.action === "start") {
      if (r.delayMs) await countdown(r.delayMs, r.why ? t(r.why) : "");
      return pull({ slow: !!r.slow, reuseSearchMs: r.reuseSearchMs || 0 });
    }
    if (r.action === "check") panel.showCheck({ title: t("ck_title"), text: t("ck_text") });
    if (r.action === "stopped") panel.showCheck({ title: t("ck_stopped_title"), text: t(r.text) });
  }

  (async () => {
    await I.load(chrome.storage.local);
    chrome.runtime.onMessage.addListener((m, sender, reply) => {
      if (!m) return false;
      if (m.type === "start") {
        if (running) reply({ ok: true, already: true });
        else {
          reply({ ok: true });
          pull({ slow: !!m.slow, reuseSearchMs: m.reuseSearchMs || 0 });
        }
        return false;
      }
      if (m.type === "stop") stop = true;
      // the side panel opened mid-search: where it is now
      if (m.type === "live?") reply(running || liveNow.check ? liveNow : null);
      return false;
    });
    chrome.storage.onChanged.addListener((c, area) => {
      if (area === "local" && c.ui && c.ui.newValue && c.ui.newValue.lang && c.ui.newValue.lang !== I.lang) I.setLang(c.ui.newValue.lang);
    });
    act(await send({ type: "hello", checkPage: false }));
  })();
})();
