/*
 * Rental Matcher: the panel on the page you're on (v1.33).
 *
 * The toolbar button runs this on the tab in front (Chrome's activeTab: no
 * standing permission on any site). It docks the panel over the page:
 * left in English, right in Hebrew, as wide as you drag it. A second click
 * closes it, and so does its ×. Going to another site takes it away with
 * the page; the toolbar button brings it back. The panel's own work is
 * panelhost.js; this only opens and closes it, and tells the background
 * this tab wants the search's progress ("overlay" on/off).
 *
 * v1.43: after the extension is reloaded or updated, a tab can still hold
 * the panel of the old copy, which can't reach the extension any more
 * ("Extension context invalidated" on Chrome's Errors page, from overlay.js
 * and panelhost.js). The toolbar button now replaces that old panel with a
 * working one instead of asking it to open.
 */
(function () {
  "use strict";
  const alive = () => {
    try {
      return !!(chrome.runtime && chrome.runtime.id);
    } catch (e) {
      return false;
    }
  };
  const old = window.__rmOverlay;
  if (old && typeof old.alive === "function" && old.alive()) {
    old.toggle();
    return;
  }
  if (old) {
    // an older copy's panel: take it off the page; this copy opens a working one
    for (const n of document.querySelectorAll("#rental-matcher-root")) n.remove();
  }
  const send = (msg) => {
    try {
      return chrome.runtime.sendMessage(msg).catch(() => null);
    } catch (e) {
      return Promise.resolve(null); // the extension was reloaded under this page
    }
  };
  let host = null;
  let opening = false;

  async function open() {
    if (host || opening || !alive()) return;
    opening = true;
    try {
      host = await RentalPanelHost.run({
        onGone: () => {
          host = null;
          send({ type: "overlay", on: false });
        },
      });
      send({ type: "overlay", on: true });
    } catch (e) {
      host = null; // the panel couldn't start (the extension went away mid-way): the next click tries again
    } finally {
      opening = false;
    }
  }

  window.__rmOverlay = { alive, toggle() { if (host) host.destroy(); else open(); } };
  window.addEventListener("pagehide", () => { if (host) send({ type: "overlay", on: false }); });
  open();
})();
