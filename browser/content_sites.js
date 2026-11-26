/*
 * Rental Matcher on Komo and Madlan pages the user opens himself (v1.27).
 *
 * Reads the page that's already on screen (sites.js readPage): the
 * listings on a results page, or one listing's facts. Nothing is fetched
 * and nothing on the page is clicked or changed; only a small note says
 * what was kept. The background keeps it a few days, for the next search.
 *
 * Madlan answers automatic reading with a bot check, so this is the only
 * way its listings come in. On its check page nothing is found, and
 * nothing is done.
 */
(function () {
  "use strict";
  if (window.__rentalMatcherSites) return;
  window.__rentalMatcherSites = true;

  const I = RentalI18n;

  function note(text) {
    const box = document.createElement("div");
    box.textContent = text;
    box.setAttribute("role", "status");
    box.dir = I.lang === "he" ? "rtl" : "ltr";
    Object.assign(box.style, {
      position: "fixed", bottom: "16px", insetInlineStart: "16px", zIndex: 2147483646, background: "#1f2328", color: "#fff",
      font: "13px/1.4 system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif", padding: "8px 12px", borderRadius: "10px",
      boxShadow: "0 6px 20px rgba(16,24,40,.25)", opacity: "0", transition: "opacity .25s", pointerEvents: "none",
    });
    document.documentElement.append(box);
    requestAnimationFrame(() => { box.style.opacity = "0.94"; });
    setTimeout(() => { box.style.opacity = "0"; }, 3500);
    setTimeout(() => box.remove(), 4000);
  }

  async function look() {
    // the page's own HTML as the server sent it: Madlan's data is in a script, Komo's in the markup
    const found = RentalSites.readPage(location.href, document.documentElement.outerHTML);
    if (!found) return;
    const r = await chrome.runtime.sendMessage({ type: "seen", found }).catch(() => null);
    if (!r || !r.ok) return;
    await I.load(chrome.storage.local);
    note(found.item ? I.t("cap_kept1") : I.t("cap_kept", { n: found.rows.length }));
  }

  look();
})();
