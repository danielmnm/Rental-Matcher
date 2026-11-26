"""
The whole thing, the way the owner uses it (v1.25): Chromium with the unpacked
extension (browser/), the helper registered for native messaging the way
`python -m rental_matcher.install` registers it (Chrome starts it itself),
and one click on Find listings in the side panel (v1.32). The extension
opens Yad2 by itself, in a background tab, and reads the searches in the preferences. Yad2 and the route
server are played by the Oct 20 live fixtures (60 Bat Yam listings, their
pages and their routes), so no real site is touched.

Checked:
- the panel shows TestLivePull's 10 listings in its order; a second pull
  opens nothing;
- another Yad2 tab (a listing opened from the panel) never starts a pull
  of its own: only one pull, at one pace;
- Reject hides a listing on the panel and the next pull doesn't open it;
  Favorite and Interested show on the results page;
- when Yad2 answers with its check, the tab is reloaded so the real check
  is on screen, a window says what to do, and once it's done the pull goes
  on by itself at half the pace (one check counted, both in the log);
- when Yad2 pushes back without a check, the pull pauses and goes on at
  half the pace;
- the setup page adds a city and saves the preferences file;
- (v1.27) a Madlan page the user opens is kept for the next pull; the pull
  adds Komo's first page for the same city and opens Komo listing pages,
  without cookies, and never fetches Madlan. Komo and Madlan are played by
  the Oct 22 saved pages (tests/fixtures/sites_2026-10-22).

Needs Playwright and its Chromium; skipped where they aren't installed.
"""

import json
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urlsplit

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "tests" / "fixtures" / "yad2_live_2026-10-20"
SITES = ROOT / "tests" / "fixtures" / "sites_2026-10-22"
SHOTS = os.environ.get("RM_E2E_SHOTS")  # a folder, to save what each screen looks like

# the extension's background fetches Komo (v1.27): let the harness route a service worker's requests too
os.environ.setdefault("PW_EXPERIMENTAL_SERVICE_WORKER_NETWORK_EVENTS", "1")

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

TEN = ["7w5nv0p7", "t8n0ghu0", "2a5m0b7a", "idoewwx4", "f9gz3aqq", "clp32ctv", "44gzb3qw", "1dqm0ykv", "igj5zw99", "9aq4ffmq"]  # v1.28: 9aq4ffmq (floor 4, elevator unstated) last


def _png(seed, w=96, h=72):
    """A small gradient PNG, its colors from `seed`: a stand-in listing photo."""
    import struct
    import zlib
    k = sum(map(ord, seed))
    a, b = ((k * 37) % 200 + 40, (k * 61) % 200 + 40, (k * 17) % 200 + 40), ((k * 13) % 200 + 40, (k * 7) % 200 + 40, (k * 29) % 200 + 40)
    raw = b"".join(b"\x00" + bytes(int(a[c] + (b[c] - a[c]) * (x + y) / (w + h)) for x in range(w) for c in range(3)) for y in range(h))
    chunk = lambda tag, data: struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)  # noqa: E731
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def _nd(queries):
    return ('<html><head><script id="__NEXT_DATA__" type="application/json">'
            + json.dumps({"props": {"pageProps": {"dehydratedState": {"queries": queries}}}}, ensure_ascii=False)
            + "</script></head><body><h1>Yad2 (test)</h1></body></html>")


class FakeYad2:
    def __init__(self):
        self.xs = json.loads((LIVE / "extracts.json").read_text(encoding="utf-8"))
        # a listing's own text must never run as code in the panel
        top = next(x for x in self.xs if x["id"] == "t8n0ghu0")
        top["street"] = '<img src=x onerror="window.__pwned=1">'
        self.km = json.loads((LIVE / "routes_citycenter38.json").read_text(encoding="utf-8"))["bike_minutes"]
        self.items, self.searches, self.osrm = [], [], 0
        self.search_times = []
        self.check = False  # True: every Yad2 page is the bot check
        self.soft = 0  # this many listing pages answer 429 (a pushback without a check)
        self.komo = False  # False: Komo's results page is empty (the steps about Yad2 stay Yad2's)
        self.komo_log, self.madlan_log = [], []
        self.photos = []

    def other_site(self, route):
        """Komo and Madlan, from the Oct 22 saved pages."""
        req = route.request
        url = req.url
        if url.startswith("https://www.komo.co.il/"):
            self.komo_log.append((url, req.headers.get("cookie"), req.resource_type))
            m = re.search(r"modaaNum=(\d+)", url)
            if m:
                body = (SITES / "komo_item_4943180.html").read_text(encoding="utf-8").replace("4943180", m.group(1))
            elif "apartments-for-rent" in url and self.komo:
                body = (SITES / "komo_search_batyam.html").read_text(encoding="utf-8")
            else:
                body = "<html><body>0 מודעות</body></html>"
            return route.fulfill(status=200, content_type="text/html; charset=utf-8", body=body)
        if url.startswith("https://www.madlan.co.il/"):
            self.madlan_log.append((url, req.resource_type))
            if "/for-rent/" in url:
                return route.fulfill(status=200, content_type="text/html; charset=utf-8", body=(SITES / "madlan_search_batyam.html").read_text(encoding="utf-8"))
            return route.fulfill(status=403, body="")
        return route.fulfill(status=204, body="")

    def row(self, x):
        d = x["additionalDetails"]
        md = {"squareMeterBuild": d["squareMeterBuild"]} if "squareMeterBuild" in d else {}
        # v1.31: photos, as Yad2 sends them with the search (served by the fake image server below)
        if x["id"] != TEN[4]:  # v1.33: one listing has no photos at all
            md["coverImage"] = f"https://img.yad2.co.il/Pic/test/{x['id']}_1.png"
            md["images"] = [f"https://img.yad2.co.il/Pic/test/{x['id']}_{i}.png" for i in range(1, 4)]
        return {"token": x["id"], "adType": x["adType"], "price": x["price"],
                "address": {"city": {"text": x["city"]}, "house": {"floor": x["floor"]}, "coords": x["coords"]},
                "additionalDetails": {"roomsCount": d.get("roomsCount"), "squareMeter": d.get("squareMeter"),
                                      "property": {"id": 1, "text": (d.get("property") or {}).get("text")}},
                "metaData": md}

    def item(self, x):
        return {"token": x["id"], "adType": x["adType"], "price": x["price"],
                "address": {"city": {"text": x["city"]}, "neighborhood": {"text": x["neighborhood"]}, "street": {"text": x["street"]},
                            "house": {"floor": x["floor"]}, "coords": x["coords"]},
                "additionalDetails": x["additionalDetails"], "inProperty": x["inProperty"], "dates": x.get("dates", {}),
                "metaData": {"description": x["description"]}, "customer": {"name": "Test Poster", "id": 1}}

    def search(self, url):
        q = parse_qs(urlparse(url).query)
        cap = float(q["maxPrice"][0]) if "maxPrice" in q else None
        rows = [self.row(x) for x in self.xs if cap is None or x["price"] <= cap]
        page = int(q.get("page", ["1"])[0])
        per = 20
        data = {"private": rows[(page - 1) * per: page * per], "agency": [],
                "pagination": {"total": len(rows), "totalPages": -(-len(rows) // per)}}
        return _nd([{"queryKey": ["realestate", "rent-feed", {}], "state": {"data": data}}])

    HOODS = {5000: [(205, "מרכז העיר", "City Center"), (848, "נווה צדק", "Neve Tzedek"), (1483, "הצפון הישן - החלק הצפוני", "Old North- North"),
                    (197, "רמת אביב", "Ramat Aviv"), (209, "נווה אליעזר וכפר שלם מזרח", "Neve Eliezer and Kfar Shalem East"),
                    (206, "יד אליהו", "Yad Eliyahu"), (493, "עג'מי, גבעת העליה", "Ajami, Givaat Haaliya"), (494, "צהלון, שיכוני חסכון", "Tzahalon, Shikunei Chisachon")],
             8600: [(1, "מרכז העיר", "City Center")]}

    PINS = {205: (32.0565, 34.7705), 848: (32.0610, 34.7650), 1483: (32.0920, 34.7780), 197: (32.1130, 34.8000),
            209: (32.0560, 34.8150), 206: (32.0570, 34.7930), 493: (32.0480, 34.7530), 494: (32.0420, 34.7560)}

    def photo(self, route):
        self.photos.append(route.request.url)
        return route.fulfill(status=200, content_type="image/png", body=_png(route.request.url))

    def handle(self, route):
        url = route.request.url
        if url.startswith("https://gw.yad2.co.il/address-master/hoods"):
            city = int(parse_qs(urlparse(url).query)["city_id"][0])
            # v1.32: with where each one is, as Yad2's extended list has it (centers near the real ones)
            data = [{"hood_id": i, "hood_heb": he, "hood_eng": en, "city_id": str(city),
                     "hood_lat": self.PINS.get(i, (None, None))[0], "hood_lon": self.PINS.get(i, (None, None))[1],
                     **({"hood_min_x": self.PINS[i][1] - 0.006, "hood_max_x": self.PINS[i][1] + 0.006,
                         "hood_min_y": self.PINS[i][0] - 0.005, "hood_max_y": self.PINS[i][0] + 0.005} if i in self.PINS else {}),
                     **({"city_min_x": 34.74, "city_max_x": 34.83, "city_min_y": 32.03, "city_max_y": 32.12} if city == 5000 else {})}
                    for i, he, en in self.HOODS.get(city, [])]
            return route.fulfill(status=200, content_type="application/json", body=json.dumps({"data": {"data": data}}, ensure_ascii=False),
                                 headers={"Access-Control-Allow-Origin": "*"})
        if url.startswith("https://routing.openstreetmap.de/"):
            self.osrm += 1
            pins = urlsplit(url).path.split("/driving/")[1].split(";")[1:]  # urlsplit: urlparse would cut at the ';'
            assert pins, url
            dist = [0.0]
            for p in pins:
                lon, lat = (float(v) for v in p.split(","))
                x = next((x for x in self.xs if round(x["coords"]["lat"], 4) == lat and round(x["coords"]["lon"], 4) == lon), None)
                dist.append(self.km[x["id"]] * 1000 if x else 3000.0)  # a Madlan pin (v1.27): 3 km
            body = json.dumps({"code": "Ok", "distances": [dist], "durations": [[d / 5 for d in dist]]})
            return route.fulfill(status=200, content_type="application/json", body=body,
                                 headers={"Access-Control-Allow-Origin": "*"})
        m = re.match(r"https://www\.yad2\.co\.il/realestate/item/([A-Za-z0-9]+)$", url)
        if m and self.soft > 0:
            self.soft -= 1
            return route.fulfill(status=429, body="slow down")
        if m:
            self.items.append(m.group(1))
            x = next((x for x in self.xs if x["id"] == m.group(1)), None)
            if x is None:
                return route.fulfill(status=404, body="gone")
            return route.fulfill(status=200, content_type="text/html", body=_nd([{"queryKey": ["item", x["id"]], "state": {"data": self.item(x)}}]))
        if self.check == "armed" and url.startswith("https://www.yad2.co.il/") and ("page=" in url or "/item/" in url):
            self.check = True  # v1.32: the search's tab loads, then Yad2 starts asking for its check
        if self.check is True and url.startswith("https://www.yad2.co.il/"):
            return route.fulfill(status=200, content_type="text/html", body="<html><title>Radware Bot Manager Captcha</title>captcha</html>")
        if url.startswith("https://www.yad2.co.il/realestate/rent"):
            self.searches.append(url)
            if "page=" in url:  # the pull's own reads, not a page load
                self.search_times.append(time.time())
            return route.fulfill(status=200, content_type="text/html", body=self.search(url))
        return route.fulfill(status=204, body="")  # anything else Yad2's page would load


def _chromium():
    for p in sorted(Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")).glob("chromium-*/chrome-linux*/chrome")):
        return str(p)
    return None


@unittest.skipUnless(sync_playwright and _chromium() and sys.platform.startswith("linux"), "Playwright with Chromium (Linux) isn't installed")
class TestExtensionEndToEnd(unittest.TestCase):
    def test_one_click(self):
        from rental_matcher import install
        fake = FakeYad2()
        got = {}
        with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
            tmp = Path(tmp)
            prefs = json.loads((ROOT / "tests" / "fixtures" / "prefs_frozen.json").read_text(encoding="utf-8"))
            prefs["searches"] = [{"source": "yad2", "label": "Bat Yam", "label_he": "בת ים", "path": "/realestate/rent/tel-aviv-area?area=11&city=6600"}]
            prefs_path = tmp / "prefs.json"
            prefs_path.write_text(json.dumps(prefs, ensure_ascii=False), encoding="utf-8")
            profile = tmp / "profile"
            hosts = [profile / "NativeMessagingHosts", Path.home() / ".config" / "chromium" / "NativeMessagingHosts"]
            install.install(prefs_path, python=sys.executable, host_dirs=hosts, where=tmp / "data")
            ext = str(ROOT / "browser")
            ctx = pw.chromium.launch_persistent_context(
                str(profile), headless=True, executable_path=_chromium(),
                args=[f"--disable-extensions-except={ext}", f"--load-extension={ext}", "--headless=new"],
                viewport={"width": 1400, "height": 900})
            base = f"chrome-extension://{install.EXTENSION_ID}"

            def shot(page, name):
                if SHOTS:
                    page.screenshot(path=str(Path(SHOTS) / f"{name}.png"))
            try:
                ctx.route("https://www.yad2.co.il/**", fake.handle)
                ctx.route("https://routing.openstreetmap.de/**", fake.handle)
                ctx.route("https://gw.yad2.co.il/**", fake.handle)
                ctx.route("https://www.komo.co.il/**", fake.other_site)
                ctx.route("https://img.yad2.co.il/**", fake.photo)
                ctx.route("https://*.tile.openstreetmap.fr/**", lambda r: r.fulfill(status=200, content_type="image/png", body=_png("tile", 256, 256)))
                ctx.route("https://www.madlan.co.il/**", fake.other_site)

                # 0. the first time: opening the extension starts the quick setup (v1.30), which can be skipped
                first = ctx.new_page()
                with ctx.expect_page(predicate=lambda pg: "wizard.html" in pg.url) as welcome:
                    first.goto(f"{base}/sidepanel.html")
                first_run = welcome.value
                first_run.locator(".card h1").wait_for(timeout=20000)
                got["tour"] = first_run.locator(".card h1").inner_text()
                shot(first_run, "wizard")
                for _ in range(6):  # through every question with the answers already there
                    first_run.locator(".nav .btn.primary").click()
                    time.sleep(0.4)
                first_run.locator(".summary").wait_for(timeout=10000)
                got["wizard_summary"] = first_run.locator(".summary").inner_text()
                with first_run.expect_navigation():
                    first_run.locator("#skip").click()
                got["after_skip"] = first_run.url
                first_run.close()
                # v1.32: the panel is Chrome's side panel; here it's the same page in a tab
                side = ctx.new_page()
                side.goto(f"{base}/sidepanel.html")
                side.locator("#rental-matcher-root .est", has_text="Takes about").wait_for(timeout=20000)
                got["estimate"] = side.locator("#rental-matcher-root .est").inner_text()
                storage = lambda key: side.evaluate(f"chrome.storage.local.get('{key}').then(o => o['{key}'])")  # noqa: E731
                # v1.40: listings with no photos are hidden by default; the flow below keeps TEN[4] (no photos) in view,
                # and step 4 checks the switch itself
                side.evaluate("chrome.storage.local.get('ui').then(o => chrome.storage.local.set({ui: Object.assign(o.ui || {}, {hideNoPhotos: false})}))")
                yad2_url = "https://www.yad2.co.il/realestate/rent/tel-aviv-area?area=11&city=6600"

                def clear():
                    side.evaluate("chrome.storage.local.remove('status')")

                def finished(n):
                    side.wait_for_function(f"chrome.storage.local.get('status').then(o => !!o.status && o.status.stage === 'done' && o.status.shown === {n})",
                                           timeout=120000)

                def shown(page):
                    # Chrome's side panel stays on screen next to the tab; here it's a tab of its own, which
                    # Chrome stops running while another tab is in front: bring it back, as the side panel would be
                    page.bring_to_front()
                    page.locator("#rental-matcher-root .status", has_text="Done in").wait_for(timeout=120000)
                    return [a.get_attribute("data-id") for a in page.locator("#rental-matcher-root .grid > article.rm-card").all()]

                def pull_in_new_tab():
                    """Find listings: the extension opens a Yad2 tab of its own, in the background."""
                    with ctx.expect_page() as opened:
                        side.locator("#rental-matcher-root button.act", has_text="Find listings").click()
                    tab = opened.value
                    tab.wait_for_load_state()
                    # The harness can't intercept the very first load of a tab the extension opens
                    # (there's no network here, so it's an error page); loading it again goes through
                    # the fake Yad2, and the page picks up the pull it was opened for.
                    if tab.url.startswith("chrome-error://"):
                        tab.goto(yad2_url)
                    return tab

                def clear_cache(stores):
                    y = ctx.new_page()
                    y.goto("https://www.yad2.co.il/realestate/item/none")
                    y.evaluate("""(names) => new Promise((ok) => { const r = indexedDB.open('rental-matcher-cache', 2);
                        r.onsuccess = () => { const t = r.result.transaction(names, 'readwrite');
                          for (const n of names) t.objectStore(n).clear(); t.oncomplete = () => ok(1); }; })""", stores)
                    y.close()
                    side.bring_to_front()

                # 1. one click: the extension reads Yad2 in a tab of its own, and the panel shows what it finds
                t0 = time.time()
                tab = pull_in_new_tab()
                got["first_active"] = side.evaluate("chrome.tabs.query({url: 'https://www.yad2.co.il/*'}).then(ts => ts.map(t => t.active))")  # never brought to the front
                got["first"] = shown(side)
                got["first_s"] = time.time() - t0
                # Photos are the only images allowed, and only from the photo hosts
                imgs = side.locator("#rental-matcher-root img")
                srcs = [imgs.nth(i).get_attribute("src") or "" for i in range(imgs.count())]
                got["injected"] = sum(1 for s in srcs if not s.startswith("https://img.yad2.co.il/"))
                got["injected"] += side.locator("#rental-matcher-root img[onerror]").count()
                got["pwned"] = side.evaluate("window.__pwned === 1")
                got["card"] = side.locator("#rental-matcher-root .grid > article.rm-card").first.inner_text()
                got["summary"] = side.locator("#rental-matcher-root .sum").inner_text()
                got["dir"] = side.evaluate("getComputedStyle(document.querySelector('#rental-matcher-root').shadowRoot.querySelector('.rm-card')).direction")
                finished(10)
                time.sleep(1)
                got["first_tab_closed"] = tab.is_closed()  # the search's tab goes when it's done
                got["stick"] = side.evaluate("getComputedStyle(document.querySelector('#rental-matcher-root').shadowRoot.querySelector('.stick')).position")  # v1.41
                got["cols"] = side.evaluate("getComputedStyle(document.querySelector('#rental-matcher-root').shadowRoot.querySelector('.grid')).gridTemplateColumns.split(' ').length")
                shot(side, "panel")
                opened_first = list(fake.items)

                # 2. again: nothing opened or routed again, and no tab left behind
                fake.items.clear()
                osrm = fake.osrm
                pages_before = len(ctx.pages)
                clear()
                pull_in_new_tab()
                finished(10)
                got["second"] = shown(side)
                time.sleep(1)
                got["second_items"] = list(fake.items)
                got["second_osrm"] = fake.osrm - osrm
                got["second_pages"] = len(ctx.pages) - pages_before

                # 3. a Yad2 page of your own: nothing added to it, and no search of its own
                reads = len([u for u in fake.searches if "page=" in u])
                other = ctx.new_page()
                other.goto(f"https://www.yad2.co.il/realestate/item/{TEN[3]}")
                time.sleep(3)
                got["other_reads"] = len([u for u in fake.searches if "page=" in u]) - reads
                got["other_added"] = other.locator("#rental-matcher-root").count()
                other.close()

                # 4. your calls: reject the top one, favorite and "interested" on the next
                root = side.locator("#rental-matcher-root .grid > article.rm-card")
                # (v1.31: the simple card: "Not for me", the heart on the photo, "Interested" under "More")
                got["simple_photos"] = side.locator("#rental-matcher-root .grid > article.rm-simple .rm-photo img").count()
                got["photos_before"] = list(fake.photos)
                got["no_photos_card"] = side.locator(f"#rental-matcher-root .grid > article.rm-card[data-id={TEN[4]}] .rm-photo").inner_text()
                # v1.40: the setup page's "Hide listings with no photos" (on by default) takes it off the panel, and back
                sel = f"document.querySelector('#rental-matcher-root').shadowRoot.querySelector('.grid > article.rm-card[data-id=\"{TEN[4]}\"]')"
                side.evaluate("chrome.storage.local.get('ui').then(o => chrome.storage.local.set({ui: Object.assign(o.ui || {}, {hideNoPhotos: true})}))")
                side.wait_for_function(f"!{sel}", timeout=5000)
                got["nophoto_hidden"] = side.locator("#rental-matcher-root .grid > article.rm-card").count()
                side.evaluate("chrome.storage.local.get('ui').then(o => chrome.storage.local.set({ui: Object.assign(o.ui || {}, {hideNoPhotos: false})}))")
                side.wait_for_function(f"!!{sel}", timeout=5000)
                third = root.nth(2)
                got["third_id"] = third.get_attribute("data-id")
                third.locator(".rm-ph-nav.next").click(force=True)
                time.sleep(0.5)
                got["after_next"] = third.locator(".rm-photo img").get_attribute("src")
                got["count_after_next"] = third.locator(".rm-ph-count").inner_text()
                root.first.locator("button", has_text="Not for me").click()
                side.wait_for_function("document.querySelector('#rental-matcher-root').shadowRoot.querySelectorAll('.grid > article.rm-card').length === 9")
                root.first.locator("button.rm-heart").click()
                side.wait_for_function("document.querySelector('#rental-matcher-root').shadowRoot.querySelector('.grid > article.rm-card').classList.contains('rm-fav')")
                root.first.locator("details.rm-more summary").click()
                root.first.locator("button", has_text="Interested").click()
                time.sleep(0.5)
                got["marks"] = storage("marks")
                # one card's details, then all of them detailed and back
                root.nth(1).locator("button.rm-detail").click()
                side.locator("#rental-matcher-root .grid > article.rm-detailed .rm-kv").first.wait_for(timeout=5000)
                got["one_detailed"] = side.locator("#rental-matcher-root .grid > article.rm-detailed").count()
                shot(side, "panel_one_detailed")
                side.locator("#rental-matcher-root .seg button", has_text="Detailed").click()
                time.sleep(0.3)
                got["all_detailed"] = side.locator("#rental-matcher-root .grid > article.rm-detailed").count()
                got["ui_detail"] = storage("ui").get("detail")
                side.locator("#rental-matcher-root .seg button", has_text="Simple").click()
                time.sleep(0.3)
                results = ctx.new_page()
                results.goto(f"{base}/results.html")
                results.locator(".shelf h2").first.wait_for(timeout=10000)
                got["shelves"] = [h.inner_text() for h in results.locator(".shelf h2").all()]
                got["views"] = [b.inner_text().split("\n")[0] for b in results.locator("#views .view").all()]
                got["chips_folded"] = results.locator("#chips").is_hidden()
                shot(results, "results_shelves")
                results.locator("#views .view", has_text="Every listing").click()
                results.locator(".tab", has_text="Favorites").wait_for(timeout=10000)
                got["tabs"] = [t.inner_text().replace("\n", " ") for t in results.locator(".tab").all()]
                shot(results, "results")
                results.locator("#filt").click()
                results.locator(".fchip", has_text="Balcony").first.click()
                time.sleep(0.3)
                got["chip_cards"] = results.locator(".grid .rm-card").count()
                got["filt_label"] = results.locator("#filt").inner_text()
                results.locator(".fchip", has_text="Balcony").first.click()
                results.locator("#views .view", has_text="Picks for you").click()
                results.close()

                # 5. the next pull doesn't open the rejected one, and doesn't show it
                clear()
                pull_in_new_tab()
                finished(9)
                got["after_reject"] = shown(side)
                kept = storage("results")
                got["rejected_why"] = kept["skippedRows"].get(TEN[0])
                # v1.40: "Missing a listing?" and what each search covered
                results = ctx.new_page()
                results.goto(f"{base}/results.html")
                results.locator("#find").click()
                finder = results.locator("#finder input")
                finder.fill(f"https://www.yad2.co.il/realestate/item/{TEN[0]}")
                results.locator("#finder button").click()
                got["find_rejected"] = results.locator("#finder .fdout").inner_text()
                finder.fill(f"https://www.yad2.co.il/realestate/item/{TEN[1]}")
                results.locator("#finder button").click()
                got["find_shown"] = results.locator("#finder .fdout").inner_text()
                finder.fill("https://www.yad2.co.il/realestate/item/zzzzzzzz")
                results.locator("#finder button").click()
                got["find_unseen"] = results.locator("#finder .fdout").inner_text()
                got["coverage_rows"] = results.locator("#stats table").first.locator("tr").count()
                shot(results, "results_finder")
                # v1.41: send listings to someone without the extension: a page to send
                results.locator("#share").click()
                results.locator("#sharebox[open]").wait_for(timeout=5000)
                got["share_boxes"] = [b.is_checked() for b in results.locator("#sharebox input[type=checkbox]").all()]
                shot(results, "results_share")
                with results.expect_download() as dl:
                    results.locator("#sharebox button", has_text="Download a page to share").click()
                page_html = Path(dl.value.path()).read_text(encoding="utf-8")
                got["share_cards"] = page_html.count('<article class="card">')
                got["share_script"] = "<script" in page_html
                got["share_link"] = f"https://www.yad2.co.il/realestate/item/{TEN[1]}" in page_html
                results.close()
                side.bring_to_front()

                # 6. Yad2's check: the search's tab comes to the front with the real check, a window says so,
                #    and once it's done the search goes on
                clear_cache(["listings", "searches"])
                side.evaluate("chrome.storage.local.set({tuning: {solvedDelayMs: 300, cooldownMs: 1500}})")
                fake.check = "armed"
                clear()
                with ctx.expect_page(predicate=lambda pg: "check.html" in pg.url, timeout=60000) as win:
                    tab = pull_in_new_tab()
                window = win.value
                window.wait_for_load_state()
                got["window_url"] = window.url
                got["window_text"] = window.locator("main").inner_text()
                shot(window, "check_window")
                got["check_front"] = side.evaluate("chrome.tabs.query({url: 'https://www.yad2.co.il/*'}).then(ts => ts.map(t => t.active))")
                side.bring_to_front()
                side.locator("#rental-matcher-root .ycheck").wait_for(timeout=10000)
                got["check_panel"] = side.locator("#rental-matcher-root .ycheck").inner_text()
                got["checks"] = storage("checks")
                got["log"] = [e["kind"] for e in storage("log")]
                got["pushback"] = next(e for e in storage("log") if e["kind"] == "pushback")
                fake.check = False
                n_before = len(fake.search_times)
                tab.reload()  # what Yad2 does once the check is done: back to the page
                side.bring_to_front()
                finished(9)
                got["resumed"] = shown(side)
                got["times"] = fake.search_times[n_before:]
                time.sleep(0.5)
                got["window_closed"] = window.is_closed()
                if not tab.is_closed():
                    tab.close()  # it stays open if you're looking at it; here, close it for the next steps

                # 7. a pushback without a check: a pause, then half the pace
                clear_cache(["listings"])
                fake.soft = 1
                clear()
                tab = pull_in_new_tab()
                finished(9)
                got["soft"] = shown(side)
                if not tab.is_closed():
                    tab.close()
                got["soft_checks"] = storage("checks")
                got["soft_log"] = [e["kind"] for e in storage("log")]
                got["pulls"] = storage("pulls")

                # 8. ways to see more: one line; its options show on hover, and Apply saves one
                line = side.locator("#rental-matcher-root .rm-moreline")
                line.wait_for(timeout=20000)
                got["more_line"] = line.locator("span").first.inner_text()
                got["more_hidden"] = side.locator("#rental-matcher-root .rm-morepop").is_hidden()
                line.hover()
                more = side.locator("#rental-matcher-root .rm-morepop li")
                more.first.wait_for(timeout=5000)
                got["suggestions"] = [li.inner_text() for li in more.all()]
                shot(side, "panel_more")
                before_prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
                more.first.locator("button").click()
                side.locator("#rental-matcher-root .rm-morepop li", has_text="Saved").wait_for(timeout=20000)
                after_prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
                got["relaxed"] = [(a["name"], a.get("limit"), b.get("limit")) for a, b in zip(before_prefs["preferences"], after_prefs["preferences"]) if a != b]

                # 9. other sites: a Madlan page the user opens is kept; the pull adds Komo, and never fetches Madlan
                mad = ctx.new_page()
                mad.goto("https://www.madlan.co.il/for-rent/%D7%97%D7%95%D7%9C%D7%95%D7%9F-%D7%99%D7%A9%D7%A8%D7%90%D7%9C")
                mad.locator("[role=status]", has_text="kept 5 listings").wait_for(timeout=20000)
                got["pool"] = sorted(storage("pool")["rows"])
                mad.close()
                madlan_loads = len(fake.madlan_log)
                fake.komo = True
                komo_before = len(fake.komo_log)
                clear()
                pull_in_new_tab()
                side.wait_for_function("chrome.storage.local.get('status').then(o => !!o.status && o.status.stage === 'done' && !o.status.running)", timeout=120000)
                side.locator("#rental-matcher-root .status", has_text="Done in").wait_for(timeout=120000)
                kept = storage("results")
                got["sources"] = sorted({r.get("source") for r in kept["results"]})
                got["by_source"] = kept["bySource"]
                got["komo_cards"] = side.locator("#rental-matcher-root .grid > article.rm-card[data-source=komo]").count()
                got["madlan_cards"] = side.locator("#rental-matcher-root .grid > article.rm-card[data-source=madlan]").count()
                links = [a.get_attribute("href") for a in side.locator("#rental-matcher-root .grid > article.rm-card a.rm-go, "
                                                                        "#rental-matcher-root .grid > article.rm-card a.rm-link").all()]
                got["yad2_go"] = side.locator("#rental-matcher-root .grid > article.rm-card[data-source=yad2] a.rm-go").first.get_attribute("href")
                got["komo_links"] = [u for u in links if "komo.co.il" in u]
                got["madlan_fetched"] = fake.madlan_log[madlan_loads:]
                got["komo_log"] = fake.komo_log[komo_before:]
                got["komo_all"] = list(fake.komo_log)
                shot(side, "panel_sites")
                for site in ("komo", "madlan"):
                    card = side.locator(f"#rental-matcher-root .grid > article.rm-card[data-source={site}]")
                    if SHOTS and card.count():
                        card.first.screenshot(path=str(Path(SHOTS) / f"card_{site}.png"))
                fake.komo = False

                # 9b. tune the ranking: pick between two, eight times, and see what it says (v1.32)
                cmp = ctx.new_page()
                cmp.goto(f"{base}/compare.html")
                cmp.locator(".pick").first.wait_for(timeout=10000)
                got["cmp_cards"] = cmp.locator(".side .rm-card").count()
                pair = [c.get_attribute("data-id") for c in cmp.locator(".side .rm-card").all()]
                cmp.locator("#detail button", has_text="Detailed").click()  # v1.36: the full cards, the same pair
                cmp.locator(".side .rm-detailed").first.wait_for(timeout=5000)
                got["cmp_detailed"] = (cmp.locator(".side .rm-detailed").count(), [c.get_attribute("data-id") for c in cmp.locator(".side .rm-card").all()] == pair)
                shot(cmp, "compare_detailed")
                cmp.locator("#detail button", has_text="Simple").click()
                shot(cmp, "compare")
                for i in range(8):
                    cmp.locator(".pick").nth(i % 2).click()
                    time.sleep(0.2)
                pair = [c.get_attribute("data-id") for c in cmp.locator(".side .rm-card").all()]
                cmp.locator("button", has_text="Neither").click()  # v1.40: neither: no preference, and nothing is hidden
                time.sleep(0.5)
                got["cmp_neither"] = [(storage("marks").get(i) or {}).get("status") for i in pair]
                got["cmp_picks"] = len(storage("tune")["picks"])
                cmp.locator("#result").click()
                cmp.locator("#report .num").first.wait_for(timeout=60000)
                got["cmp_report"] = cmp.locator("#report").inner_text()
                got["cmp_rows"] = cmp.locator("#report table tr").count()
                shot(cmp, "compare_report")
                cmp.close()

                # 10. setup (v1.37: no Save button; every change saves itself): a whole city, Tel Aviv without Jaffa,
                #     then its neighborhoods edited on the map
                opts = ctx.new_page()
                opts.goto(f"{base}/options.html")
                opts.locator(".place", has_text="Bat Yam").wait_for(timeout=20000)
                got["save_buttons"] = opts.locator("#save").count() + opts.locator("#hoodbox button", has_text="Save").count()
                saved_ok = lambda: opts.locator("#msg", has_text="All changes saved").wait_for(timeout=20000)  # noqa: E731
                opts.locator("#city").fill("Ramat Gan")
                opts.locator("#city").press("Enter")
                opts.locator("#citymsg", has_text="Added Ramat Gan").wait_for(timeout=20000)  # picked: added, no "Add"
                time.sleep(1)
                saved_ok()
                opts.locator("#hoodbox button.primary", has_text="Done").click()
                opts.locator("#city").fill("Tel Aviv (without Jaffa) · תל אביב")
                opts.locator("#city").press("Enter")
                opts.locator("#hoodbox .hm path").first.wait_for(timeout=20000)
                # v1.33: the map opens with nothing picked; the preset's whole area is what's searched
                got["map_areas"] = opts.locator("#hoodbox .hm path").count()
                got["map_on"] = opts.locator("#hoodbox .hm path.on").count()
                got["tiles"] = [i.get_attribute("src") for i in opts.locator("#hoodbox .hm-tiles img").all()][:2]
                opts.locator(".place", has_text="Tel Aviv").wait_for(timeout=20000)
                got["place_tlv"] = opts.locator(".place", has_text="Tel Aviv").inner_text()
                time.sleep(1)
                saved_ok()
                opts.locator("#hoodbox button.primary", has_text="Done").click()

                def area_point(hood):
                    return opts.evaluate("""(id) => { const p = document.querySelector(`#hoodbox .hm path[data-id="${id}"]`); const b = p.getBBox();
                        const r = p.ownerSVGElement.getBoundingClientRect(); for (let i = 0; i < 400; i++) { const x = b.x + Math.random() * b.width, y = b.y + Math.random() * b.height;
                        if (p.isPointInFill(new DOMPoint(x, y))) return [r.left + x, r.top + y]; } return null; }""", hood)
                # edit it: its six open picked; a click on Ajami adds it, and that's saved, nothing else to press
                opts.locator(".place", has_text="Tel Aviv").locator("button", has_text="Edit on the map").click()
                opts.locator("#hoodbox .hm path.on").first.wait_for(timeout=20000)
                got["edit_on"] = opts.locator("#hoodbox .hm path.on").count()
                opts.locator("#hoodbox .hm").scroll_into_view_if_needed()
                pt = area_point(493)
                opts.mouse.click(pt[0], pt[1])
                time.sleep(0.2)
                got["map_after_click"] = (opts.locator("#hoodbox .hm path.on").count(), opts.locator("#hoodbox .hoodlist input:checked").count())
                shot(opts, "setup_map")
                opts.locator(".place", has_text="7 neighborhoods").wait_for(timeout=20000)
                got["place_tlv_after"] = opts.locator(".place", has_text="Tel Aviv").inner_text()
                time.sleep(1)
                saved_ok()
                opts.locator("#hoodbox button.primary", has_text="Done").click()
                shot(opts, "setup")
                got["saved"] = json.loads(prefs_path.read_text(encoding="utf-8"))
                got["backups"] = len(list((tmp / ".backups").glob("*.json")))

                # 10b. the panel on a page (v1.33): docked left in English, wider by dragging its edge
                page = ctx.new_page()
                page.goto(f"https://www.yad2.co.il/realestate/item/{TEN[2]}")
                time.sleep(1)
                tab_id = side.evaluate("chrome.tabs.query({url: 'https://www.yad2.co.il/realestate/item/*'}).then(ts => ts[0].id)")
                side.evaluate("""(id) => chrome.scripting.executeScript({target: {tabId: id}, files: ["i18n.js", "store.js", "cards.js", "panel.js", "panelhost.js", "overlay.js"]})""", tab_id)
                page.locator("#rental-matcher-root .grid > article.rm-card").first.wait_for(timeout=20000)
                box = lambda: page.evaluate("(() => { const r = document.querySelector('#rental-matcher-root').shadowRoot.querySelector('.panel').getBoundingClientRect(); return [Math.round(r.left), Math.round(r.right), innerWidth]; })()")  # noqa: E731
                got["dock_en"] = box()
                g = page.locator("#rental-matcher-root .grip").bounding_box()
                page.mouse.move(g["x"] + 5, g["y"] + g["height"] / 2)
                page.mouse.down()
                page.mouse.move(g["x"] + 305, g["y"] + g["height"] / 2, steps=8)
                page.mouse.up()
                time.sleep(0.3)
                got["dock_wider"] = box()
                got["ui_width"] = storage("ui").get("panelWidth")
                shot(page, "overlay")

                # 11. Hebrew: the whole thing right to left, in Hebrew
                side.locator("#rental-matcher-root .icon", has_text="עב").click()
                side.wait_for_function("document.querySelector('#rental-matcher-root').shadowRoot.querySelector('.wrap').dir === 'rtl'", timeout=10000)
                got["he_panel"] = side.evaluate("document.querySelector('#rental-matcher-root').shadowRoot.querySelector('.panel').innerText")
                shot(side, "panel_he")
                page.wait_for_function("document.querySelector('#rental-matcher-root').shadowRoot.querySelector('.wrap').dir === 'rtl'", timeout=10000)
                time.sleep(0.3)
                got["dock_he"] = box()
                shot(page, "overlay_he")
                opts.reload()
                opts.locator("h1", has_text="הגדרות").wait_for(timeout=10000)
                got["he_setup_dir"] = opts.evaluate("document.documentElement.dir")
                shot(opts, "setup_he")
                res = ctx.new_page()
                res.goto(f"{base}/results.html")
                res.locator("h1", has_text="המודעות שלך").wait_for(timeout=10000)
                shot(res, "results_he")
                res.locator("#v-stats").click()
                res.locator(".stat").first.wait_for(timeout=10000)
                got["he_stats"] = res.locator("#stats").inner_text()
                shot(res, "stats_he")
            finally:
                ctx.close()
                install.uninstall(host_dirs=hosts, where=tmp / "data")

        self.assertEqual((got["injected"], got["pwned"]), (0, False))  # a listing's text is shown as text, never run
        self.assertEqual(got["first"], TEN)  # the same ten, in the same order, as the pipeline on these pages
        reads = [u for u in fake.searches if "page=" in u]
        self.assertTrue(all("area=11&city=6600&maxPrice=5450&page=" in u for u in reads), reads[:3])  # the preferences' search, with the cap
        self.assertEqual(sorted(opened_first), sorted(TEN))  # only those were opened
        self.assertIn("10 matches", got["summary"])
        self.assertRegex(got["card"], r"₪[\d,]+ a month")  # the simple card: price first
        self.assertRegex(got["card"], r"(Great|Good|Fair|Weak|Poor|Possible) match|Not a match|match")
        self.assertNotRegex(got["card"], r"\d+%")  # the numbers wait in the detailed view
        self.assertEqual(got["dir"], "ltr")
        self.assertGreater(got["cols"], 1)  # a wide side panel shows cards side by side
        self.assertEqual(got["first_active"], [False])  # the search's tab stays in the background
        self.assertTrue(got["first_tab_closed"])
        self.assertIn("Takes about", got["estimate"])
        self.assertLess(got["first_s"], 60)
        self.assertEqual(got["second"], TEN)
        self.assertEqual((got["second_items"], got["second_osrm"], got["second_pages"]), ([], 0, 0))  # all cached, and no tab left behind
        self.assertEqual((got["other_reads"], got["other_added"]), (0, 0))  # one pull only, and Yad2's page is left as it is
        self.assertEqual(got["marks"][TEN[0]]["status"], "rejected")
        self.assertEqual((got["marks"][TEN[1]]["fav"], got["marks"][TEN[1]]["status"]), (True, "interested"))
        self.assertIn("★ Favorites1", got["tabs"])
        self.assertIn("All9", got["tabs"])
        self.assertIn("Interested1", got["tabs"])
        self.assertIn("Rejected1", got["tabs"])
        self.assertEqual(got["after_reject"], TEN[1:])
        self.assertEqual(got["rejected_why"], ["You rejected it"])
        self.assertTrue(got["window_url"].endswith("/check.html"), got["window_url"])
        self.assertIn("Yad2 wants to check you're a person", got["window_text"])
        self.assertEqual(got["checks"]["count"], 1)
        self.assertEqual(got["log"][-2:], ["pushback", "check shown"])
        self.assertEqual(got["pushback"]["what"], "search page")
        self.assertEqual(got["resumed"], TEN[1:])
        gaps = [b - a for a, b in zip(got["times"], got["times"][1:])]
        self.assertTrue(gaps and all(g >= 2.3 for g in gaps), gaps)  # after a check: half the pace
        self.assertTrue(got["window_closed"])
        self.assertEqual(got["check_front"], [True])  # only Yad2's check brings its tab to the front
        self.assertIn("check", got["check_panel"].lower())
        self.assertEqual(got["soft"], TEN[1:])
        self.assertEqual((got["soft_checks"]["count"], got["soft_checks"]["soft"]), (1, 1))
        self.assertIn("no check shown", got["soft_log"])
        self.assertEqual([p["kind"] for p in got["pulls"]][:2], ["first", "repeat"])
        self.assertEqual(got["tour"], "Let's find your next home")
        self.assertIn("Bat Yam", got["wizard_summary"])
        self.assertTrue(got["after_skip"].endswith("/options.html"), got["after_skip"])
        self.assertTrue(got["suggestions"] and all("more listings" in x for x in got["suggestions"]), got["suggestions"])
        self.assertRegex(got["more_line"], r"(ways? to see|One way to see).* more listings")
        self.assertTrue(got["more_hidden"])  # the options wait for the hover
        self.assertEqual(len(got["relaxed"]), 1, got["relaxed"])  # one preference loosened, as the suggestion said
        labels = [x["label"] for x in got["saved"]["searches"]]
        self.assertEqual(labels[:2], ["Bat Yam", "Ramat Gan"])
        self.assertEqual(got["saved"]["searches"][1]["path"], "/realestate/rent?city=8600")
        self.assertEqual((got["map_areas"], got["map_on"]), (8, 0))  # an area for each neighborhood; none picked when the map opens
        self.assertTrue(got["tiles"] and all("tile.openstreetmap.fr/osmfr/" in u for u in got["tiles"]), got["tiles"])
        self.assertEqual(got["map_after_click"], (7, 7))  # a click on Ajami picks it, on the map and in the list
        self.assertEqual(got["save_buttons"], 0)  # v1.37: one way to save: it saves itself
        self.assertIn("6 neighborhoods", got["place_tlv"])  # what was saved, said on its card
        self.assertEqual(got["edit_on"], 6)  # editing opens with them picked
        self.assertIn("7 neighborhoods", got["place_tlv_after"])
        tlv = got["saved"]["searches"][2:]
        self.assertEqual(len(tlv), 7)  # up to 12: a Yad2 search for each, filtered by Yad2 itself
        self.assertEqual(sorted(int(x["path"].split("neighborhood=")[1]) for x in tlv), [197, 205, 206, 209, 493, 848, 1483])
        self.assertTrue(all(x["path"].startswith("/realestate/rent?city=5000&neighborhood=") for x in tlv))
        # v1.33: the panel on a page
        left, right, width = got["dock_en"]
        self.assertEqual(left, 0)  # English: docked left
        self.assertGreater(got["dock_wider"][1] - got["dock_wider"][0], right - left + 250)  # dragged about 300 px wider
        self.assertEqual(got["ui_width"], got["dock_wider"][1] - got["dock_wider"][0])
        self.assertAlmostEqual(got["dock_he"][1], got["dock_he"][2], delta=2)  # Hebrew: docked right
        self.assertEqual(got["backups"], 4)  # the suggestion's save, then each change to where to look (saved by itself)
        self.assertIn("חיפוש מודעות", got["he_panel"])
        self.assertIn("לא בשבילי", got["he_panel"])  # Not for me, in Hebrew
        self.assertNotRegex(got["he_panel"], r"\b(Reject|Not for me|Favorite|Interested|Worth asking|What it has|matches|All details)\b")
        self.assertEqual(got["he_setup_dir"], "rtl")
        self.assertIn("מודעות שנבדקו", got["he_stats"])
        self.assertRegex(got["he_stats"], r"הורדת המודעות שנקראו \((?:[1-9]\d*)\)")  # v1.35: the listings read, ready to label
        # v1.32: compare two
        self.assertEqual((got["cmp_cards"], got["cmp_picks"]), (2, 9))
        self.assertEqual(got["cmp_neither"], [None, None])  # v1.40: "Neither" doesn't put them in "Not for me"
        self.assertEqual(got["nophoto_hidden"], 9)  # v1.40: the one with no photos leaves the panel
        self.assertIn("Not for me", got["find_rejected"])  # v1.40: "Missing a listing?"
        self.assertIn("It's in your listings", got["find_shown"])
        self.assertIn("didn't see it", got["find_unseen"])
        self.assertIn("Yad2 listed", got["find_unseen"])
        self.assertGreaterEqual(got["coverage_rows"], 2)  # a header and a row per search
        self.assertEqual(got["share_boxes"], [True, True, False, False])  # v1.41: your marked lists, ticked; none viewing yet
        self.assertEqual((got["share_cards"], got["share_script"], got["share_link"]), (1, False, True))  # the favorite
        self.assertEqual(got["stick"], "sticky")  # v1.41: the panel's count, view and sort stay in view
        self.assertEqual(got["cmp_detailed"], (2, True))
        self.assertIn("What 10 picks say", got["cmp_report"])  # v1.41: 8 picks + "Neither" as 2 comparisons
        self.assertIn("Your weights now", got["cmp_report"])
        self.assertGreater(got["cmp_rows"], 2)
        # v1.27: other sites
        self.assertEqual(len(got["pool"]), 5)
        self.assertTrue(all(i.startswith("madlan:") for i in got["pool"]))
        self.assertEqual(got["sources"], ["komo", "madlan", "yad2"])
        self.assertEqual((got["by_source"]["komo"], got["by_source"]["madlan"]), (21, 5))
        self.assertEqual(got["madlan_fetched"], [])  # Madlan: only the page the user opened, never a fetch
        searches = [u for u, _, _ in got["komo_log"] if "apartments-for-rent" in u]
        self.assertEqual(len(searches), 1)  # Bat Yam's first page, once
        self.assertTrue(all("cityName=%D7%97%D7%95%D7%9C%D7%95%D7%9F" in u and "currPage" not in u for u in searches), searches)
        self.assertTrue(all(c is None for _, c, _ in got["komo_all"]), "Komo is read without cookies")
        self.assertTrue(any("modaaNum=" in u for u, _, _ in got["komo_log"]))
        self.assertGreater(got["komo_cards"] + got["madlan_cards"], 0)
        # v1.31: photos, simple and detailed cards, shelves and quick filters
        self.assertEqual(got["simple_photos"], 9)  # every card with photos shows its first one
        self.assertIn("No photos in this listing", got["no_photos_card"])  # v1.33: and one without says so
        self.assertTrue(got["photos_before"] and all(u.endswith("_1.png") for u in got["photos_before"]), got["photos_before"])  # first photos only
        self.assertTrue(got["after_next"].endswith(f"{got['third_id']}_2.png"), got["after_next"])  # the next one when you ask for it
        self.assertEqual(got["count_after_next"], "2/3")
        self.assertEqual(got["one_detailed"], 1)
        self.assertEqual((got["all_detailed"], got["ui_detail"]), (9, True))
        self.assertEqual(got["shelves"][:2], ["♥ Saved", "⭐ Best for you"])  # v1.32: the one "deal" may be a room in a shared flat, so it isn't one
        self.assertIn("Cheapest", got["shelves"][-1])
        self.assertLess(got["chip_cards"], 9)
        self.assertEqual(got["views"], ["✨ Picks for you", "▦ Every listing", "📊 Statistics"])
        self.assertTrue(got["chips_folded"])
        self.assertEqual(got["filt_label"], "☰ Filters (1)")
        self.assertRegex(got["yad2_go"], r"^https://www\.yad2\.co\.il/realestate/item/\w+$")  # the place is the button to the listing
        self.assertTrue(all(re.fullmatch(r"https://www\.komo\.co\.il/code/nadlan/details/\?modaaNum=\d+", u) for u in got["komo_links"]))


if __name__ == "__main__":
    unittest.main()
