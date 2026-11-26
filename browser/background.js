/*
 * Rental Matcher: the extension's background (v1.25).
 *
 * - Talks to the helper through Chrome's native messaging: Chrome starts it
 *   (rental_matcher/native.py) on the first request and stops it when it's
 *   no longer needed. Nothing to run by hand.
 * - Owns the pull: which tab pulls (only ever one), and what happens when
 *   Yad2 pushes back. The page reports a pushback; this reloads the pull's
 *   tab to see what Yad2 wants:
 *     - its check (the tab lands on validate.perfdrive.com, or the page is
 *       the check): a window pops up saying to complete it, the tab comes
 *       forward, and once it's done the pull goes on at half the pace. A
 *       second check the same day stops pulling until tomorrow.
 *     - no check: the pull pauses a minute and goes on at half the pace;
 *       a third pushback the same day without a check also stops it.
 *   Every pushback and check goes to the pull log (store.js).
 */
"use strict";

importScripts("store.js", "i18n.js", "sites.js");

const HOST = "com.rental_matcher.helper";
const NOT_INSTALLED = "e_not_installed"; // words: i18n.js
const CHECK_HOST = "validate.perfdrive.com"; // where Yad2's check (Radware) sends a tab
const COOLDOWN_MS = 60e3;
const REUSE_SEARCH_MS = 30 * 60e3;
const MAX_SOFT_PUSHBACKS = 3;
const store = RentalStore.make(chrome.storage.local);

// ---- the helper ------------------------------------------------------------------

let port = null;
let seq = 0;
const pending = new Map();
const pieces = new Map();

function connect() {
  if (port) return port;
  port = chrome.runtime.connectNative(HOST);
  port.onMessage.addListener((m) => {
    if (m && m.part !== undefined) {
      const got = pieces.get(m.id) || { parts: [], n: 0 };
      if (got.parts[m.part] === undefined) got.n++;
      got.parts[m.part] = m.data;
      pieces.set(m.id, got);
      if (got.n < m.of) return;
      pieces.delete(m.id);
      m = JSON.parse(got.parts.join(""));
    }
    const done = pending.get(m && m.id);
    if (done) {
      pending.delete(m.id);
      done({ ok: !!m.ok, status: m.status, body: m.body });
    }
  });
  port.onDisconnect.addListener(() => {
    const why = (chrome.runtime.lastError && chrome.runtime.lastError.message) || "";
    port = null;
    const error = /not found|forbidden|not allowed|invalid/i.test(why) ? NOT_INSTALLED : RentalI18n.t("e_helper_stopped", { why: why || "?" });
    for (const done of pending.values()) done({ ok: false, status: 0, body: { error } });
    pending.clear();
    pieces.clear();
  });
  return port;
}

function helper(path, body) {
  return new Promise((resolve) => {
    const id = ++seq;
    pending.set(id, resolve);
    try {
      connect().postMessage({ id, path, body });
    } catch (e) {
      pending.delete(id);
      resolve({ ok: false, status: 0, body: { error: NOT_INSTALLED } });
    }
  });
}

// ---- state -------------------------------------------------------------------------

const today = () => new Date().toISOString().slice(0, 10);

async function getPull() {
  return store.get("pull", null);
}

async function setPull(patch) {
  const p = Object.assign((await getPull()) || {}, patch, { since: Date.now() });
  await store.set("pull", p);
  return p;
}

/** Today's checks seen and pushbacks without one. */
async function getDay() {
  const d = await store.get("checks", null);
  if (!d || d.date !== today()) return { date: today(), count: 0, soft: 0 };
  // before v1.25 every pushback counted as a check, seen or not: those count as pushbacks
  if (d.soft === undefined) return { date: d.date, count: 0, soft: d.count || 0 };
  return d;
}

async function setStatus(patch) {
  const status = await store.get("status", {});
  await store.set("status", Object.assign(status, patch, { at: Date.now() }));
}

async function notify(id, titleKey, messageKey) {
  await RentalI18n.load(chrome.storage.local);
  try {
    chrome.notifications.create(id, { type: "basic", iconUrl: "icons/icon128.png", title: RentalI18n.t(titleKey),
      message: RentalI18n.t(messageKey), priority: 2 });
  } catch (e) { /* notifications off: the window and the page still say it */ }
}

async function tabAlive(id) {
  try {
    return await chrome.tabs.get(id);
  } catch (e) {
    return null;
  }
}

async function focus(tab) {
  await chrome.tabs.update(tab.id, { active: true });
  await chrome.windows.update(tab.windowId, { focused: true });
}

// i18n.js keys: the side panel and the window word them in the user's language
const TEXT = { check: "ck_text", again: "ck_again", soft: "ck_soft", softStop: "ck_soft_stop", solved: "ck_solved" };

// ---- starting a pull ---------------------------------------------------------------

async function stoppedToday() {
  const d = await getDay();
  if (d.count >= 2) return TEXT.again;
  if (d.soft >= MAX_SOFT_PUSHBACKS) return TEXT.softStop;
  return null;
}

async function findYad2Tab(prefer) {
  if (prefer) {
    const t = await tabAlive(prefer);
    if (t && /^https:\/\/www\.yad2\.co\.il\//.test(t.url || "")) return t;
  }
  const [open] = await chrome.tabs.query({ url: "https://www.yad2.co.il/*" });
  return open || null;
}

const START_MS = 45e3; // a search's tab says hello well within this

/**
 * here: a Yad2 tab that asked to search itself (none since v1.32). Without
 * it, the search runs in a Yad2 tab of its own, opened in the background
 * (`own`), never brought to the front unless Yad2 asks for its check, and
 * closed when the search is done. The user's own Yad2 tabs are left alone.
 * Returns {ok, start?, slow?, error?}.
 */
async function startPull(here) {
  const stopped = await stoppedToday();
  if (stopped) return { ok: false, error: stopped };
  const p = await getPull();
  // v1.32: a tab that never got going (Yad2 or the connection down) doesn't block the next search for half an hour
  const stuck = p && p.phase === "starting" && Date.now() - (p.since || 0) > START_MS;
  if (stuck && p.own) chrome.tabs.remove(p.tabId).catch(() => {});
  if (p && !stuck && p.phase !== "done" && (await tabAlive(p.tabId)) && Date.now() - (p.since || 0) < 30 * 60e3) {
    return { ok: false, error: "e_running_here" };
  }
  const cfg = await helper("/config");
  if (!cfg.ok) {
    await setStatus({ stage: "done", error: cfg.body && cfg.body.error, running: false });
    return { ok: false, error: cfg.body && cfg.body.error };
  }
  const d = await getDay();
  const slow = d.count + d.soft >= 1; // Yad2 pushed back today: half the pace all day
  await setStatus({ running: true, stage: "starting", error: null, message: null, asked: 0, done: 0, shown: null, eta: null });
  if (here) {
    await setPull({ tabId: here.id, phase: "running", slow, startedAt: Date.now() });
    return { ok: true, start: true, slow };
  }
  const first = (cfg.body.searches && cfg.body.searches[0] && cfg.body.searches[0].path) || "/realestate/rent";
  const prev = p && p.own ? p.tabId : null;
  const tab = prev ? await findYad2Tab(prev) : null;
  if (tab && tab.id === prev) {
    await setPull({ tabId: tab.id, phase: "running", slow, startedAt: Date.now(), own: true });
    try {
      await chrome.tabs.sendMessage(tab.id, { type: "start", slow });
    } catch (e) {
      // a tab from before the extension was loaded has no page script yet: load it again
      await setPull({ phase: "starting" });
      await chrome.tabs.reload(tab.id);
    }
    return { ok: true };
  }
  const created = await chrome.tabs.create({ url: "https://www.yad2.co.il" + first, active: false });
  await setPull({ tabId: created.id, phase: "starting", slow, startedAt: Date.now(), own: true });
  return { ok: true };
}

// ---- Yad2's pushback and check -----------------------------------------------------

let checkWindow = null;

async function openCheckWindow() {
  try {
    if (checkWindow && (await chrome.windows.get(checkWindow))) {
      await chrome.windows.update(checkWindow, { focused: true, drawAttention: true });
      return;
    }
  } catch (e) { /* closed */ }
  try {
    const w = await chrome.windows.create({ url: chrome.runtime.getURL("check.html"), type: "popup", width: 420, height: 300, focused: true });
    checkWindow = w.id;
    await store.set("checkWindow", w.id);
  } catch (e) { /* no windows here (tests): the notification and the page still say it */ }
}

async function closeCheckWindow() {
  const id = checkWindow || (await store.get("checkWindow", null));
  checkWindow = null;
  await store.set("checkWindow", null);
  if (id) chrome.windows.remove(id).catch(() => {});
}

/** The pull's tab is showing Yad2's check. */
async function enterCheck(tabId, how) {
  const p = await getPull();
  if (!p || p.tabId !== tabId || p.phase === "check" || p.phase === "done") return p && p.phase === "check" ? { again: false } : null;
  const d = await getDay();
  d.count++;
  await store.set("checks", d);
  const again = d.count >= 2;
  await store.logEvent({ kind: "check shown", how, again });
  await setPull({ phase: again ? "done" : "check" });
  await setStatus({ running: false, stage: again ? "done" : "check", message: { key: again ? TEXT.again : TEXT.check } });
  chrome.action.setBadgeText({ text: "!" });
  chrome.action.setBadgeBackgroundColor({ color: "#d4691e" });
  const tab = await tabAlive(tabId);
  if (tab) await focus(tab);
  notify("rm-check", "ck_title", again ? TEXT.again : TEXT.check);
  if (!again) await openCheckWindow();
  return { again };
}

async function onPushback(tab, detail) {
  const p = await getPull();
  if (!p || p.tabId !== tab.id) return;
  await store.logEvent(Object.assign({ kind: "pushback" }, detail || {}));
  await setPull({ phase: "verifying" });
  await setStatus({ running: true, stage: "check", message: { key: "ck_reload" } });
  // a moment's pause, then look: the real page, as Yad2 serves it to this browser now
  setTimeout(() => chrome.tabs.reload(tab.id).catch(() => {}), 1500);
}

/** A page loaded and said hello: what should it do? */
async function hello(tab, checkPage) {
  const p = await getPull();
  if (!p || p.tabId !== tab.id) return { action: "idle" };
  if (checkPage) {
    if (p.phase === "done") return { action: "idle" };
    const r = await enterCheck(tab.id, "the page");
    return r && r.again ? { action: "stopped", text: TEXT.again } : { action: "check", text: TEXT.check };
  }
  const tuning = await store.get("tuning", {}); // tests only: shorter waits
  if (p.phase === "starting") {
    await setPull({ phase: "running" });
    return { action: "start", slow: p.slow };
  }
  if (p.phase === "verifying") {
    // Yad2 pushed back but serves the page: no check to do. Pause, then half the pace.
    const d = await getDay();
    d.soft++;
    await store.set("checks", d);
    await store.logEvent({ kind: "no check shown", soft: d.soft });
    if (d.soft >= MAX_SOFT_PUSHBACKS) {
      await setPull({ phase: "done" });
      await setStatus({ running: false, stage: "done", message: { key: TEXT.softStop } });
      return { action: "stopped", text: TEXT.softStop };
    }
    await setPull({ phase: "running", slow: true });
    return { action: "start", slow: true, delayMs: tuning.cooldownMs || COOLDOWN_MS, reuseSearchMs: REUSE_SEARCH_MS, why: TEXT.soft };
  }
  if (p.phase === "check") {
    // the check is done: Yad2 sent the tab back
    await store.logEvent({ kind: "check completed" });
    await closeCheckWindow();
    chrome.action.setBadgeText({ text: "" });
    notify("rm-check", "ck_solved_title", TEXT.solved);
    await setPull({ phase: "running", slow: true });
    return { action: "start", slow: true, delayMs: tuning.solvedDelayMs || 5000, reuseSearchMs: REUSE_SEARCH_MS, why: "ck_done_short" };
  }
  if (p.phase === "running" && Date.now() - (p.since || 0) < 30 * 60e3) {
    // the pull's own tab was reloaded mid-pull: go on, nothing read is read again
    return { action: "start", slow: p.slow, reuseSearchMs: REUSE_SEARCH_MS };
  }
  return { action: "idle" };
}

async function finished(tab, summary) {
  const pulls = await store.get("pulls", []);
  const lastFull = pulls.filter((x) => x.complete).pop();
  const kind = lastFull && Date.now() - lastFull.at < RentalStore.DAY ? "repeat" : "first";
  await store.addPull(Object.assign({ at: Date.now(), kind }, summary));
  const p = await getPull();
  await setPull({ phase: "done" });
  chrome.action.setBadgeText({ text: "" });
  // v1.32: the search's own tab goes once it's done, unless the user is looking at it; then it's
  // theirs (v1.34): the next search opens a tab of its own instead of taking it over (and closing it)
  if (p && p.own && p.tabId === tab.id) {
    if (!tab.active) chrome.tabs.remove(tab.id).catch(() => {});
    else await setPull({ own: false });
  }
}

// ---- other sites ---------------------------------------------------------------------
//
// Komo's public pages, fetched here for a pull (a page can't read another
// site; the extension can). Only Komo's results and listing pages, with no
// cookies (so never as the user's Komo account) and nothing sent but the
// address. Madlan is never fetched: it answers fetches with a bot check.

const SITE_OK = /^https:\/\/www\.komo\.co\.il\/code\/nadlan\/(?:apartments-for-rent\.asp\?[^#]*|details\/\?modaaNum=\d+)$/;

async function siteGet(url) {
  if (typeof url !== "string" || !SITE_OK.test(url)) return { error: "not a page we read" };
  try {
    const r = await fetch(url, { credentials: "omit", cache: "no-store", redirect: "follow" });
    const text = r.status === 200 ? await r.text() : "";
    return { status: r.status, url: r.url, text: text.slice(0, 3e6) };
  } catch (e) {
    return { error: String((e && e.message) || e) };
  }
}

// What the user saw on Komo and Madlan himself (content_sites.js), kept a
// few days for the next pull: the facts of each listing, no contact details.
const POOL_MS = 3 * 864e5;
const POOL_MAX = 800;
let poolWrite = Promise.resolve();

function keepSeen(found, site) {
  const mine = (id) => typeof id === "string" && id.startsWith(`${site}:`);
  poolWrite = poolWrite.then(async () => {
    const pool = await store.get("pool", { rows: {}, items: {} });
    const now = Date.now();
    for (const r of found.rows || []) if (r && mine(r.id)) pool.rows[r.id] = Object.assign({}, r, { seenAt: now });
    if (found.item && mine(found.item.id)) {
      pool.items[found.item.id] = { extract: found.item, seenAt: now };
      // a listing page is a row too, so the next pull plans it even if no results page showed it
      const x = found.item;
      pool.rows[x.id] = Object.assign({}, pool.rows[x.id] || {}, {
        id: x.id, source: x.source, url: x.url, price: x.price, rooms: x.rooms, size_m2: x.size_m2, floor: x.floor, property: x.property || null,
        city: x.city, hood_name: x.neighborhood, street: x.street, lat: x.lat, lng: x.lng, adType: x.adType || null,
        photos: Array.isArray(x.photos) ? x.photos.slice(0, 20) : [],
        fp: (pool.rows[x.id] && pool.rows[x.id].fp) || `${x.price}|${x.rooms}|${x.size_m2}|${x.floor}`, seenAt: now,
      });
    }
    for (const box of [pool.rows, pool.items]) {
      const ids = Object.keys(box).filter((id) => now - (box[id].seenAt || 0) <= POOL_MS).sort((a, b) => box[b].seenAt - box[a].seenAt);
      for (const id of Object.keys(box)) if (!ids.slice(0, POOL_MAX).includes(id)) delete box[id];
    }
    await store.set("pool", pool);
  }).catch(() => {});
  return poolWrite;
}

// ---- messages ------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((msg, sender, send) => {
  if (!msg || typeof msg.type !== "string") return false;
  const reply = (f) => {
    f().then(send, (e) => send({ ok: false, error: String((e && e.message) || e) }));
    return true;
  };
  if (msg.type === "helper" && typeof msg.path === "string" && /^\/[a-z]+$/.test(msg.path)) {
    return reply(() => helper(msg.path, msg.body));
  }
  // Komo pages for the pull running in a Yad2 tab
  if (msg.type === "site" && sender.tab && /^https:\/\/www\.yad2\.co\.il\//.test(sender.url || sender.tab.url || "")) {
    return reply(() => siteGet(msg.url));
  }
  // a Komo or Madlan page the user opened, read by content_sites.js on that page
  const seenOn = msg.type === "seen" && sender.tab && /^https:\/\/www\.(komo|madlan)\.co\.il\//.exec(sender.url || sender.tab.url || "");
  if (seenOn) return reply(async () => (await keepSeen(msg.found || {}, seenOn[1]), { ok: true }));
  if (msg.type === "pull") return reply(() => startPull(msg.here && sender.tab ? sender.tab : null));
  if (msg.type === "hello" && sender.tab) return reply(() => hello(sender.tab, !!msg.checkPage));
  if (msg.type === "pushback" && sender.tab) return reply(async () => (await onPushback(sender.tab, msg.detail), { ok: true }));
  if (msg.type === "finished" && sender.tab) return reply(async () => (await finished(sender.tab, msg.summary || {}), { ok: true }));
  // v1.33: a panel on a page opened or closed; the search's progress, passed on to those panels
  if (msg.type === "overlay" && sender.tab) return reply(async () => (await setOverlay(sender.tab.id, !!msg.on), { ok: true }));
  if (msg.type === "live" && sender.tab) {
    relayLive(msg);
    return false;
  }
  // v1.32: a wait for the search's background tab, whose own timers Chrome slows
  if (msg.type === "sleep" && sender.tab) {
    const ms = Math.min(Math.max(Number(msg.ms) || 0, 0), 5 * 60e3);
    return reply(() => new Promise((ok) => setTimeout(() => ok({ ok: true }), ms)));
  }
  // v1.32: the side panel opened mid-search: the search's tab says where it is
  if (msg.type === "live?") {
    return reply(async () => {
      const p = await getPull();
      if (!p || p.phase === "done" || !(await tabAlive(p.tabId))) return null;
      return chrome.tabs.sendMessage(p.tabId, { type: "live?" }).catch(() => null);
    });
  }
  if (msg.type === "stop") {
    return reply(async () => {
      const p = await getPull();
      if (p && p.tabId) chrome.tabs.sendMessage(p.tabId, { type: "stop" }).catch(() => {});
      if (p && p.phase !== "running") {
        await setPull({ phase: "done" });
        await setStatus({ running: false, stage: "done" });
        await closeCheckWindow();
        // v1.32: the search's own tab, if it never got going, goes too
        if (p.own && p.phase === "starting") chrome.tabs.remove(p.tabId).catch(() => {});
      }
      return { ok: true };
    });
  }
  // v1.32: "Go to the check" in the side panel: the search's tab, in front
  if (msg.type === "to_check") {
    return reply(async () => {
      const p = await getPull();
      const tab = p && p.phase === "check" ? await tabAlive(p.tabId) : null;
      if (tab) await focus(tab);
      return { ok: !!tab };
    });
  }
  if (msg.type === "open") {
    return reply(async () => {
      if (msg.page === "options") await chrome.runtime.openOptionsPage();
      else if (msg.page === "results") await chrome.tabs.create({ url: chrome.runtime.getURL("results.html") });
      return { ok: true };
    });
  }
  if (msg.type === "welcome") {
    return reply(async () => (await chrome.tabs.create({ url: chrome.runtime.getURL("wizard.html") }), { ok: true }));
  }
  if (msg.type === "estimate") {
    return reply(async () => {
      const cfg = await helper("/config");
      const n = cfg.ok ? (cfg.body.searches || []).length : 1;
      return Object.assign({ searches: n, stopped: await stoppedToday() }, RentalStore.estimate(await store.get("pulls", []), n, Date.now()));
    });
  }
  return false;
});

// Yad2 can send the whole tab to its check page: the page's own script is
// gone then, so the background notices and keeps the pull waiting for it.
chrome.tabs.onUpdated.addListener(async (tabId, info) => {
  if (!info.url || !info.url.includes(CHECK_HOST)) return;
  const p = await getPull();
  if (!p || tabId !== p.tabId || p.phase === "done") return;
  await enterCheck(tabId, "a redirect");
});

chrome.tabs.onRemoved.addListener(async (tabId) => {
  const p = await getPull();
  if (!p || tabId !== p.tabId || p.phase === "done") return;
  await setPull({ phase: "done" });
  await setStatus({ running: false, stage: "done", message: { key: "e_tab_closed" } });
  await closeCheckWindow();
});

chrome.windows.onRemoved.addListener((id) => {
  if (id === checkWindow) checkWindow = null;
});

// v1.33: the toolbar button puts the panel on the page you're on (overlay.js, by Chrome's
// activeTab: only that tab, only when you click), docked left in English and right in
// Hebrew. Where Chrome keeps extensions off a page (its own pages, the Web Store), the
// side panel opens instead.
const OVERLAY_FILES = ["i18n.js", "store.js", "cards.js", "panel.js", "panelhost.js", "overlay.js"];
const NO_PAGE = /^https:\/\/(chromewebstore\.google\.com|chrome\.google\.com\/webstore)\//;

function panelOnClick() {
  if (chrome.sidePanel && chrome.sidePanel.setPanelBehavior) chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: false }).catch(() => {});
}
panelOnClick();
chrome.runtime.onStartup.addListener(panelOnClick);

chrome.action.onClicked.addListener((tab) => {
  const page = /^https?:\/\//.test(tab.url || "") && !NO_PAGE.test(tab.url || "");
  const side = () => {
    if (chrome.sidePanel && chrome.sidePanel.open) return chrome.sidePanel.open({ windowId: tab.windowId }).catch(() => openResults());
    return openResults();
  };
  if (!page) return side(); // straight away: Chrome opens the side panel only in answer to the click
  chrome.scripting.executeScript({ target: { tabId: tab.id }, files: OVERLAY_FILES }).catch(() => side());
});

function openResults() {
  return chrome.tabs.create({ url: chrome.runtime.getURL("results.html") }).catch(() => {});
}

// the tabs showing the panel, which get the search's progress from here
async function overlayTabs() {
  try {
    return new Set((await chrome.storage.session.get("overlays")).overlays || []);
  } catch (e) {
    return new Set();
  }
}
async function setOverlay(tabId, on) {
  const s = await overlayTabs();
  if (on) s.add(tabId);
  else s.delete(tabId);
  try {
    await chrome.storage.session.set({ overlays: Array.from(s) });
  } catch (e) { /* no session storage (old Chrome): the panel still shows the finished search */ }
}
async function relayLive(msg) {
  for (const id of await overlayTabs()) chrome.tabs.sendMessage(id, msg).catch(() => setOverlay(id, false));
}
chrome.tabs.onRemoved.addListener((id) => { setOverlay(id, false); });

// first install: straight to setup
chrome.runtime.onInstalled.addListener((d) => {
  if (d.reason === "install") chrome.tabs.create({ url: chrome.runtime.getURL("wizard.html") });
  // v1.40: "Neither" no longer rejects; the listings it rejected before come back
  if (d.reason === "update") RentalStore.make(chrome.storage.local).undoNeither().catch(() => {});
});


// ---- Facebook, view-only (v1.66) -------------------------------------------------------
//
// Meta prohibits automated collection, and the penalty would land on the user's own account (Extension Plan). So nothing on
// Facebook runs by itself: the user selects a rental post's text and chooses "Keep this rental post" from the right-click
// menu. Only then is the selection read (and the page's address, to link back to the post); it's kept for the next search
// like a Madlan page the user opened. No fetching, scrolling or clicking, and no poster's name.
const FB_MENU = "rm_keep_facebook_post";
const FB_PAGES = ["https://www.facebook.com/*", "https://m.facebook.com/*", "https://web.facebook.com/*"];

function fbMenu() {
  try {
    chrome.contextMenus.removeAll(() => {
      RentalI18n.load(chrome.storage.local).then(() => {
        chrome.contextMenus.create({ id: FB_MENU, title: RentalI18n.t("fb_keep"), contexts: ["selection"], documentUrlPatterns: FB_PAGES });
      });
    });
  } catch (e) { /* no context menus: nothing to offer */ }
}
chrome.runtime.onInstalled.addListener(fbMenu);
chrome.runtime.onStartup.addListener(fbMenu);

async function keepFacebookPost(info, tab) {
  // the full selection (the menu's own copy can be shortened); the menu click lets this one tab be read once (activeTab)
  let got = { text: info.selectionText || "", url: (tab && tab.url) || info.pageUrl || "" };
  try {
    const [r] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: () => ({ text: String(getSelection() || ""), url: location.href }) });
    if (r && r.result && r.result.text.length >= got.text.length) got = r.result;
  } catch (e) { /* the menu's selection is enough */ }
  const item = RentalSites.facebookPost(got);
  if (!item) return notify(FB_MENU, "fb_title", "fb_too_short");
  if (item.price == null) return notify(FB_MENU, "fb_title", "fb_no_price");
  await keepSeen({ rows: [], item }, "facebook");
  return notify(FB_MENU, "fb_title", "fb_kept");
}
chrome.contextMenus && chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === FB_MENU && tab) keepFacebookPost(info, tab).catch(() => {});
});
