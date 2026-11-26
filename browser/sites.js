/*
 * Rental Matcher: reading Madlan and Komo pages (v1.27). Pure functions
 * over a page's HTML, so they run the same in the extension and in Node's
 * tests, with no DOM.
 *
 * What we may read, and how (checked Oct 22, 2026):
 * - Komo serves its first results page for a city, and every listing page,
 *   to anyone. Further results pages need a Komo account, so those are read
 *   only when the user opens them himself (see content_sites.js).
 * - Madlan answers any request that isn't a page the user opened with a
 *   bot block (PerimeterX, 403), so Madlan is never fetched: its search
 *   and listing pages are read only as the user opens them.
 *
 * Only the facts of a listing are taken: never the poster's name or phone.
 */
(function (root) {
  "use strict";

  // ---- shared ----------------------------------------------------------------------

  // v1.62: Komo's text keeps typographic codes ("&rsquo;", Komo batch 1): decode them, and hex codes too
  const ENT = { "&nbsp;": " ", "&quot;": "\"", "&#39;": "'", "&amp;": "&", "&lt;": "<", "&gt;": ">", "&#8362;": "₪",
    "&rsquo;": "’", "&lsquo;": "‘", "&rdquo;": "”", "&ldquo;": "“", "&ndash;": "–", "&mdash;": "—", "&hellip;": "…", "&apos;": "'", "&shekel;": "₪" };
  function decode(s) {
    return String(s || "")
      .replace(/&#x([0-9a-f]+);/gi, (m, n) => String.fromCharCode(parseInt(n, 16)))
      .replace(/&#(\d+);/g, (m, n) => String.fromCharCode(Number(n)))
      .replace(/&[a-z#0-9]+;/gi, (m) => (ENT[m] != null ? ENT[m] : m));
  }
  const text = (html) => decode(String(html || "").replace(/<br\s*\/?>/gi, "\n").replace(/<[^>]+>/g, "")).replace(/[ \t ]+/g, " ")
    .replace(/\s*\n\s*/g, "\n").trim();
  const num = (s) => {
    const m = String(s == null ? "" : s).replace(/,/g, "").match(/-?\d+(?:\.\d+)?/);
    return m ? Number(m[0]) : null;
  };
  // a phone number in free text, however it's written (the same rule as yad2_pull.scrub)
  const PHONE = /(?:\+?972[\s-]?|0)(?:[2-9]|5\d|7\d)[\s-]?\d{3}[\s-]?\d{4}\b/g;
  const SPLIT = /(?<!\d)(?:\+?972[\s-]?|0)(?:5\d|7\d)[\s-]+(?:[^\d\s]{1,8}[\s-]+){1,2}\d{3}[\s-]?\d{4}(?!\d)/g;  // "050 מספר 5792223" (v1.53)
  const scrub = (s) => (s == null ? s : String(s).replace(SPLIT, "[phone]").replace(PHONE, "[phone]"));

  // ---- Komo --------------------------------------------------------------------------

  const KOMO = "https://www.komo.co.il";
  const KOMO_ITEM = (n) => `${KOMO}/code/nadlan/details/?modaaNum=${encodeURIComponent(n)}`;
  const NOT_GIVEN = /לא צוין/;

  /** Komo's first results page for a city (the rest need an account). */
  function komoSearchUrl(cityHe, maxPrice) {
    const q = new URLSearchParams({ nehes: "1", cityName: cityHe });
    if (maxPrice) q.set("toPrice", String(Math.floor(maxPrice)));
    return `${KOMO}/code/nadlan/apartments-for-rent.asp?${q.toString()}`;
  }

  /** "דירות 4.0 חדרים (75 מ"ר)\nקומה: 1 מתוך 3" -> facts. */
  function komoFacts(desc) {
    const out = {};
    const rooms = desc.match(/([\d.]+)\s*חדרים/);
    if (rooms) out.rooms = Number(rooms[1]);
    const size = desc.match(/\((\d+)\s*מ"ר\)/);
    if (size) out.size_m2 = Number(size[1]);
    const floor = desc.match(/קומה:\s*(קרקע|\d+)(?:\s*מתוך\s*(\d+))?/);
    if (floor) {
      out.floor = floor[1] === "קרקע" ? 0 : Number(floor[1]);
      if (floor[2]) out.floors = Number(floor[2]);
    }
    const kind = desc.split(/\s|\n/)[0];
    if (kind) out.property = kind.replace(/^דירות$/, "דירה");
    return out;
  }

  const KOMO_PIC = (n) => `${KOMO}/api/modaot/tmunot/showPic/list/?picNum=${n}&luachNum=2`;

  /** The listings on a Komo results page: rows in the shape the helper plans with. */
  function komoRows(html) {
    const rows = [];
    const seen = new Set();
    // each listing's box starts with its id and then its photo, before its text (never the next box's photo)
    const pics = {};
    for (const m of String(html).matchAll(/(?:modaaPPC|modaaRowDv)(\d+)(?:(?!modaaPPC|modaaRowDv)[\s\S]){0,800}?showPic\/list\/\?(?:picSize=\w+&(?:amp;)?)?picNum=(\d+)/g)) {
      if (!pics[m[1]]) pics[m[1]] = m[2];
    }
    for (const chunk of String(html).split(/class=["']contant["']/).slice(1)) {
      const id = (chunk.match(/details\/\?modaaNum=(\d+)/) || [])[1];
      if (!id || seen.has(id)) continue;
      seen.add(id);
      const title = text((chunk.match(/<h2 class=["']title["']\s*>([\s\S]*?)<\/h2>/) || [])[1]);
      const parts = title.split(",").map((s) => s.trim());
      // "city, neighborhood, street", but a missing part is dropped: "תל אביב יפו, אפטר יעקב 6" is a street
      if (parts.length === 2 && /\d/.test(parts[1])) parts.splice(1, 0, null);
      const [city, hood, street] = parts;
      const shown = num(text((chunk.match(/<div class=["']price["']\s*>([\s\S]*?)<\/div>/) || [])[1]));
      const price = shown > 0 ? shown : null; // Komo shows 0 when the rent isn't given
      const desc = text((chunk.match(/<div class=["']description["']\s*>([\s\S]*?)<div class=["']mFooterAction/) || [])[1]);
      const f = komoFacts(desc);
      // v1.64: "קומה: 14 מתוך 14" is often the building's height, not the flat's floor (Komo batch 2): not used to plan or match
      const tall = f.floor != null && f.floors != null && f.floors >= 3 && f.floor === f.floors;
      if (tall) { f.floor_said = f.floor; f.floor = null; }
      rows.push({
        id: `komo:${id}`, source: "komo", url: KOMO_ITEM(id), price, rooms: f.rooms == null ? null : f.rooms,
        size_m2: f.size_m2 == null ? null : f.size_m2, floor: f.floor == null ? null : f.floor, property: f.property || null,
        city: city || null, hood_name: hood && !NOT_GIVEN.test(hood) ? hood : null, street: street && !NOT_GIVEN.test(street) ? street : null,
        lat: null, lng: null, adType: null, fp: `${price}|${f.rooms}|${f.size_m2}|${f.floor}`, floor_said: f.floor_said == null ? null : f.floor_said,
        photos: pics[id] ? [KOMO_PIC(pics[id])] : [],
      });
    }
    const total = num((String(html).match(/(\d[\d,]*)\s*מודעות/) || [])[1]);
    return { rows, total };
  }

  // Komo's feature list on a listing page: <li class="mamad add"> is ticked, <li class="mamad "> isn't
  const KOMO_FEATURES = {
    mamad: "mamad", maalit: "elevator", soragim: "window_bars", mizug: "air_conditioning", riut: "furniture_box",
    gisha: "accessible", shutafim: "suits_roommates", pets: "pets_allowed", renovated: "renovated", unit: "unit",
    mahsan: "storage", boiler: "solar_heater", longRent: "long_term", kitchenKosher: "kosher_kitchen",
  };

  /** A Komo listing page -> the extract the helper reads (rental_matcher/adapters/komo.py). */
  function komoItem(html, id, row) {
    const h = String(html);
    if (!/class=["'](?:secondInfoWrap|firstInfoWrap)/.test(h)) return null;
    const ticked = {};
    for (const m of h.matchAll(/<li class=["'](\w+)( add)?\s*["']/g)) if (KOMO_FEATURES[m[1]]) ticked[KOMO_FEATURES[m[1]]] = !!m[2];
    const info = {};
    for (const m of h.matchAll(/secondInfoElementTitle[^>]*>([\s\S]*?)<\/div>\s*<div class=["']secondInfoElementContent[^>]*>([\s\S]*?)<\/div>/g)) {
      info[text(m[1])] = text(m[2]);
    }
    const first = {};
    for (const m of h.matchAll(/<div class=["']firstInfo["']\s*>([\s\S]*?)<\/div>\s*<div class=["']firstInfoTitle["']\s*>([\s\S]*?)<\/div>/g)) first[text(m[2])] = text(m[1]);
    const where = text((h.match(/modaaWTitleNew[\s\S]*?<h2>([\s\S]*?)<\/h2>/) || h.match(/<h2>\s*<span>([\s\S]*?)<\/span>/) || [])[1]);
    const [hood, city] = where.split(",").map((s) => s.trim());
    const shown = num(text((h.match(/ModaaWDetailsValue[^>]*>([\s\S]*?)<\/span>/) || [])[1]));
    const price = shown > 0 ? shown : null;
    const teur = text((h.match(/<div id=["']teurWrap["']\s*>([\s\S]*?)<\/div>/) || [])[1]);
    const furn = text((h.match(/<div class=["']furnitureDesc["']\s*>([\s\S]*?)<\/div>/) || [])[1]).replace(/^הסבר על הריהוט\s*:?\s*/, "");
    const entry = first["תאריך כניסה"] || null;
    const r = row || {};
    // its gallery: the photos before "similar listings" (those are other apartments')
    const cut = h.indexOf("מודעות דומות");
    const own = cut > 0 ? h.slice(0, cut) : h;
    const photos = Array.from(new Set([...own.matchAll(/showPic\/list\/\?(?:picSize=\w+&(?:amp;)?)?picNum=(\d+)/g)].map((m) => m[1]))).map(KOMO_PIC);
    return {
      id: `komo:${id}`, source: "komo", url: KOMO_ITEM(id),
      price: price != null ? price : r.price, rooms: num(first["חד'"]) != null ? num(first["חד'"]) : r.rooms,
      floor: first["קומה"] != null ? (/קרקע/.test(first["קומה"]) ? 0 : num(first["קומה"])) : r.floor,
      size_m2: num(first["מ''ר"]) != null ? num(first["מ''ר"]) : r.size_m2, floors: num(info["קומות בבניין"]),
      city: city || r.city || null, neighborhood: hood && !NOT_GIVEN.test(hood) ? hood : r.hood_name || null, street: r.street || null,
      property: r.property || null, condition: info["מצב הנכס"] || null, parking: num(info["חניות"]), balconies: num(info["מרפסות"]),
      arnona: num(info["ארנונה"]),
      entry: entry && !NOT_GIVEN.test(entry) ? entry : null, ticked, description: scrub([teur, furn].filter(Boolean).join("\n").trim()) || null,
      // Komo has no pin: the row may carry its neighborhood's middle (placeApprox), never the apartment's own spot
      approx: true, lat: r.lat == null ? null : r.lat, lng: r.lng == null ? null : r.lng,
      photos: photos.length ? photos.slice(0, 20) : (r.photos || []),
    };
  }

  /** A neighborhood's name, compared loosely: "שכונת התקווה" = "התקווה", "נווה-שאנן" = "נווה שאנן". */
  function hoodKey(name) {
    return String(name || "").replace(/^(?:שכונת|שכ'|שכ\.)\s*/, "").replace(/["'״׳]/g, "").replace(/[-–\s]+/g, " ").trim();
  }
  function sameHood(a, b) {
    const x = hoodKey(a);
    const y = hoodKey(b);
    return !!x && !!y && (x === y || x.startsWith(y + " ") || y.startsWith(x + " "));
  }

  /** The middle of each neighborhood, from the pins of the Yad2 listings in it: {"city|hood": [lat, lng]}. */
  function hoodCentroids(rows) {
    const sum = {};
    for (const r of rows || []) {
      if (r.lat == null || r.lng == null || !r.city || !r.hood_name) continue;
      const k = `${r.city}|${hoodKey(r.hood_name)}`;
      const t = sum[k] || (sum[k] = [0, 0, 0]);
      t[0] += r.lat;
      t[1] += r.lng;
      t[2]++;
    }
    const out = {};
    for (const [k, [a, b, n]] of Object.entries(sum)) if (n >= 2) out[k] = [Math.round((a / n) * 1e5) / 1e5, Math.round((b / n) * 1e5) / 1e5];
    return out;
  }

  /** A row with no pin, placed at its neighborhood's middle (and marked as approximate), if that's known. */
  function placeApprox(row, centroids) {
    if (row.lat != null && row.lng != null) return row;
    const hit = row.hood_name && Object.entries(centroids || {}).find(([k]) => {
      const [city, hood] = k.split("|");
      return city === row.city && sameHood(hood, row.hood_name);
    });
    return hit ? Object.assign({}, row, { lat: hit[1][0], lng: hit[1][1], approx: true }) : row;
  }

  const sleeper = (ms) => new Promise((r) => setTimeout(r, ms));
  const LOGIN = /account\.komo\.co\.il|\/login/i;
  const PUSHBACK = new Set([403, 429, 503]);

  /**
   * Komo's newest listings in one city: its first results page, the one
   * anyone can see. get(url) -> {status, text, url} or {error}: the
   * extension's background fetches it, with no cookies and no account.
   */
  async function komoSearch(cityHe, maxPrice, get) {
    const r = await get(komoSearchUrl(cityHe, maxPrice));
    if (!r || r.error) return { rows: [], error: (r && r.error) || "no answer" };
    if (LOGIN.test(r.url || "")) return { rows: [], wall: true };
    if (r.status !== 200) return { rows: [], status: r.status, pushback: PUSHBACK.has(r.status) };
    const out = komoRows(r.text);
    return { rows: out.rows, total: out.total };
  }

  /**
   * Komo listing pages, one at a time at a polite pace (gapMs between
   * requests). The first pushback (403/429/503 or a sign-in page) stops
   * Komo for this pull: what's left is listed as not opened.
   * o: {get, rows: {id: row}, gapMs, shouldStop, cache ({get, set}), maxAgeMs, onResult(id, res), now, sleep}
   */
  async function komoItems(ids, o) {
    const now = o.now || (() => Date.now());
    const sleep = o.sleep || sleeper;
    const gap = o.gapMs == null ? 1500 : o.gapMs;
    const stats = { requests: 0, stoppedBecause: null };
    let last = -Infinity;
    for (const id of ids) {
      const row = (o.rows || {})[id] || {};
      const fp = row.fp;
      const hit = o.cache && fp ? await o.cache.get(id) : null;
      if (hit && hit.fp === fp && hit.extract && now() - hit.fetchedAt <= (o.maxAgeMs || 3 * 864e5)) {
        o.onResult(id, { status: "ok", extract: hit.extract, fetchedAt: hit.fetchedAt, fromCache: true });
        continue;
      }
      if (stats.stoppedBecause || (o.shouldStop && o.shouldStop())) {
        stats.stoppedBecause = stats.stoppedBecause || "stopped by you";
        o.onResult(id, { status: "stopped", error: stats.stoppedBecause, fromCache: false });
        continue;
      }
      const wait = last + gap - now();
      if (wait > 0) await sleep(wait);
      last = now();
      stats.requests++;
      const n = String(id).replace(/^komo:/, "");
      const r = await o.get(KOMO_ITEM(n));
      if (!r || r.error) {
        o.onResult(id, { status: "failed", error: (r && r.error) || "no answer", fromCache: false });
        continue;
      }
      if (LOGIN.test(r.url || "") || PUSHBACK.has(r.status)) {
        stats.stoppedBecause = "komo_pushback";
        o.onResult(id, { status: "stopped", error: stats.stoppedBecause, fromCache: false });
        continue;
      }
      if (r.status === 404 || r.status === 410) {
        o.onResult(id, { status: "removed", error: "no item data", fromCache: false });
        continue;
      }
      const extract = r.status === 200 ? komoItem(r.text, n, row) : null;
      if (!extract) {
        o.onResult(id, { status: r.status === 200 ? "removed" : "failed", error: r.status === 200 ? "no item data" : `HTTP ${r.status}`, fromCache: false });
        continue;
      }
      const fetchedAt = now();
      if (o.cache && fp) await o.cache.set(id, { fp, fetchedAt, extract });
      o.onResult(id, { status: "ok", extract, fetchedAt, fromCache: false });
    }
    return stats;
  }

  /** Is this a Komo or Madlan page we can read, and what's on it? For pages the user opens himself. */
  function readPage(url, html) {
    let u;
    try {
      u = new URL(url);
    } catch (e) {
      return null;
    }
    if (/(^|\.)komo\.co\.il$/.test(u.hostname)) {
      const m = u.search.match(/modaaNum=(\d+)/);
      if (/\/details\//.test(u.pathname) && m) {
        const x = komoItem(html, m[1], null);
        return x ? { site: "komo", item: x } : null;
      }
      if (/apartments-for-rent/.test(u.pathname)) {
        const r = komoRows(html);
        return r.rows.length ? { site: "komo", rows: r.rows } : null;
      }
      return null;
    }
    if (/(^|\.)madlan\.co\.il$/.test(u.hostname)) {
      if (/^\/listings\//.test(u.pathname)) {
        const x = madlanItem(html);
        return x ? { site: "madlan", item: x } : null;
      }
      if (/^\/for-rent\//.test(u.pathname)) {
        const r = madlanRows(html);
        return r && r.rows.length ? { site: "madlan", rows: r.rows } : null;
      }
    }
    return null;
  }

  // ---- Madlan ------------------------------------------------------------------------

  const MADLAN = "https://www.madlan.co.il";
  const MADLAN_ITEM = (id) => `${MADLAN}/listings/${encodeURIComponent(id)}`;

  /** The data Madlan's server put in the page: window.__SSR_HYDRATED_CONTEXT__. */
  function madlanContext(html) {
    const h = String(html);
    const i = h.indexOf("window.__SSR_HYDRATED_CONTEXT__=");
    if (i < 0) return null;
    const start = i + "window.__SSR_HYDRATED_CONTEXT__=".length;
    const end = h.indexOf("</script>", start);
    // it's a JavaScript literal, not quite JSON: Madlan leaves bare `undefined` values in it (31 on one page)
    const json = h.slice(start, end < 0 ? undefined : end).trim().replace(/;\s*$/, "").replace(/([:,[])undefined(?=[,}\]])/g, "$1null");
    try {
      return JSON.parse(json);
    } catch (e) {
      return null;
    }
  }

  // Madlan's building classes (seen on one city's rentals, Oct 22: roofflat, flat, penthouseapp, villa, gardenapartment)
  const BUILDING = { roofflat: "דירת גג", penthouse: "פנטהאוז", penthouseapp: "פנטהאוז", gardenapartment: "דירת גן", garden_apartment: "דירת גן",
    cottage: "קוטג'", villa: "בית פרטי", privatehouse: "בית פרטי", private_house: "בית פרטי", duplex: "דופלקס", studio: "סטודיו",
    unit: "יחידת דיור", flat: "דירה" };

  const MADLAN_PIC = (path) => `https://images2.madlan.co.il/t:nonce:v=2;resize:width=640/${path}`;

  function madlanRow(p) {
    const a = p.addressDetails || {};
    const photos = (Array.isArray(p.images) ? p.images : [])
      .filter((im) => im && typeof im.imageUrl === "string" && /^bulletins\/[^\s"'<>\\]+$/.test(im.imageUrl) && !im.isFloorplan)
      .map((im) => MADLAN_PIC(im.imageUrl)).slice(0, 20);
    const lp = p.locationPoint || {};
    return {
      id: `madlan:${p.id}`, source: "madlan", url: MADLAN_ITEM(p.id), price: typeof p.price === "number" ? p.price : null,
      rooms: typeof p.beds === "number" ? p.beds : null, size_m2: typeof p.area === "number" ? p.area : null,
      floor: num(p.floor), property: BUILDING[String(p.buildingClass || "").toLowerCase()] || null,
      city: a.city || null, hood_name: a.neighbourhood || null, street: a.streetName ? [a.streetName, a.streetNumber].filter(Boolean).join(" ") : null,
      lat: typeof lp.lat === "number" ? lp.lat : null, lng: typeof lp.lng === "number" ? lp.lng : null,
      adType: p.poc && p.poc.type === "agent" ? "commercial" : p.poc && p.poc.type === "private" ? "private" : null,
      fp: `${p.price}|${p.lastUpdated || ""}|${(p.eventsHistory || []).length}`,
      photos,
    };
  }

  /** The listings on a Madlan search page, as rows. */
  function madlanRows(html) {
    const c = madlanContext(html);
    const d = c && c.reduxInitialState && c.reduxInitialState.domainData;
    const s = d && d.searchList && d.searchList.data && d.searchList.data.searchPoiV2;
    if (!s) return null;
    return { rows: (s.poi || []).filter((p) => p && p.type === "bulletin" && p.dealType === "unitRent").map(madlanRow), total: s.total };
  }

  /** A Madlan listing page -> the extract the helper reads (rental_matcher/adapters/madlan.py). */
  function madlanItem(html) {
    const c = madlanContext(html);
    const d = c && c.reduxInitialState && c.reduxInitialState.domainData;
    const p = d && d.bulletinsByIds && d.bulletinsByIds.data && (d.bulletinsByIds.data.poiByIds || [])[0];
    if (!p || p.type !== "bulletin") return null;
    const row = madlanRow(p);
    const am = p.amenities || {};
    const amenities = {};
    for (const [k, v] of Object.entries(am)) if (typeof v === "boolean") amenities[k] = v;
    // v1.68 (Madlan sample 1): Madlan ticks a balcony, storage room or garden on its page from its list of areas, while the
    // amenity flag stays empty (17 of 18 balconies, all 13 storage rooms): how many of each the page lists
    const ar = (am.additionalAreas && typeof am.additionalAreas === "object") ? am.additionalAreas : {};
    // an entry with no size still counts ("warehouseAreas: [null]": a storage room the poster gave no size for)
    const count = (list, one) => (Array.isArray(list) ? list.length : 0) || (typeof one === "number" && one > 0 ? 1 : 0);
    const areas = { balcony: count(ar.balconyAreas, ar.balconiesArea), storage: count(ar.warehouseAreas, ar.storeroomArea), garden: count(ar.gardenAreas, null) };
    return Object.assign(row, {
      neighborhood: row.hood_name, floors: typeof p.floors === "number" ? p.floors : null, condition: p.generalCondition || null,
      building_class: p.buildingClass || null, availability: p.availabilityType || null, available_date: p.availableDate || null,
      parking: typeof p.parking === "number" ? p.parking : null, amenities, areas,
      description: scrub(typeof p.description === "string" ? p.description : null),
      approx: false,
    });
  }

  // ---- Facebook (v1.66: view-only) ---------------------------------------------------
  //
  // A post the user selected and chose to keep (the extension's right-click menu): only the text he selected and the
  // page's address. Nothing on Facebook is fetched, scrolled or clicked, and no poster's name is taken.

  const FB_POST = /^https:\/\/(?:www|m|web)\.facebook\.com\/(?:groups\/([^/?#]+)\/(?:posts|permalink)\/(\d+)|marketplace\/item\/(\d+))\/?(?:[?#].*)?$/;

  /** The post's own address, when the page is one post (a group post or a Marketplace item). */
  function facebookUrl(url) {
    const m = FB_POST.exec(String(url || ""));
    if (!m) return null;
    return m[3] ? `https://www.facebook.com/marketplace/item/${m[3]}` : `https://www.facebook.com/groups/${m[1]}/posts/${m[2]}`;
  }

  function hashText(t) {
    let h = 2166136261;
    for (let i = 0; i < t.length; i++) h = Math.imul(h ^ t.charCodeAt(i), 16777619) >>> 0;
    return h.toString(36);
  }

  /** A rent in the text: "4,500 ש"ח", "₪4500", "מחיר: 4500", "4500 לחודש"; a sale-sized or tiny number isn't one. */
  function fbPrice(t) {
    // a whole number: not the tail of "2,450,000" (a sale price)
    const N = "(?<![\\d,.])(\\d{1,2},\\d{3}|\\d{3,5})(?![\\d,])";
    const pats = [new RegExp(`(?:₪|ש["״']?ח|שקל(?:ים)?|ש\\.ח)\\s*${N}`, "g"), new RegExp(`${N}\\s*(?:₪|ש["״']?ח|שקל(?:ים)?|ש\\.ח|לחודש|בחודש)`, "g"),
      new RegExp(`(?:מחיר|שכירות|שכ["״]ד|שכר\\s+דירה)\\s*[:\\-]?\\s*${N}`, "g")];
    const found = [];
    for (const re of pats) for (const m of t.matchAll(re)) {
      const n = Number(m[1].replace(/,/g, ""));
      if (n >= 800 && n <= 60000) found.push(n);
    }
    // the rent is the largest such amount (a building fee or an arnona amount is smaller)
    return found.length ? Math.max(...found) : null;
  }

  function facebookPost(o) {
    const raw = String((o && o.text) || "").replace(/\r/g, "").trim();
    if (raw.length < 30) return null;
    const t = scrub(raw);
    const url = facebookUrl(o && o.url);
    const m = url && /(\d+)$/.exec(url);
    const id = `facebook:${m ? m[1] : hashText(raw)}`;
    const rooms = (t.match(/(?<![\d.])(\d(?:\.5)?)\s*(?:חדרים|חד['׳]?(?![א-ת]))/) || [])[1];
    const size = (t.match(/(?<![\d.])(\d{2,3})\s*(?:מ["״]ר|מטר(?:ים)?|מ['׳](?![א-ת]))/) || [])[1];
    const floorM = t.match(/קומ(?:ה|ת)\s*(קרקע|\d{1,2})(?![\d])/);
    return {
      id, source: "facebook", url: url || null, price: fbPrice(t), rooms: rooms ? Number(rooms) : null, size_m2: size ? Number(size) : null,
      floor: floorM ? (floorM[1] === "קרקע" ? 0 : Number(floorM[1])) : null, city: (o && o.city) || null, hood_name: null, street: null,
      lat: null, lng: null, description: t, photos: [], approx: true, fp: hashText(t),
    };
  }

  const api = { decode, text, scrub, komoSearchUrl, komoRows, komoItem, komoFacts, KOMO_ITEM, hoodKey, sameHood, hoodCentroids, placeApprox,
    komoSearch, komoItems, readPage, madlanContext, madlanRows, madlanItem, MADLAN_ITEM, facebookPost, facebookUrl };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.RentalSites = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
