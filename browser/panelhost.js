/*
 * Rental Matcher: what the panel does, wherever it is (v1.33; it was
 * sidepanel.js in v1.32). Used by the panel on a page (overlay.js, docked,
 * resizable) and by Chrome's side panel (sidepanel.js, `embedded`).
 *
 * A search reads Yad2 from a Yad2 tab of its own, opened in the background
 * and closed when it's done; it comes to the front only if Yad2 asks for
 * its check, which only you can do. That tab sends its progress as it goes
 * ("live" messages: to the side panel directly, to a panel on a page
 * through the background); the finished search is kept in storage, which
 * the panel shows when it opens.
 */
(function (root) {
  "use strict";

  async function run(o) {
  o = o || {};
    const I = RentalI18n;
    const t = I.t;
    const store = RentalStore.make(chrome.storage.local);
    // v1.43: once the extension is reloaded under an open page, this copy can't reach it; it goes quietly
    const alive = () => {
      try {
        return !!(chrome.runtime && chrome.runtime.id);
      } catch (e) {
        return false;
      }
    };
    const send = (msg) => {
      try {
        return chrome.runtime.sendMessage(msg).catch(() => null);
      } catch (e) {
        return Promise.resolve(null);
      }
    };
    const hidesPhotoless = (ui) => (root.RentalCards ? root.RentalCards.hidesPhotoless(ui) : !(ui && ui.hideNoPhotos === false));
    await I.load(chrome.storage.local);

    const first = await store.get("ui", {});
    const panel = RentalPanel.create(document, {
      embedded: !!o.embedded,
      resizable: !o.embedded,
      open: true,
      noFab: true,
      width: first.panelWidth,
      onWidth: (w) => store.get("ui", {}).then((ui) => store.set("ui", Object.assign(ui, { panelWidth: w }))),
      onClose: () => destroy(),
      openResults: () => send({ type: "open", page: "results" }),
      openSettings: () => send({ type: "open", page: "options" }),
      toggleLang: async () => {
        const ui = await store.get("ui", {});
        ui.lang = I.lang === "he" ? "en" : "he";
        await store.set("ui", ui);
      },
    });
    if (o.embedded) document.title = t("app");
    let running = false;
    let lastShown = null;

    const errorText = (key) => (key && t(key) !== key ? { key } : { key: "e_generic", params: { detail: key || "" } });

    function setRunning(on) {
      running = !!on;
      panel.setRunning(running);
    }

    async function estimate() {
      const e = await send({ type: "estimate" });
      if (!e) return;
      if (e.stopped) return panel.setEstimate(t(e.stopped), "", true);
      panel.setEstimate(t("pp_takes", { t: I.duration(e.ms), what: t(e.kind === "repeat" ? "pp_repeat" : "pp_first") }),
        t("pp_avg", { a: I.duration(e.first), am: t(e.measured.first ? "pp_yours" : "pp_est"), b: I.duration(e.repeat),
          bm: t(e.measured.repeat ? "pp_yours" : "pp_est"), n: e.searches }), false);
    }

    /** What the search's tab says as it goes. */
    function live(m) {
      if (!m) return;
      if (m.state) {
        lastShown = m.state;
        panel.render(m.state);
      }
      if (typeof m.running === "boolean") setRunning(m.running);
      if (m.check) panel.showCheck(m.check);
      else panel.clearCheck();
    }

    /**
     * What the background says about the search: Yad2's check (its page has
     * no script of ours, so this is how the panel hears of it), a stop for
     * the day, or a search that ended without its tab saying so.
     */
    function onStatus(st) {
      if (st.stage === "check") {
        const waiting = !st.running && (!st.message || st.message.key === "ck_text");
        panel.showCheck(waiting
          ? { title: t("ck_title"), text: t("ck_text"), button: t("ck_go"), onButton: () => send({ type: "to_check" }) }
          : { title: t("st_check"), text: I.msg(st.message) });
      } else if (st.stage === "cooldown") {
        panel.showCheck({ title: t("ck_pause_title"), text: I.msg(st.message) });
      } else if (st.running) panel.clearCheck();
      if (!st.running && running && st.stage !== "check" && st.stage !== "cooldown") {
        setRunning(false);
        if (st.message || st.error) panel.render(Object.assign({}, lastShown || {}, { stage: "done", message: st.message, error: st.error }));
      }
    }

    panel.onPull(async () => {
      setRunning(true);
      panel.clearCheck();
      panel.render(Object.assign({}, lastShown || {}, { stage: "starting", error: null, message: null, read: null, elapsed: 0, eta: null }));
      const r = await send({ type: "pull" });
      if (!r || !r.ok) {
        setRunning(false);
        panel.render(Object.assign({}, (await store.get("results", null)) || { stage: "done" }, { error: errorText(r && r.error) }));
      }
    });
    panel.onStop(() => send({ type: "stop" }));
    panel.onMark(async (x, patch) => { await store.setMark(x, patch); });
    panel.onSort((k) => store.get("ui", {}).then((ui) => store.set("ui", Object.assign(ui, { sort: k }))));
    panel.onDetail((on) => store.get("ui", {}).then((ui) => store.set("ui", Object.assign(ui, { detail: on }))));
    panel.onApply(async (sg) => {
      const r = await send({ type: "helper", path: "/relax", body: { name: sg.name, change: sg.change } });
      return !!(r && r.ok && r.body && r.body.saved);
    });

    // the search's progress: straight from its tab to the side panel; through the background to a panel on a page
    const onMessage = (m) => {
      if (m && m.type === "live") live(m);
      return false;
    };
    chrome.runtime.onMessage.addListener(onMessage);
    const onStorage = (c, area) => {
      if (area !== "local") return;
      if (!alive()) return destroy();
      if (c.marks) panel.setMarks(c.marks.newValue || {});
      if (c.ui) panel.setHideNoPhotos(hidesPhotoless(c.ui.newValue));
      if (c.results && c.results.newValue) {
        lastShown = c.results.newValue;
        panel.render(c.results.newValue);
      }
      if (c.status && c.status.newValue) onStatus(c.status.newValue);
      if (c.pulls || c.checks) estimate();
      if (c.ui && c.ui.newValue && c.ui.newValue.lang && c.ui.newValue.lang !== I.lang) {
        I.setLang(c.ui.newValue.lang);
        if (o.embedded) document.title = t("app");
        panel.words();
        estimate();
      }
    };
    chrome.storage.onChanged.addListener(onStorage);
    let gone = false;
    function destroy() {
      if (gone) return;
      gone = true;
      try {
        chrome.runtime.onMessage.removeListener(onMessage);
        chrome.storage.onChanged.removeListener(onStorage);
      } catch (e) { /* the extension was reloaded under this page: nothing to remove from */ }
      panel.host.remove();
      if (o.onGone) o.onGone();
    }

    const [marks, ui, results, status] = await Promise.all([store.get("marks", {}), store.get("ui", {}), store.get("results", null),
      store.get("status", {})]);
    panel.setMarks(marks);
    panel.setHideNoPhotos(hidesPhotoless(ui));
    if (ui.sort) panel.setSort(ui.sort);
    if (ui.detail) panel.setDetail(true);
    if (results) {
      lastShown = results;
      panel.render(results);
    }
    // a search already going: its tab says where it is
    const now = await send({ type: "live?" });
    if (now && now.state) live(now);
    else if (status.running && Date.now() - (status.at || 0) < 60e3) setRunning(true);
    if (status.stage === "check" && Date.now() - (status.at || 0) < 30 * 60e3) onStatus(status);
    estimate();
    // the first time: the quick setup opens next to the panel
    if (!ui.onboarded) send({ type: "welcome" });
    return { panel, destroy };

  }

  root.RentalPanelHost = { run };
})(typeof globalThis !== "undefined" ? globalThis : this);
