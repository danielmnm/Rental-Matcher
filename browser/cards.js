/*
 * Rental Matcher: one listing's card (v1.31), the same on the Yad2 panel
 * and on the results page, in English or Hebrew (i18n.js).
 *
 * The helper sends what a listing confirms, what it leaves open and what
 * goes past a limit as data; the card words it. Everything from a listing
 * goes in as text, never as HTML, and Hebrew or English from the listing
 * sits in its own <bdi>, so it never reorders the words around it. A link
 * is only ever to a listing page on a site we read, and a photo only ever
 * comes from a site's own image server.
 *
 * v1.31: two views. Simple (the default): shop-style, photo first. Detailed:
 * everything, organized, with the numbers behind the match. Each card can
 * switch on its own; the panel and the results page switch them all.
 */
(function (root) {
  "use strict";

  const CSS = `
  .rm-card { --g:#1a7f37; --gbg:#e9f7ef; --w:#9a6700; --wbg:#fff6dd; --b:#b42318; --bbg:#fdecea; --i:#57606a; --ibg:#f1f3f5;
    --line:#e3e6ea; --ink:#1d2125; --soft:#57606a; --acc:#1f6feb;
    background:#fff; border:1px solid var(--line); border-radius:12px; padding:14px 14px 10px;
    margin:0 0 12px; color:var(--ink); font-size:13px; line-height:1.45; box-shadow:0 1px 2px rgba(16,24,40,.04); }
  .rm-card.rm-fav { border-color:#e3b341; box-shadow:0 0 0 1px #e3b341 inset; }
  .rm-card.rm-rejected { opacity:.6; }
  .rm-head { display:flex; justify-content:space-between; gap:12px; align-items:start; }
  .rm-score { min-width:74px; text-align:center; border-radius:10px; padding:6px 6px 5px; background:var(--gbg); color:var(--g); }
  .rm-score.good { background:#eef6ea; color:#2d7a2b; }
  .rm-score.fair { background:var(--wbg); color:var(--w); }
  .rm-score.basic { background:var(--ibg); color:var(--i); }
  .rm-pct { font-size:20px; font-weight:700; line-height:1.1; display:block; }
  .rm-fit { font-size:11px; display:block; line-height:1.2; margin-top:2px; }
  .rm-title { min-width:0; display:block; margin-top:10px; }
  /* v1.30: the place is a real button: raised, lifts on hover, presses in, its arrow slides */
  a.rm-go { position:relative; display:flex; align-items:center; gap:12px; text-decoration:none; color:#fff; border-radius:14px; padding:12px 14px;
    background:linear-gradient(180deg,#3b82f6 0%,#1f6feb 100%); box-shadow:0 1px 0 rgba(255,255,255,.25) inset, 0 4px 12px rgba(31,111,235,.28);
    transition:transform .12s ease, box-shadow .15s ease, filter .15s ease; overflow:hidden; cursor:pointer; }
  a.rm-go:hover { transform:translateY(-1px); box-shadow:0 1px 0 rgba(255,255,255,.25) inset, 0 8px 20px rgba(31,111,235,.35); filter:brightness(1.04); }
  a.rm-go:active { transform:translateY(1px) scale(.985); box-shadow:0 2px 6px rgba(31,111,235,.3); }
  a.rm-go:focus-visible { outline:3px solid #9ec5ff; outline-offset:2px; }
  a.rm-go .rm-pin { font-size:20px; flex:none; }
  a.rm-go .rm-where { flex:1; min-width:0; }
  a.rm-go .rm-addr { font-size:16px; color:#fff; }
  a.rm-go .rm-city { color:rgba(255,255,255,.85); }
  .rm-go-site { flex:none; display:inline-flex; align-items:center; gap:6px; font-size:12px; font-weight:700; background:rgba(255,255,255,.18);
    border-radius:999px; padding:5px 10px; white-space:nowrap; }
  .rm-go-site .rm-arrow { display:inline-block; transition:transform .15s ease; }
  a.rm-go:hover .rm-arrow { transform:translateX(3px); }
  [dir=rtl] .rm-go-site .rm-arrow { transform:scaleX(-1); }
  [dir=rtl] a.rm-go:hover .rm-arrow { transform:scaleX(-1) translateX(3px); }
  /* v1.30: new, price dropped, a good deal */
  .rm-badges { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:8px; }
  .rm-badge { border-radius:999px; padding:2px 9px; font-size:11px; font-weight:700; letter-spacing:.01em; }
  .rm-badge.new { background:#1f6feb; color:#fff; }
  .rm-badge.drop { background:#e6f6ec; color:#137333; }
  .rm-badge.deal { background:#fff1d6; color:#8a5300; }
  .rm-ic { margin-inline-end:4px; }
  .rm-saving { color:var(--g) !important; font-weight:600; }
  .rm-addr { font-weight:600; font-size:14px; overflow-wrap:anywhere; }
  .rm-city { color:var(--soft); font-size:12px; }
  .rm-new { display:inline-block; margin-inline-start:6px; background:#1f6feb; color:#fff; border-radius:999px; font-size:10px; font-weight:700;
    padding:1px 7px; vertical-align:2px; }
  .rm-price { font-weight:700; font-size:15px; white-space:nowrap; text-align:end; }
  .rm-price small { display:block; font-weight:400; font-size:11px; color:var(--soft); }
  .rm-meta { display:flex; flex-wrap:wrap; gap:6px; margin-top:10px; }
  .rm-chip { border:1px solid var(--line); border-radius:6px; padding:1px 7px; font-size:12px; color:var(--soft); background:#fafbfc; }
  .rm-sec { margin-top:10px; padding-top:10px; border-top:1px solid var(--line); }
  .rm-sec-t { font-size:11px; font-weight:600; letter-spacing:.04em; text-transform:uppercase; color:var(--soft); margin-bottom:6px; }
  .rm-trip { display:flex; justify-content:space-between; gap:8px; }
  .rm-trip b { white-space:nowrap; }
  .rm-trip.est b { font-weight:500; color:var(--soft); }
  .rm-bubbles { display:flex; flex-wrap:wrap; gap:6px; }
  .rm-bub { border-radius:999px; padding:2px 9px; font-size:12px; border:1px solid transparent; }
  .rm-bub.good { background:var(--gbg); color:var(--g); border-color:#b7e1c4; }
  .rm-bub.weak { background:var(--wbg); color:var(--w); border-color:#f0d58a; }
  .rm-bub.bad { background:var(--bbg); color:var(--b); border-color:#f3b8b1; }
  .rm-bub.info { background:var(--ibg); color:var(--i); border-color:#dde1e5; }
  .rm-notes { list-style:none; margin:0; padding:0; }
  .rm-notes li { position:relative; padding-inline-start:20px; margin:4px 0; }
  .rm-notes li::before { position:absolute; inset-inline-start:0; top:0; width:16px; text-align:center; }
  .rm-notes li.risk { color:var(--w); }
  .rm-notes li.risk::before { content:"⚠"; }
  .rm-notes li.ask::before { content:"?"; font-weight:700; color:var(--soft); }
  .rm-notes li.flag { color:var(--w); }
  .rm-notes li.flag::before { content:"!"; font-weight:700; }
  .rm-notes li.hide { color:var(--b); }
  .rm-notes li.hide::before { content:"✕"; }
  .rm-foot { display:flex; flex-wrap:wrap; align-items:center; gap:6px; margin-top:12px; }
  .rm-foot .rm-sp { flex:1; }
  .rm-btn { border:1px solid var(--line); background:#fff; color:var(--ink); border-radius:8px; padding:4px 10px; font-size:12px;
    cursor:pointer; font-family:inherit; line-height:1.4; }
  .rm-btn:hover { filter:brightness(.97); }
  .rm-btn.rm-b-fav { border-color:#ecd28b; color:#8a6100; background:#fffbeb; }
  .rm-btn.rm-b-fav.on { background:#f5c518; border-color:#e0b000; color:#3d2d00; font-weight:600; }
  .rm-btn.rm-b-int, .rm-btn.rm-b-view { border-color:#c9dbff; color:#1f5fd1; background:#f3f7ff; }
  .rm-btn.rm-b-int.on, .rm-btn.rm-b-view.on { background:#1f6feb; border-color:#1f6feb; color:#fff; font-weight:600; }
  .rm-btn.rm-b-rej { border-color:#f3b8b1; color:#b42318; background:#fff5f4; }
  .rm-btn.rm-b-rej.on { background:#d92d20; border-color:#d92d20; color:#fff; font-weight:600; }
  .rm-btn.rm-b-plain { border-color:#c9dbff; color:#1f5fd1; }
  .rm-when { border:1px solid var(--line); border-radius:8px; padding:3px 6px; font-size:12px; font-family:inherit; }
  .rm-link { color:var(--acc); text-decoration:none; font-size:12px; white-space:nowrap; }
  .rm-link:hover { text-decoration:underline; }
  .rm-read { color:var(--soft); font-size:11px; }
  .rm-src { border-radius:6px; padding:1px 7px; font-size:11px; font-weight:600; background:#eef1f4; color:#3d444d; }
  .rm-src.komo { background:#fff1e6; color:#9a3d00; }
  .rm-src.madlan { background:#efeaff; color:#5b33c4; }
  .rm-chip.approx { border-style:dashed; }
  /* v1.31: the simple card, shop-style, and its photos */
  .rm-card.rm-simple { padding:0; overflow:hidden; border-radius:16px; transition:box-shadow .15s, transform .15s; }
  .rm-card.rm-simple:hover { box-shadow:0 2px 4px rgba(16,24,40,.06), 0 12px 28px rgba(16,24,40,.10); }
  .rm-photo { position:relative; aspect-ratio:var(--ph-ratio, 4 / 3); background:linear-gradient(135deg,#dfe7f5,#eef1f6); overflow:hidden; }
  .rm-photo img { width:100%; height:100%; object-fit:cover; display:block; }
  .rm-photo.none, .rm-photo.broken { display:grid; place-items:center; align-content:center; color:#8a94a3; }
  .rm-photo.broken img { visibility:hidden; position:absolute; }
  .rm-photo .rm-ph-icon { font-size:38px; line-height:1; }
  .rm-photo .rm-ph-none { font-size:12.5px; margin-top:4px; }
  .rm-photo .rm-ph-why { font-size:11.5px; max-width:300px; text-align:center; margin:4px 14px 0; line-height:1.35; }
  .rm-photo.none.warn { background:linear-gradient(135deg,#fff4e5,#fdebd3); color:#9a5a00; }
  .rm-photo.strip { --ph-ratio: 16 / 7; border-radius:10px; margin-bottom:10px; }
  .rm-ph-nav { position:absolute; top:50%; transform:translateY(-50%); width:34px; height:34px; border-radius:50%; border:0; cursor:pointer;
    background:rgba(255,255,255,.88); color:#1d2125; font-size:22px; line-height:1; box-shadow:0 2px 6px rgba(0,0,0,.2); opacity:0; transition:opacity .15s, transform .1s; }
  .rm-photo:hover .rm-ph-nav, .rm-ph-nav:focus-visible { opacity:1; }
  .rm-ph-nav:active { transform:translateY(-50%) scale(.92); }
  .rm-ph-nav.prev { inset-inline-start:8px; } .rm-ph-nav.next { inset-inline-end:8px; }
  .rm-ph-count { position:absolute; bottom:8px; inset-inline-end:10px; font-size:11px; color:#fff; background:rgba(0,0,0,.45); padding:1px 8px; border-radius:999px; }
  .rm-photo .rm-badges { position:absolute; top:10px; inset-inline-start:10px; margin:0; }
  .rm-photo .rm-badge { box-shadow:0 1px 3px rgba(0,0,0,.15); font-size:12px; padding:3px 10px; }
  .rm-heart { position:absolute; top:8px; inset-inline-end:8px; width:38px; height:38px; border-radius:50%; border:0; cursor:pointer; font-size:19px;
    background:rgba(255,255,255,.92); color:#1d2125; box-shadow:0 2px 6px rgba(0,0,0,.18); transition:transform .1s; }
  .rm-heart:active { transform:scale(.88); } .rm-heart.on { color:#e5484d; }
  .rm-body { padding:12px 14px 12px; display:flex; flex-direction:column; gap:8px; }
  .rm-shead { display:flex; align-items:baseline; justify-content:space-between; gap:8px; flex-wrap:wrap; }
  .rm-bigprice { font-size:22px; font-weight:800; letter-spacing:-.3px; white-space:nowrap; }
  .rm-bigprice small { font-size:13px; color:var(--soft); font-weight:400; }
  .rm-verdict { font-size:12px; font-weight:700; border-radius:999px; padding:3px 10px; white-space:nowrap; background:var(--ibg); color:var(--i); }
  .rm-verdict.great { background:#e6f6ec; color:#137333; } .rm-verdict.good { background:#eef6ea; color:#2d7a2b; } .rm-verdict.fair { background:var(--wbg); color:var(--w); }
  .rm-simple .rm-title { margin-top:2px; }
  .rm-simple a.rm-go { padding:10px 12px; flex-wrap:wrap; row-gap:8px; }
  .rm-simple a.rm-go .rm-where { flex:1 1 150px; }
  .rm-simple a.rm-go .rm-go-site { margin-inline-start:auto; }
  .rm-simple a.rm-go .rm-addr { font-size:15px; }
  .rm-sfacts { color:var(--soft); font-size:13px; }
  .rm-strip { font-size:14px; } .rm-strip.est b { font-weight:500; color:var(--soft); } .rm-strip small { color:var(--soft); }
  .rm-sicons { display:flex; flex-wrap:wrap; gap:6px; }
  .rm-sicons span { background:#f3f5f8; border-radius:999px; padding:2px 9px; font-size:12px; }
  .rm-sicons span.more { color:var(--soft); }
  .rm-sicons.other span { background:#fff; border:1px solid var(--line); color:#3d444d; } /* v1.54: the rest of what it has */
  .rm-sask { font-size:12.5px; color:var(--w); background:var(--wbg); border-radius:8px; padding:5px 9px; }
  .rm-sask.ask { color:#3d444d; background:#f3f5f8; } .rm-sask.hide { color:var(--b); background:var(--bbg); }
  .rm-sfoot { display:flex; align-items:center; gap:6px; flex-wrap:wrap; margin-top:2px; }
  .rm-sfoot .rm-sp, .rm-foot .rm-sp { flex:1; }
  .rm-more { position:relative; }
  .rm-more summary { list-style:none; display:inline-block; }
  .rm-more summary::-webkit-details-marker { display:none; }
  .rm-menu { position:absolute; bottom:calc(100% + 6px); inset-inline-start:0; z-index:3; background:#fff; border:1px solid var(--line); border-radius:12px;
    padding:8px; display:flex; flex-direction:column; gap:6px; min-width:190px; box-shadow:0 10px 30px rgba(16,24,40,.16); }
  .rm-detail { border:0; background:none; color:var(--acc); font:inherit; font-size:12px; font-weight:600; cursor:pointer; padding:4px 2px; }
  .rm-detail:hover { text-decoration:underline; }
  /* v1.31: the detailed card's numbers */
  .rm-kv { display:grid; grid-template-columns:max-content 1fr; gap:3px 14px; margin:0; font-size:12.5px; }
  .rm-kv dt { color:var(--soft); } .rm-kv dd { margin:0; font-variant-numeric:tabular-nums; }
  .rm-raw { margin-top:8px; font-size:12px; } .rm-raw summary { cursor:pointer; color:var(--soft); }
  .rm-raw ul { margin:6px 0 0; padding-inline-start:18px; font-family:ui-monospace,SFMono-Regular,Consolas,monospace; font-size:11.5px; color:#3d444d; }
  bdi { unicode-bidi:isolate; }
  /* v1.32: "Want more options?" in one line; the options open on hover, focus or a click */
  .rm-moreline { position:relative; display:flex; align-items:center; gap:8px; background:#f3f7ff; border:1px solid #c9dbff; border-radius:10px;
    padding:7px 12px; margin:0 0 12px; font-size:13px; color:#1d2125; cursor:default; }
  .rm-moreline > b { font-weight:600; }
  .rm-moreline > span { color:#1f5fd1; flex:1; }
  .rm-moreline > i { font-style:normal; color:#57606a; transition:transform .15s; }
  .rm-moreline:hover > i, .rm-moreline:focus-within > i, .rm-moreline.open > i { transform:rotate(180deg); }
  .rm-morepop { display:none; position:absolute; z-index:5; top:100%; inset-inline:0; margin-top:4px; background:#fff; border:1px solid #c9dbff;
    border-radius:10px; box-shadow:0 8px 24px rgba(16,24,40,.14); padding:4px 12px; }
  .rm-moreline::after { content:""; position:absolute; inset-inline:0; top:100%; height:6px; } /* the gap to the list keeps the hover */
  .rm-moreline:hover .rm-morepop, .rm-moreline:focus-within .rm-morepop, .rm-moreline.open .rm-morepop { display:block; }
  .rm-morepop ul { list-style:none; margin:0; padding:0; }
  .rm-morepop li { display:flex; align-items:center; gap:8px; padding:7px 0; border-top:1px solid #eef2f8; }
  .rm-morepop li:first-child { border-top:0; }
  .rm-morepop li span { flex:1; }
  .rm-morepop li em { font-style:normal; color:#1f5fd1; font-weight:600; white-space:nowrap; }
  .rm-morepop button { border:1px solid #1f6feb; background:#fff; color:#1f6feb; border-radius:8px; padding:3px 10px; font-size:12px; cursor:pointer; }
  .rm-morepop button:hover { background:#1f6feb; color:#fff; }
  `;

  // a listing page on a site we read, and nothing else
  const LINKS = {
    yad2: /^https:\/\/www\.yad2\.co\.il\/realestate\/item\/[A-Za-z0-9]+$/,
    komo: /^https:\/\/www\.komo\.co\.il\/code\/nadlan\/details\/\?modaaNum=\d+$/,
    madlan: /^https:\/\/www\.madlan\.co\.il\/listings\/[A-Za-z0-9_-]+$/,
    facebook: /^https:\/\/www\.facebook\.com\/(?:groups\/[A-Za-z0-9._-]+\/posts\/\d+|marketplace\/item\/\d+)$/,  // v1.66: a post the user kept
  };
  const siteOf = (url) => Object.keys(LINKS).find((k) => LINKS[k].test(url || "")) || null;
  const SAFE_LINK = { test: (url) => !!siteOf(url) };

  // v1.30: an icon for each kind of fact (emoji everyone's system already has)
  const ICONS = {
    ac: "❄️", mamad: "🛡️", building_shelter: "🛡️", balcony: "🌿", no_balcony: "🚫", elevator: "↕️", no_elevator: "🚫",
    parking_own: "🅿️", parking_building: "🅿️", parking_street: "🅿️", parking_none: "🚫", renovated: "✨", not_renovated: "🔧",
    pets: "🐾", accessible: "♿", bars: "🔒", room_share: "👥", housing_unit: "🏚️", short_lease: "⏳", furniture_for_sale: "🏷️", whole: "🏠", suits_roommates: "👥", garden: "🌳", roof: "🌇",
    house: "🏡", studio: "🛏️", available: "📅", furniture: "🛋️", fan: "🌀",
    parking_any: "🅿️", public_shelter: "🛡️", no_building_shelter: "⚠️", agency_no_fee: "🤝", no_parking_space: "🚫",
    floor_shelter: "🛡️", solar_heater: "☀️", tornado_ac: "🌬️", storage: "📦", kosher_kitchen: "🍽️", maybe_furnished: "🛋️", pandor_doors: "🚪", // v1.54; pandor_doors v1.55
  };
  // v1.54: the furniture the text names (item_sofa...) had no icon, so the simple card never showed it
  const iconOf = (k) => ICONS[k] || (typeof k === "string" && k.startsWith("item_") ? "🛋️" : null);
  const MODE_ICON = { ebike: "🛵", bike: "🚲", walk: "🚶", car: "🚗" };

  /**
   * v1.38: a trip's minutes from its evidence, as the helper writes it (commute.py car_times and
   * _minutes_from): for results saved before v1.37, whose drives had a range and no number.
   */
  function timesFrom(ev) {
    const s = typeof ev === "string" ? ev : "";
    let m = s.match(/about (\d+) min in typical traffic, (\d+) min at rush hour/);
    if (m) return { usual: +m[1], worst: +m[2], estimate: false };
    m = s.match(/roughly (\d+)-(\d+) min in typical traffic, (\d+)-(\d+) at rush hour/);
    if (m) return { usual: Math.round((+m[1] + +m[2]) / 2), worst: +m[4], estimate: true };
    m = s.match(/about ([\d.]+) min/);
    return m ? { about: +m[1] } : {};
  }

  /**
   * Every copy of this apartment we can link to, and the one to open:
   * the lowest rent; on a tie Yad2, then the card's own copy.
   */
  function bestOffer(x) {
    // v1.63: a merged apartment's own rent is price_own (price is the cheapest copy's, which it was scored at)
    const offers = [{ source: x.source || "yad2", url: x.url, price: typeof x.price_own === "number" ? x.price_own : x.price, own: true }]
      .concat((x.also || []).map((o) => ({ source: o.source, url: o.url, price: o.price })))
      .filter((o) => siteOf(o.url));
    const rank = (o) => [typeof o.price === "number" && o.price > 0 ? o.price : Infinity, siteOf(o.url) === "yad2" ? 0 : o.own ? 1 : 2];
    const best = offers.slice().sort((a, b) => { const p = rank(a), q = rank(b); return p[0] - q[0] || p[1] - q[1]; })[0] || null;
    return { offers, best };
  }

  // v1.31: a listing's photos, from the sites' own image servers, and nothing else
  const PHOTO = [
    /^https:\/\/img\.yad2\.co\.il\/Pic\/[A-Za-z0-9_\/.-]+\.(?:jpe?g|png|webp)$/i,
    /^https:\/\/www\.komo\.co\.il\/api\/modaot\/tmunot\/showPic\/list\/\?picNum=\d+&luachNum=2$/,
    /^https:\/\/images2\.madlan\.co\.il\/t:nonce:v=2;resize:width=640\/bulletins\/[^\s"'<>\\]+$/,
  ];
  const safePhotos = (list) => (Array.isArray(list) ? list : []).filter((u) => typeof u === "string" && PHOTO.some((re) => re.test(u))).slice(0, 20);

  /**
   * v1.40: a listing with no photos to show: none of its site's photos (Yad2 and Madlan send
   * them with the search, so none there means none in the listing), or a count of 0. Komo's
   * photos are read off its page, so one we couldn't read isn't "no photos".
   */
  const photoless = (x) => !!x && (x.photos_state === "none"
    || ((x.source || "yad2") !== "komo" && safePhotos(x.photos).length === 0));
  /** v1.40: the setting, on unless turned off (setup page, "Hide listings with no photos"). */
  const hidesPhotoless = (ui) => !(ui && ui.hideNoPhotos === false);

  const fitOf = (x) => x.fit || (x.match_expected >= 70 ? "great" : x.match_expected >= 55 ? "good" : x.match_expected >= 40 ? "fair" : "basic");

  /** What both views share: words, the cheapest copy, the tags, the notes, the buttons. */
  function parts(doc, x, ctx) {
    const I = ctx.I || root.RentalI18n;
    const t = I.t;
    const mark = ctx.mark || {};
    const prefs = ctx.prefs || {};
    const el = (tag, cls, text) => {
      const e = doc.createElement(tag);
      if (cls) e.className = cls;
      if (text != null) e.textContent = String(text);
      return e;
    };
    const iso = (text) => {
      const b = el("bdi", null, text);
      b.dir = "auto";
      return b;
    };
    const { offers, best } = bestOffer(x);
    const siteName = (url) => t(`site_${siteOf(url)}`);

    // the place: the way in, a big button to the cheapest copy (Yad2 unless another site asks less)
    function place() {
      const title = el(best ? "a" : "div", "rm-title");
      const addr = el("div", "rm-addr");
      addr.append(iso(x.street || x.neighborhood || x.city || ""));
      const city = el("div", "rm-city");
      [x.street && x.neighborhood, x.city].filter((v) => v && typeof v === "string").forEach((w, i) => {
        if (i) city.append(", ");
        city.append(iso(w));
      });
      if (!best) {
        title.append(addr, city);
        return title;
      }
      title.classList.add("rm-go");
      title.href = best.url;
      title.target = "_blank";
      title.rel = "noopener noreferrer";
      title.title = t("open_on", { site: siteName(best.url) });
      const go = el("span", "rm-go-site", t("open_on", { site: siteName(best.url) }));
      go.append(el("span", "rm-arrow", "→"));
      const whereBox = el("span", "rm-where");
      whereBox.append(addr, city);
      title.append(el("span", "rm-pin", "📍"), whereBox, go);
      return title;
    }

    const shownPrice = best && typeof best.price === "number" && best.price > 0 ? best.price : x.price;
    const ownPrice = typeof x.price_own === "number" ? x.price_own : x.price;
    function saving() {
      if (best && !best.own && typeof ownPrice === "number" && shownPrice < ownPrice) {
        return el("small", "rm-saving", t("cheaper_on", { n: I.money(ownPrice - shownPrice), site: siteName(best.url) }));
      }
      return null;
    }

    function badges() {
      const box = el("div", "rm-badges");
      if (ctx.isNew) box.append(el("span", "rm-badge new", t("new_badge")));
      if (x.drop && typeof x.drop.was === "number" && typeof x.drop.now === "number" && x.drop.was > x.drop.now) {
        const b = el("span", "rm-badge drop", `↓ ${t("b_drop", { n: I.money(x.drop.was - x.drop.now) })}`);
        b.title = t("b_drop_tip", { was: I.money(x.drop.was), now: I.money(x.drop.now) });
        box.append(b);
      }
      if (x.deal && typeof x.deal.median === "number") {
        const b = el("span", "rm-badge deal", `🏷️ ${t("b_deal")}`);
        b.title = t(x.deal.scope === "hood" ? "b_deal_tip_hood" : "b_deal_tip_city",
          { n: I.money(x.deal.median - x.price), rooms: I.num(x.deal.rooms), place: x.deal.place || "", count: x.deal.n });
        box.append(b);
      }
      return box.childNodes.length ? box : null;
    }

    /**
     * The photos: the first one shown; the others load one at a time as
     * you go through them (and the next one just before), so a card costs
     * one photo until you look at more.
     */
    function gallery(cls) {
      const photos = safePhotos(x.photos);
      const box = el("div", `rm-photo ${cls || ""}`);
      if (!photos.length) {
        // v1.33: the listing has none (a warning), or we didn't get them (open the listing)
        const none = x.photos_state === "none";
        box.classList.add("none");
        if (none) box.classList.add("warn");
        box.append(el("span", "rm-ph-icon", none ? "📷" : "🏠"), el("b", "rm-ph-none", t(none ? "ph_none" : x.photos_state === "unread" ? "ph_unread" : "no_photos")));
        if (x.photos_state === "none" || x.photos_state === "unread") box.append(el("small", "rm-ph-why", t(none ? "ph_none_x" : "ph_unread_x")));
        return box;
      }
      let i = 0;
      const img = doc.createElement("img");
      img.alt = t("photo_n", { n: 1, of: photos.length });
      img.loading = "lazy";
      img.decoding = "async";
      img.referrerPolicy = "no-referrer";
      img.src = photos[0];
      img.addEventListener("error", () => box.classList.add("broken"));
      box.append(img);
      if (photos.length > 1) {
        const count = el("span", "rm-ph-count", `1/${photos.length}`);
        const preload = (k) => {
          const p = new (doc.defaultView || root).Image();
          p.referrerPolicy = "no-referrer";
          p.src = photos[k];
        };
        const go = (d) => (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          i = (i + d + photos.length) % photos.length;
          box.classList.remove("broken");
          img.src = photos[i];
          img.alt = t("photo_n", { n: i + 1, of: photos.length });
          count.textContent = `${i + 1}/${photos.length}`;
          preload((i + d + photos.length) % photos.length);
        };
        const rtl = I.dir() === "rtl";
        const prev = el("button", "rm-ph-nav prev", rtl ? "›" : "‹");
        const next = el("button", "rm-ph-nav next", rtl ? "‹" : "›");
        prev.type = next.type = "button";
        prev.setAttribute("aria-label", t("photo_prev"));
        next.setAttribute("aria-label", t("photo_next"));
        prev.addEventListener("click", go(-1));
        next.addEventListener("click", go(1));
        // the next photo starts loading when the pointer comes near, so the first tap is quick
        box.addEventListener("pointerenter", () => preload(1), { once: true });
        box.append(prev, next, count);
      }
      return box;
    }

    function facts(withSource) {
      const out = [];
      if (x.rooms != null) out.push(`🛏️ ${t("rooms_n", { n: I.num(x.rooms) })}`);
      if (x.floor != null) out.push(`🏢 ${x.floor === 0 ? t("ground") : t("floor_n", { n: x.floor })}`);
      else if (typeof x.floor_said === "number") out.push(`🏢 ${t("floor_maybe", { n: x.floor_said })}`); // v1.64: Komo's "14 of 14"
      // v1.63 (owner ruling): the copies of a merged apartment give different sizes: a range
      const sizes = [x.size_m2].concat((x.also || []).map((o) => o.size_m2)).filter((v) => typeof v === "number" && v > 0);
      const lo = sizes.length ? Math.min(...sizes) : null, hi = sizes.length ? Math.max(...sizes) : null;
      if (x.size_m2) out.push(`📐 ${lo != null && lo < hi ? t("m2", { n: `${I.num(lo)}–${I.num(hi)}` }) : t("m2", { n: x.size_m2 })}`);
      if (withSource && x.listed_by === "agency") out.push(`🤝 ${t("agency")}`);
      const costs = x.costs || {};
      if (withSource) {
        for (const [k, v, top] of [["vaad", costs.vaad_bayit, costs.vaad_bayit_max], ["arnona", costs.arnona, costs.arnona_max]]) {
          // v1.59 (owner ruling): the ad and Yad2's field disagree: a range
          if (typeof v === "number") out.push(`🧾 ${typeof top === "number" ? t(`cost_${k}`, { n: `${I.money(v)}–${I.money(top)}` }) : v === 0 ? t(`cost_${k}_in`) : t(`cost_${k}`, { n: I.money(v) })}`);
        }
        // v1.57: Yad2's "סה״כ תשלום חודשי": the rent and both fees together, when both fees are known
        if (typeof x.total_monthly === "number" && x.total_monthly !== x.price) out.push(`💰 ${t("cost_total", { n: I.money(x.total_monthly) })}`);
      }
      return out;
    }

    function tripText(v0) {
      // v1.38: a trip saved by an older helper (or with its minutes left out) is read from its evidence
      const v = v0.minutes == null && v0.about == null && v0.usual == null ? Object.assign({}, v0, timesFrom(((x.commutes || {})[v0.signal] || {}).evidence)) : v0;
      // v1.37: a drive: the usual time and rush hour's
      if (v.mode === "car" && v.usual != null && v.worst != null) {
        return t(v.estimate ? "trip_car_est" : "trip_car", { u: I.num(v.usual, 0), w: I.num(v.worst, 0) });
      }
      return v.minutes != null ? (v.traffic ? t("trip_traffic", { n: I.num(v.minutes, 0) }) : t("min", { n: I.num(v.minutes, 0) }))
        : v.about != null ? t("trip_about", { n: I.num(v.about, 0) }) : "–";
    }

    function noteLines() {
      const lines = [];
      const done = new Set();
      const skipTrip = (n) => prefs[n.name] && prefs[n.name].topic === "commute" && /unclear|unstated/.test(n.reason);
      for (const n of (x.notes || []).filter((n) => n.kind === "exclude")) {
        const s = I.note(n, prefs[n.name]);
        if (s) lines.push(["hide", s, n.name]);
        done.add(n.name);
      }
      for (const r of (x.risks || []).filter((r) => r.pct >= 3 && !done.has(r.name))) {
        lines.push(["risk", t("n_risk", { topic: I.topicText(prefs[r.name]), pct: r.pct }), r.name]);
        done.add(r.name);
      }
      for (const n of (x.notes || []).filter((n) => n.kind !== "exclude" && !done.has(n.name) && !skipTrip(n))) {
        const s = I.note(n, prefs[n.name]);
        if (!s) continue;
        lines.push([n.reason === "unstated" || n.reason === "unclear" ? (prefs[n.name] && prefs[n.name].must ? "risk" : "ask") : "flag", s, n.name]);
        done.add(n.name);
      }
      const ask = (x.asks || []).filter((a) => a.worth >= 3).flatMap((a) => a.about || a.names)
        .filter((nm, i, all) => all.indexOf(nm) === i && !done.has(nm) && prefs[nm] && prefs[nm].topic !== "commute");
      if (ask.length) lines.push(["ask", t("ask_about", { list: ask.map((nm) => I.topicText(prefs[nm])).join(", ") }), null, ask]);
      return lines;
    }

    const btn = (cls, label, on, f) => {
      const b = el("button", `rm-btn ${cls}${on ? " on" : ""}`, label);
      b.type = "button";
      b.addEventListener("click", f);
      return b;
    };
    function viewingButton(label) {
      const view = btn("rm-b-view", mark.status === "viewing" && mark.viewingAt ? t("viewing_at", { when: I.date(mark.viewingAt, true) }) : label || t("viewing"),
        mark.status === "viewing", () => {
          if (mark.status === "viewing") return ctx.onMark(x, { status: null, viewingAt: null });
          const when = el("input", "rm-when");
          when.type = "datetime-local";
          when.title = t("viewing_when");
          const ok = btn("rm-b-plain", t("save"), false, () => ctx.onMark(x, { status: "viewing", viewingAt: when.value || null }));
          view.replaceWith(when, ok);
          when.focus();
        });
      return view;
    }

    // v1.63: the same address on another site, but the floor or size disagrees: maybe this flat, maybe a neighbor
    function maybeLines() {
      return (x.maybe || []).map((o) => {
        const differs = [];
        if (o.floor != null && x.floor != null && o.floor !== x.floor) differs.push(t("maybe_floor", { there: o.floor, here: x.floor }));
        if (o.size_m2 && x.size_m2 && o.size_m2 !== x.size_m2) differs.push(t("maybe_size", { there: I.num(o.size_m2), here: I.num(x.size_m2) }));
        return [o.url, t("maybe_same", { site: siteName(o.url), what: differs.join(", ") })];
      }).filter(([u]) => siteOf(u));
    }

    function otherLinks(into) {
      for (const [u, text] of maybeLines()) {
        const a = el("a", "rm-link rm-maybe", `${text} ↗`);
        a.href = u;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        into.append(a);
      }
      for (const o of offers) {
        if (o === best) continue;
        // v1.38: a second post of this apartment on the same site (merged into this card)
        const label = best && siteOf(o.url) === siteOf(best.url) ? "also_post" : "also_on";
        const a = el("a", "rm-link", `${t(label, { site: siteName(o.url) })}${typeof o.price === "number" && o.price > 0 ? ` · ${I.money(o.price)}` : ""} ↗`);
        a.href = o.url;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        into.append(a);
      }
    }

    // simple <-> detailed, for this card only
    function toggle(detail) {
      const b = el("button", "rm-detail", detail ? `▴ ${t("details_hide")}` : `▾ ${t("details_show")}`);
      b.type = "button";
      b.addEventListener("click", () => {
        const card = b.closest(".rm-card");
        const next = render(doc, x, Object.assign({}, ctx, { detail: !detail }));
        card.replaceWith(next);
        const again = next.querySelector(".rm-detail");
        if (again) again.focus({ preventScroll: true });
        if (ctx.onDetail) ctx.onDetail(x, !detail);
      });
      return b;
    }

    function card(cls) {
      const c = el("article", `rm-card ${cls}`);
      c.dataset.id = x.id;
      c.dataset.source = x.source || "yad2";
      if (mark.fav) c.classList.add("rm-fav");
      if (mark.status === "rejected") c.classList.add("rm-rejected");
      return c;
    }

    return { I, t, el, iso, mark, prefs, offers, best, shownPrice, place, saving, badges, gallery, facts, tripText, noteLines, btn,
      viewingButton, otherLinks, toggle, card };
  }

  /**
   * The simple card (v1.31, the default): a photo you can flip through, the
   * price, a verdict in words, the place as a button, the basics with icons,
   * the trip, the best few features, what to ask, and three buttons.
   */
  function renderSimple(doc, x, ctx) {
    const P = parts(doc, x, ctx);
    const { t, el, I, mark } = P;
    const c = P.card("rm-simple");
    const top = P.gallery();
    const tags = P.badges();
    if (tags) top.append(tags);
    if (ctx.onMark) {
      const heart = el("button", `rm-heart${mark.fav ? " on" : ""}`, mark.fav ? "♥" : "♡");
      heart.type = "button";
      heart.title = mark.fav ? t("saved") : t("save_listing");
      heart.setAttribute("aria-pressed", mark.fav ? "true" : "false");
      heart.addEventListener("click", (ev) => {
        ev.stopPropagation();
        ctx.onMark(x, { fav: !mark.fav });
      });
      top.append(heart);
    }
    c.append(top);
    const body = el("div", "rm-body");
    const head = el("div", "rm-shead");
    const price = el("div", "rm-bigprice", P.shownPrice != null ? I.money(P.shownPrice) : "–");
    price.append(el("small", null, ` ${t("a_month")}`));
    const fit = fitOf(x);
    const verdict = el("span", `rm-verdict ${fit}`, t(`fit_${fit}`));
    verdict.title = x.match_expected != null ? `${t("fit_tip")} (${Math.round(x.match_expected)}%)` : t("fit_tip");
    head.append(price, verdict);
    body.append(head);
    const saving = P.saving();
    if (saving) body.append(saving);
    body.append(P.place());
    const facts = P.facts(false);
    if (facts.length) body.append(el("div", "rm-sfacts", facts.join("  ·  ")));
    // v1.36: every trip (the e-bike and the car), not only the first
    for (const v of (x.trips || []).slice(0, 3)) {
      const line = el("div", `rm-strip${v.minutes == null ? " est" : ""}`);
      line.append(el("span", "rm-ic", MODE_ICON[v.mode] || "📍"), el("b", null, P.tripText(v)), " ");
      line.append(P.iso(t("to_place", { place: v.place })));
      body.append(line);
    }
    // v1.54 (owner ruling): everything the listing has, not only what matches the settings: the matches
    // first, then the rest (Yad2's ticked boxes among them) in a quieter row. A fact that hides the
    // listing is said by the hide line below.
    const feats = (x.feature_keys || []).filter((f) => iconOf(f.key));
    for (const [cls, list] of [["rm-sicons", feats.filter((f) => f.tone === "good")],
      ["rm-sicons other", feats.filter((f) => f.tone === "info" || f.tone === "weak")]]) {
      if (!list.length) continue;
      const row = el("div", cls);
      for (const f of list) row.append(el("span", null, `${iconOf(f.key)} ${I.feature(f)}`));
      body.append(row);
    }
    const lines = P.noteLines();
    const hide = lines.find((l) => l[0] === "hide");
    const asks = lines.filter((l) => l[0] === "risk" || l[0] === "ask" || l[0] === "flag");
    if (hide) body.append(el("div", "rm-sask hide", `✕ ${hide[1]}`));
    else if (asks.length) {
      const first = asks[0];
      body.append(el("div", `rm-sask ${first[0]}`, `${first[0] === "ask" ? "💬" : "⚠"} ${first[1]}${asks.length > 1 ? ` (+${asks.length - 1})` : ""}`));
    }
    const foot = el("div", "rm-sfoot");
    if (ctx.onMark) {
      foot.append(P.btn("rm-b-rej", mark.status === "rejected" ? t("rejected_undo") : `✕ ${t("not_for_me")}`, mark.status === "rejected",
        () => ctx.onMark(x, { status: mark.status === "rejected" ? null : "rejected" })));
      // the rest of what you can do, tucked away
      const more = el("details", "rm-more");
      const sum = el("summary", "rm-btn", mark.status === "interested" ? `✓ ${t("interested")}` : mark.status === "viewing" ? `📅 ${t("viewing")}` : `⋯ ${t("more_actions")}`);
      const menu = el("div", "rm-menu");
      menu.append(P.btn("rm-b-int", t("interested"), mark.status === "interested",
        () => ctx.onMark(x, { status: mark.status === "interested" ? null : "interested" })), P.viewingButton());
      P.otherLinks(menu);
      more.append(sum, menu);
      foot.append(more);
    }
    foot.append(el("span", "rm-sp"), P.toggle(false));
    body.append(foot);
    c.append(body);
    return c;
  }

  /**
   * The detailed card (v1.31: one click away): everything, organized, the
   * way it was before, plus the numbers behind the match.
   */
  function renderDetailed(doc, x, ctx) {
    const P = parts(doc, x, ctx);
    const { t, el, iso, I, mark } = P;
    const c = P.card("rm-detailed");
    const tags = P.badges();
    if (tags) c.append(tags);
    c.append(P.gallery("strip"));

    // ---- head: the match, the price
    const head = el("div", "rm-head");
    const fit = fitOf(x);
    const score = el("div", `rm-score ${fit}`);
    score.append(el("span", "rm-pct", x.match_expected != null ? `${Math.round(x.match_expected)}%` : "–"), el("span", "rm-fit", t(`fit_${fit}`)));
    score.title = t("fit_tip");
    const price = el("div", "rm-price", P.shownPrice != null ? I.money(P.shownPrice) : "–");
    price.append(el("small", null, t("a_month")));
    const saving = P.saving();
    if (saving) price.append(saving);
    head.append(score, price);
    c.append(head, P.place());

    const meta = el("div", "rm-meta");
    const src = x.source || "yad2";
    meta.append(el("span", `rm-src ${src}`, t(`site_${src}`)));
    for (const f of P.facts(true)) meta.append(el("span", "rm-chip", f));
    if (x.approx) {
      const a = el("span", "rm-chip approx", t("approx_place"));
      a.title = t("approx_tip", { site: t(`site_${src}`) });
      meta.append(a);
    }
    c.append(meta);

    // ---- getting there
    const trips = x.trips || [];
    if (trips.length) {
      const sec = el("div", "rm-sec");
      for (const v of trips) {
        const line = el("div", `rm-trip${v.minutes == null ? " est" : ""}`);
        const what = el("span");
        what.append(el("span", "rm-ic", MODE_ICON[v.mode] || "📍"), iso(I.topicTitle({ topic: "commute", place: v.place, mode: v.mode })));
        line.append(what, el("b", null, P.tripText(v)));
        sec.append(line);
      }
      c.append(sec);
    }

    // ---- what it has
    const feats = x.feature_keys || (x.features || []).map((f) => ({ label: f.label, tone: f.tone }));
    if (feats.length) {
      const sec = el("div", "rm-sec");
      sec.append(el("div", "rm-sec-t", t("what_it_has")));
      const bub = el("div", "rm-bubbles");
      for (const f of feats) {
        const b = el("span", `rm-bub ${f.tone || "info"}`, `${f.key && iconOf(f.key) ? `${iconOf(f.key)} ` : ""}${f.key ? I.feature(f) : f.label}`);
        b.title = t(`tone_${f.tone || "info"}`);
        bub.append(b);
      }
      sec.append(bub);
      c.append(sec);
    }

    // ---- what to know before going
    const lines = P.noteLines();
    if (lines.length) {
      const sec = el("div", "rm-sec");
      sec.append(el("div", "rm-sec-t", x.excluded ? t("why_hidden") : t("worth_asking")));
      const ul = el("ul", "rm-notes");
      for (const [cls, text] of lines) ul.append(el("li", cls, text));
      sec.append(ul);
      c.append(sec);
    }

    // ---- the numbers (v1.31)
    const pct = (v) => (typeof v === "number" ? `${Math.round(v)}%` : "–");
    const rows = [
      ["k_match", pct(x.match_expected)],
      ["k_likely", x.match_likely_low != null && x.match_likely_high != null ? `${pct(x.match_likely_low)} – ${pct(x.match_likely_high)}` : "–"],
      ["k_range", x.match_low != null && x.match_high != null ? `${pct(x.match_low)} – ${pct(x.match_high)}` : "–"],
      ["k_risk", typeof x.fail_risk === "number" ? pct(100 * x.fail_risk) : "–"],
      ["k_per_m2", typeof x.price === "number" && x.size_m2 ? I.money(x.price / x.size_m2) : "–"],
      ["k_listed", x.listed_by ? t(x.listed_by === "agency" ? "k_agency" : "k_private") : "–"],
      ["k_photos", x.photos_state === "none" ? t("ph_none") : x.photos_state === "unread" && !safePhotos(x.photos).length ? t("ph_unread") : String(safePhotos(x.photos).length)],
      ["k_source", `${t(`site_${src}`)} · ${x.id}`],
    ];
    if (x.deal && typeof x.deal.median === "number") rows.push(["k_usual", `${I.money(x.deal.median)} (${x.deal.n})`]);
    if (ctx.readAt) rows.push(["k_read", I.when(ctx.readAt)]);
    const sec = el("div", "rm-sec");
    sec.append(el("div", "rm-sec-t", t("k_numbers")));
    const dl = el("dl", "rm-kv");
    for (const [k, v] of rows) dl.append(el("dt", null, t(k)), el("dd", null, v));
    sec.append(dl);
    const raw = [...(x.reasons || []), ...(x.flags || []), ...(x.checks || [])];
    if (raw.length) {
      const d = el("details", "rm-raw");
      d.append(el("summary", null, t("k_engine", { n: raw.length })));
      const ul = el("ul");
      for (const r of raw) ul.append(el("li", null, r));
      d.append(ul);
      sec.append(d);
    }
    c.append(sec);

    // ---- your call
    const foot = el("div", "rm-foot");
    if (ctx.onMark) {
      foot.append(P.btn("rm-b-fav", `${mark.fav ? "♥" : "♡"} ${mark.fav ? t("saved") : t("save_listing")}`, mark.fav, () => ctx.onMark(x, { fav: !mark.fav })));
      foot.append(P.btn("rm-b-int", t("interested"), mark.status === "interested",
        () => ctx.onMark(x, { status: mark.status === "interested" ? null : "interested" })));
      foot.append(P.viewingButton());
      foot.append(P.btn("rm-b-rej", mark.status === "rejected" ? t("rejected_undo") : `✕ ${t("not_for_me")}`, mark.status === "rejected",
        () => ctx.onMark(x, { status: mark.status === "rejected" ? null : "rejected" })));
    }
    foot.append(el("span", "rm-sp"));
    P.otherLinks(foot);
    foot.append(P.toggle(true));
    c.append(foot);
    return c;
  }

  /** One listing's card: simple unless ctx.detail. */
  function render(doc, x, ctx) {
    ctx = ctx || {};
    return ctx.detail ? renderDetailed(doc, x, ctx) : renderSimple(doc, x, ctx);
  }

  /**
   * v1.32: "Want more options?" as one line: "3 ways to see up to 12 more
   * listings". Hovering it (or a click, or the keyboard) opens the list,
   * each with its Apply. apply(x) resolves to {ok, text}.
   */
  function moreLine(doc, I, list, apply) {
    const t = I.t;
    const el = (tag, cls, text) => {
      const e = doc.createElement(tag);
      if (cls) e.className = cls;
      if (text != null) e.textContent = String(text);
      return e;
    };
    const sg = (list || []).filter((x) => x && x.count >= 2);
    if (!sg.length) return null;
    const line = el("div", "rm-moreline");
    line.tabIndex = 0;
    line.setAttribute("role", "button");
    line.setAttribute("aria-haspopup", "true");
    const most = Math.max(...sg.map((x) => x.count));
    line.append(el("b", null, `💡 ${t("sg_title")}`), el("span", null, t(sg.length === 1 ? "sg_line1" : "sg_line", { k: sg.length, n: most })), el("i", null, "▾"));
    const pop = el("div", "rm-morepop");
    const ul = el("ul");
    for (const x of sg) {
      const li = el("li");
      li.append(el("span", null, I.suggestion(x)), el("em", null, t("sg_count", { n: x.count })));
      if (apply) {
        const b = el("button", null, t("apply"));
        b.type = "button";
        b.addEventListener("click", async (ev) => {
          ev.stopPropagation();
          b.disabled = true;
          const r = await apply(x);
          li.replaceChildren(el("span", null, r && r.ok ? t("sg_saved") : t("e_generic", { detail: (r && r.text) || "" })));
        });
        li.append(b);
      }
      ul.append(li);
    }
    pop.append(ul);
    line.append(pop);
    line.addEventListener("click", () => line.classList.toggle("open"));
    line.addEventListener("keydown", (ev) => { if (ev.key === "Escape") { line.classList.remove("open"); line.blur(); } });
    return line;
  }

  const api = { timesFrom, photoless, hidesPhotoless, CSS, render, SAFE_LINK, siteOf, bestOffer, ICONS, safePhotos, moreLine };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.RentalCards = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
