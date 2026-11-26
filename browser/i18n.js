/*
 * Rental Matcher: English and Hebrew (v1.31).
 *
 * Every word the extension shows comes from here, in both languages, and a
 * test (i18n.test.js) checks that each key exists in both. Hebrew turns the
 * whole screen right to left. What comes from a listing or from the user
 * (a street, a place's name) keeps its own direction in a <bdi>, so either
 * language reads cleanly around the other.
 *
 * The helper sends data, not sentences (rental_matcher/server.py: topics,
 * notes, feature keys); the sentences are made here.
 */
(function (root) {
  "use strict";

  const S = {
    en: {
      // brand and common
      app: "Rental Matcher", close: "Close", save: "Save", undo: "Undo", apply: "Apply", remove: "Remove", add: "Add",
      cancel: "Cancel", next: "Next", back: "Back", done: "Done", language: "Language",
      pull: "Find listings", stop: "Stop", wider: "Wider", narrower: "Narrower", all_listings: "All listings", setup: "Setup",
      show_panel: "Show the panel", your_listings: "Your listings", open_yad2: "Open on Yad2", a_month: "a month",
      // time
      sec: "{n} s", min_sec: "{m} min {s} s", min: "{n} min", h_min: "{h} h {m} min",
      left_less: "less than a minute left", left_about: "about {n} min left",
      // stages
      st_starting: "Getting ready", st_search: "Reading your searches", st_search_x: "Reading your searches: {x}",
      st_plan: "Choosing what to open", st_route: "Working out travel times", st_read: "Opening listings: {done} of {asked}",
      st_read_cache: " ({n} already read)", st_traffic: "Checking drive times", st_check: "Waiting for Yad2's check",
      st_cooldown: "Taking a short pause", st_done: "Done in {t}", st_last: "Last search {when}", st_idle: "Press Find listings to search.",
      st_suggest: "Looking for ways to find you more",
      // summary and sections
      n_matches: "{n} matches", n_match: "1 match", n_checked: "{n} listings checked", n_so_far: "{n} so far",
      matches_best: "Matches, best first", sort_by: "Sort", sort_match: "Best match", sort_price: "Lowest rent",
      sort_commute: "Shortest commute", sort_marked: "Recently marked",
      sec_rejected: "Rejected by you ({n})", sec_hidden: "Read, but not a fit ({n})", sec_skipped: "Didn't meet your must-haves ({n})", sec_skipped_see: "Each one, with its reason and a link: Your listings → Every listing → Not a fit.",
      sec_notopened: "Couldn't open these: have a look yourself ({n})", empty_now: "Nothing in your searches matches right now.",
      // cards
      fit_great: "Great match", fit_good: "Good match", fit_fair: "Fair match", fit_basic: "Meets your must-haves",
      fit_tip: "How well it fits what you'd like. Must-haves are already met.",
      rooms_n: "{n} rooms", floor_n: "Floor {n}", floor_maybe: "Floor {n}? (the site may mean the building's height: check)", ground: "Ground floor", m2: "{n} m²", agency: "Agency", new_badge: "New",
      what_it_has: "What it has", worth_asking: "Worth asking", heads_up: "Heads-up", why_hidden: "Why it's hidden",
      ask_about: "Ask about: {list}",
      fav: "Favorite", interested: "Interested", viewing: "Viewing scheduled", viewing_at: "Viewing {when}", reject: "Reject",
      rejected_undo: "Rejected · undo", viewing_when: "When is the viewing? (optional)", gone: "Not in the latest search: it may have been taken down.",
      read_ago: "read {t} ago", ago_min: "{n} min", ago_h: "{n} h",
      trip_car: "≈{u} min · up to {w} at rush hour", trip_car_est: "≈{u} min · up to {w} at rush hour (estimate)",
      trip_about: "about {n} min (estimate)", trip_traffic: "{n} min in typical traffic",
      tone_good: "Meets your preference", tone_weak: "Within your limit, not what you hoped for", tone_bad: "Fails a must-have", tone_info: "Mentioned in the listing",
      // topics
      t_rent: "rent", t_size: "size", t_rooms: "rooms", t_floor_ground: "ground floor", t_floor_high: "floor", t_parking: "parking",
      t_balcony: "a balcony", t_elevator: "an elevator", t_ac: "air conditioning", t_shelter: "a safe room or shelter",
      t_whole: "whether it's the whole apartment", t_movein: "the move-in date", t_renovated: "renovation", t_furniture: "furniture", t_photos: "photos", t_unit: "whether it's a unit in someone's home", t_lease: "how long the lease is",
      t_pets: "pets", t_accessible: "accessibility", t_commute: "the trip to {place}",
      T_rent: "Rent", T_size: "Size", T_rooms: "Rooms", T_floor: "Floor", T_parking: "Parking", T_balcony: "Balcony",
      T_elevator: "Elevator", T_ac: "Air conditioning", T_shelter: "Safe room or shelter", T_whole: "Whole apartment (no roommates)",
      T_movein: "Move-in date", T_renovated: "Renovated", T_furniture: "Furniture", T_photos: "Has photos", T_unit: "A home of its own (not a unit in someone's house)", T_lease: "Not a short stay", T_pets: "Pets allowed", T_accessible: "Accessible",
      T_commute: "{mode} to {place}",
      mode_ebike: "E-bike", mode_bike: "Bike", mode_walk: "Walk", mode_car: "Car",
      by_ebike: "by e-bike", by_bike: "by bike", by_walk: "on foot", by_car: "by car",
      // notes
      n_risk: "The listing doesn't mention {topic}, a must-have for you. About {pct}% of similar listings don't have it.",
      n_must_unstated: "The listing doesn't mention {topic}, a must-have for you. Ask before you visit.",
      n_unclear: "The listing isn't clear about {topic}. Ask.",
      n_verify: "Double-check {topic} in the listing.",
      n_companion: "Some rooms may only have a fan. Ask which have air conditioning.",
      n_needs_floor: "Floor {value} is fine only if there's an elevator. Ask.",
      n_needs: "Fine only if it has {needs}. Ask.",
      n_rent_over: "₪{over} over your ₪{limit} budget", n_rent_within_if: "; within budget if it has {needs}",
      n_size_under: "{value} m², smaller than your {limit} m²", n_rooms_under: "{value} rooms, fewer than your {limit}",
      n_commute_over: "{value} min {by}, more than your {limit} min", n_movein_late: "Available in {value} days, later than you'd like",
      n_floor_high: "Floor {value} with no elevator, higher than you'd like", n_floor_ground: "It's on the ground floor",
      n_parking_low: "Not the parking you'd like", n_generic: "{topic}: {value} (your limit {limit})",
      n_exception: "{text}. Kept as an exception.", n_no_whole: "It's a room in a shared apartment", n_no_unit: "It's a unit in someone's home", n_no_lease: "It's offered for a short stay", n_no: "No {topic}",
      // features
      f_ac: "Air conditioning", f_mamad: "Mamad", f_building_shelter: "Building shelter", f_balcony: "Balcony", f_no_balcony: "No balcony",
      f_elevator: "Elevator", f_no_elevator: "No elevator", f_parking_own: "Own parking", f_parking_building: "Building parking",
      f_parking_street: "Street parking", f_parking_none: "No parking", f_renovated: "Renovated", f_not_renovated: "Not renovated", f_no_photos: "No photos",
      f_pets: "Pets allowed", f_accessible: "Accessible", f_bars: "Window bars", f_room_share: "Room in a share", f_whole: "Whole apartment", f_housing_unit: "Unit in someone's home", f_short_lease: "Short stay", f_furniture_for_sale: "Furniture for sale (not included)",
      f_suits_roommates: "Suits roommates", f_garden: "Garden apartment", f_roof: "Rooftop", f_house: "House", f_studio: "Studio",
      f_available_now: "Available now", f_available_from: "Available from {date}",
      f_parking_any: "Parking (whose isn't said)", f_public_shelter: "Public shelter {m} m away",
      f_no_building_shelter: "No safe room or building shelter marked", f_agency_no_fee: "Agency listing, no broker fee",
      f_no_parking_space: "No parking space with it",
      // v1.54: every box on Yad2's form, and the furniture box when the text lists nothing
      f_floor_shelter: "Floor safe room (ממ\"ק)", f_solar_heater: "Solar water heater", f_tornado_ac: "Tornado A/C",
      f_storage: "Storage room", f_kosher_kitchen: "Kosher kitchen", f_maybe_furnished: "Might be furnished (box ticked, no items listed)", f_pandor_doors: "Pandor doors",
      f_item_sofa: "Sofa", f_item_bed: "Bed", f_item_table_chairs: "Table and chairs", f_item_cabinet: "Storage furniture",
      f_item_fridge: "Fridge", f_item_washer: "Washing machine", f_item_dryer: "Dryer", f_item_dishwasher: "Dishwasher",
      f_item_microwave: "Microwave", f_item_tv: "TV", f_item_closets: "Closets", f_item_oven_stove: "Oven and stove",
      f_item_says_furnished: "Furnished", f_item_says_partly_furnished: "Partly furnished", f_item_says_unfurnished: "Unfurnished",
      f_item_says_equipped: "Appliances",
      // why left out
      w_rent: "Rent", w_commute: "Too far", w_size: "Too small", w_rooms: "Too few rooms", w_floor_ground: "Ground floor",
      w_floor_high: "Too high without an elevator", w_parking: "Parking", w_movein: "Move-in date", w_shelter: "No safe room",
      w_whole: "Room share", w_unit: "Unit in someone's home", w_lease: "Short stay", w_ac: "No air conditioning", w_rejected: "Rejected by you", w_other: "Not a home, or no price",
      w_custom: "{label}",
      // suggestions
      m_hoods_unsure: "Yad2 didn't say which neighborhood its listings in {x} are in, so the whole city is shown. Pick its neighborhoods on the map again in Setup to keep it to them.",
      m_read_short: "Yad2 listed more than were read for: {x}. Some listings may be missing; Statistics shows each search.",
      ph_none: "No photos in this listing", ph_none_x: "The poster added none. Listings without photos are more often not what they seem: ask for some before a viewing.",
      ph_unread: "Photos weren't read", ph_unread_x: "The site didn't give them to us for this listing. Open it to see them.",
      drag_width: "Drag to make it wider or narrower",
      sg_line: "{k} ways to see up to {n} more listings", sg_line1: "One way to see {n} more listings",
      sg_title: "Want more options?", sg_count: "{n} more listings", sg_rent: "Raise your rent limit to ₪{to}",
      sg_commute: "Allow up to {to} min {by}", sg_size: "Accept {to} m² and up", sg_rooms: "Accept {to} rooms and up",
      sg_floor_ground: "Accept ground-floor apartments", sg_floor_high: "Accept up to floor {to} without an elevator",
      sg_movein: "Accept move-in within {to} days", sg_parking: "Accept listings without parking", sg_soften: "Make {topic} a nice-to-have",
      sg_saved: "Saved. Search again to see them.",
      // Yad2's check
      ck_title: "Yad2 wants to check you're a person",
      ck_text: "Complete the check in the Yad2 tab. When it's done, the search goes on by itself, a little slower. What was read is kept.",
      ck_again: "Yad2 asked a second time today, so searching pauses until tomorrow. Everything read so far is kept.",
      ck_soft: "Yad2 asked for a short pause.", ck_soft_stop: "Yad2 asked for a pause three times today, so searching pauses until tomorrow. Everything read so far is kept.",
      ck_solved: "Thanks! Going on in a few seconds.", ck_solved_title: "Thanks, the search goes on",
      ck_reload: "Yad2 asked us to slow down. Checking whether it wants its check…", ck_countdown: "{why} Going on in {n} s, a little slower.",
      ck_pause_title: "A short pause", ck_stopped_title: "Searching has stopped for today", ck_go: "Go to the check", ck_stop: "Stop the search",
      ck_never: "Rental Matcher never answers the check for you. This window closes by itself once it's done.", ck_done_short: "Check done.",
      // errors and messages
      e_not_installed: "The helper isn't set up on this computer yet: run install.bat in the project folder once.",
      e_helper_stopped: "The helper stopped ({why}).", e_generic: "Something went wrong: {detail}",
      e_running_here: "A search is already running.", e_running_other: "A search is already running in another Yad2 tab. It's in front now.",
      e_tab_closed: "The Yad2 tab was closed, so the search stopped. What was read is kept.",
      m_no_searches: "No searches set up yet. Open Setup and add a city.",
      m_pages_failed: "Some search pages couldn't be read; listings on them are missing from this search.",
      m_elsewhere: "Yad2 shows {x} on a separate site ({site}) that this version can't read yet, so Yad2's listings there are missing.",
      m_routes_failed: "Some travel times couldn't be worked out; those listings show an estimate.",
      m_stopped: "Stopped. What was read is below.", m_score_retry: "Scoring paused for a moment; it's tried again at the end.",
      // popup
      pp_intro: "Reads your searches and shows the listings that match.", pp_takes: "Takes about {t} ({what}).",
      pp_first: "the first search of the day", pp_repeat: "a repeat: listings read in the last day aren't opened again",
      pp_avg: "First search of the day ≈ {a}{am} · repeat ≈ {b}{bm}.", pp_yours: " (your average)", pp_est: " (estimate)",
      pp_done: "Done: {n} matches", pp_done1: "Done: 1 match", pp_done0: "Done",
      // results page
      rs_title: "Your listings", rs_tab_listings: "Listings", rs_tab_stats: "Statistics", rs_all: "All", rs_fav: "★ Favorites",
      rs_interested: "Interested", sx_btn: "📤 Share listings", sx_title_dlg: "Share listings", sx_x: "Share with someone who doesn't have the extension: a page that opens in any browser, phone included, or text to paste in WhatsApp or an email. Pick what to send:",
      sx_all: "Every listing that fits", sx_name: "Title", sx_title: "Apartments I'm looking at", sx_page: "Download a page to share", sx_text: "Copy as text",
      sx_system: "Share with an app…", sx_pick: "Pick at least one list.", sx_page_done: "Saved a page with {n} listings. Share the file like any other (WhatsApp, email).",
      sx_text_done: "Copied {n} listings. Paste them into a chat or an email.", sx_sub: "{n} listings · {when}",
      sx_building: "Preparing the page (fetching photos)…",
      sx_photo_note: "Some photos need an internet connection to show. If this page looks broken on a phone (WhatsApp or Messages often preview files without one), open it in a browser instead: tap Share (or the ••• menu), then \"Open in Safari\" or \"Open in Chrome\".",
      sx_footer: "Made with Rental Matcher. Rent, photos and details are the listings' own; check them on the site before you go.",
      sx_privacy: "It's made here and goes only to whoever you share it with.", rs_notopened: "Seen in the search, not opened ({n})", rs_notopened_x: "The search page alone showed these fail a must-have, so they weren't opened. Each one with its reason and a link: if one looks right to you, the reason says which setting to change.",
      fd_btn: "🔎 Missing a listing?", fd_title: "Missing a listing?", fd_x: "Paste the link of a listing you expected to see. This says what the last search did with it.", fd_go: "Check",
      fd_bad: "That isn't a Yad2, Komo or Madlan listing link.", fd_rejected: "You marked it \"Not for me\", so it isn't shown or opened.",
      fd_shown: "It's in your listings: #{n} in the order.", fd_hidden: "The search read it and hid it for:",
      fd_merged: "It's another post of an apartment that's already in your listings: it's linked from that card.",
      fd_skipped: "The search saw it but didn't open it, because the search page showed:", fd_unread: "The search tried to open it, but the page didn't load. The next search tries again.",
      fd_outside: "The search saw it, but Yad2 puts it in {hood}, which isn't one of the neighborhoods you chose.",
      fd_unseen: "The last search ({when}) didn't see it. It may be newer than the search, cost more than the search's price cap, or be in a city you don't search. What each search read:",
      fd_cover: "Yad2 listed {total}, read {seen}",
      cv_title: "What each search covered", cv_x: "Yad2's own count for each search, how many were read, and how many are in the neighborhoods you chose. A ⚠ means fewer were read than Yad2 listed.",
      cv_search: "Search", cv_total: "Yad2 listed", cv_seen: "Read", cv_kept: "In your neighborhoods", cv_failed: "{n} pages failed",
      rooms_short: "rooms", floor_short: "floor", rs_photoless: "{n} listings with no photos are left out (Setup → Hide listings with no photos).", rs_viewing: "Viewing scheduled", rs_rejected: "Rejected", rs_hidden: "Not a fit",
      rs_filter: "Filter by street or city", rs_last: "Last search {when} · {n} listings in your searches", rs_viewings: "Upcoming viewings",
      rs_no_date: "Date not set", rs_empty: "Nothing here yet.", rs_none: "No search yet: press Find listings.",
      // statistics
      ss_checked: "Listings checked", ss_matches: "Matches", ss_new: "New in the last search", ss_rent: "Average rent of your matches",
      ss_commute: "Average trip to {place}", ss_favs: "Favorites", ss_viewings: "Viewings", ss_week: "Searches this week",
      ss_first: "Typical first search", ss_repeat: "Typical repeat search", ss_saved: "Time saved",
      ss_saved_note: "Reading these listings one by one would take about {t} (estimate).", ss_recent: "Recent searches",
      ss_when: "When", ss_took: "Took", ss_listings: "Listings", ss_opened: "Opened", ss_result: "Result",
      ss_complete: "Complete", ss_stopped: "Stopped", ss_kind_first: "First of the day", ss_kind_repeat: "Repeat",
      ss_label_title: "Help it read listings better", ss_label_x: "The listings your searches read, as a file: their text and the site's own facts, no names or phone numbers. Labeled by hand, they show where the reading rules go wrong.",
      ss_label_dl: "Download the listings read ({n})",
      ss_log: "Connection log", ss_log_empty: "Nothing to report: Yad2 hasn't asked us to slow down.",
      lg_pushback: "Yad2 asked us to slow down on a {what}; the search slowed down", lg_what_search: "search page", lg_what_listing: "listing",
      lg_check: "Yad2 showed its check", lg_check_again: "Yad2 showed its check a second time today; searching paused until tomorrow",
      lg_nocheck: "No check was needed; the search went on after a short pause", lg_solved: "Check completed; the search went on",
      // setup
      su_title: "Setup", su_where: "Where to look", su_where_lead: "The cities, or just the neighborhoods, to search on Yad2.",
      su_city_ph: "Add a city: type its name", su_none: "No cities yet.", su_whole_city: "Whole city", su_pick_hoods: "Choose neighborhoods",
      su_tlv_no_jaffa: "Tel Aviv without Jaffa", su_jaffa: "Jaffa", su_hoods_loading: "Loading neighborhoods…",
      su_hoods_failed: "Neighborhoods couldn't be loaded; the whole city will be searched.", su_hoods_n: "{n} neighborhoods",
      su_added: "Added {x}.", su_already: "{x} is already there.", su_pick_city: "Pick a city from the list as you type.",
      su_finding: "Finding {x} on Yad2…", su_link: "Or paste a Yad2 search link", su_link_name: "Its name", su_link_bad: "That isn't a Yad2 rentals search. Open the search on Yad2 and copy the address bar.",
      su_not_link: "That isn't a link.", su_my_search: "My search", su_hood_filter: "Search", su_select_all: "Select all", su_select_none: "Clear",
      su_places: "Places you go to", su_places_lead: "Work, studies, family: each place gets its own travel time on every listing.",
      su_place: "Place", su_name: "Name", su_name_ph: "e.g. Work", su_address: "Address", su_address_ph: "e.g. Dizengoff 50, Tel Aviv", su_find: "Find",
      su_by: "Getting there by", su_speed: "Your speed (km/h)", su_usual: "{n} (usual)", su_time: "Time of day", su_rush: "Rush hour",
      su_offpeak: "Off-peak", su_full_marks: "Perfect if up to (min)", su_at_most: "Longest you'd accept (min)", su_looking: "Looking…",
      su_nothing: "Nothing found. Try the street and city.", su_from: "From {src}.", su_find_first: "Find the address to place it on the map.",
      su_add_place: "+ Add a place", su_no_places: "No places yet.", su_lookup_failed: "The lookup didn't work.",
      su_basics: "Budget and the apartment", su_basics_lead: "A must-have hides listings that fail it. Everything else counts toward the match.",
      su_features: "Features", su_features_lead: "What the apartment should have.", su_add_pref: "Add a preference…",
      su_must: "Must-have", su_must_on: "Must-have: listings without it are hidden", su_counts: "How important",
      su_rent_ideal: "Ideal rent (₪)", su_rent_limit: "Most you'd pay (₪)", su_rent_tol: "Negotiable up to +₪", su_none_ph: "none",
      su_size_min: "At least (m²)", su_size_ideal: "Ideal (m²)", su_rooms_min: "At least (rooms)", su_floor: "Floor", su_floor_ground: "Ground floor is OK",
      su_floor_max: "Highest floor without an elevator", su_floor_elev: "With an elevator, any floor is fine",
      su_movein: "Move-in date", su_movein_ideal: "Ideally", su_movein_latest: "At the latest",
      mv_0: "As soon as possible", mv_14: "Within 2 weeks", mv_30: "Within a month", mv_45: "Within 6 weeks", mv_60: "Within 2 months",
      mv_90: "Within 3 months", mv_180: "Within 6 months",
      pk_3: "Own parking", pk_2: "Building parking", pk_1: "Street parking", pk_0: "None needed", su_pk_ideal: "Ideal", su_pk_min: "Lowest acceptable",
      su_ideal: "Ideal", su_limit: "Limit", su_tol: "Tolerance", su_items: "Wanted items",
      su_saved_hint: "Changes count from the next search.", su_unsaved: "Unsaved changes.", su_undo: "Undo changes",
      su_saving: "Saving…", su_saved: "Saved. The next search uses it.", su_nothing_changed: "Nothing changed.", su_not_saved: "Not saved: {e}",
      su_find_addr_first: "Find the address of {x} first.", su_no_helper: "The helper didn't answer: run install.bat in the project folder once.",
      // tour
      // v1.27: other sites
      site_yad2: "Yad2", site_komo: "Komo", site_madlan: "Madlan", site_facebook: "Facebook", fb_keep: "Keep this rental post (Rental Matcher)", fb_title: "Rental Matcher", fb_kept: "Kept this post for your next search", fb_too_short: "Select the post's text first, then choose Keep this rental post", fb_no_price: "No rent found in the selected text: select the whole post, including the price", open_on: "Open on {site}", also_on: "Also on {site}", also_post: "Another post on {site}", maybe_same: "Possibly the same apartment on {site} ({what}): the sites disagree, check before you call", maybe_floor: "floor {there} there, {here} here", maybe_size: "{there} m² there, {here} m² here",
      approx_place: "Neighborhood only",
      approx_tip: "{site} doesn't give the exact address, so travel times are estimated from the middle of the neighborhood.",
      st_sites: "Looking on other sites", st_sites_x: "Looking on Komo: {x}",
      m_komo_wall: "Komo asked to sign in, so only its first page was read. Listings you open on Komo yourself are still added.",
      m_komo_pushback: "Komo asked us to slow down, so we stopped reading it for this search. Yad2 wasn't affected.",
      ss_sources: "Where the matches came from", ss_from: "From {site}",
      su_sites: "Other sites", su_show: "What to show", su_nophotos: "Hide listings with no photos", su_nophotos_x: "On by default. A listing on Yad2 or Madlan with no photos is left out of your listings, the panel and Teach it your taste. Komo's photos sometimes can't be read, so those stay.", su_sites_lead: "Besides Yad2, listings can come from:",
      su_komo_x: "Its newest listings in your cities are read with every search (the first page, which anyone can see; the rest need a Komo account). Komo listings you open yourself are added too.",
      su_madlan_x: "Madlan blocks automatic reading, so only what you see on Madlan yourself is added: open a Madlan search or listing page, and it's kept for your next search for 3 days.",
      cap_kept: "Rental Matcher kept {n} listings for your next search", cap_kept1: "Rental Matcher kept this listing for your next search",
      // v1.30: settings in plain words
      su_must_hint: "Hide listings without it", su_imp_better: "How much a better one counts", su_imp_lo: "A little", su_imp_hi: "A lot",
      imp_1: "A little", imp_2: "A little", imp_3: "Somewhat", imp_4: "Somewhat", imp_5: "Important", imp_6: "Important",
      imp_7: "Very important", imp_8: "Very important", imp_9: "Top priority", imp_10: "Top priority", imp_of: "{n} of 10 · {w}",
      su_budget: "Your budget", su_budget_from: "From", su_budget_to: "Up to", su_budget_none: "no minimum",
      su_rent_perfect: "Perfect price: up to ₪", su_over_ok: "Also show listings a little over budget, marked \"over budget\"",
      su_over_up_to: "up to +₪", su_worth: "Worth paying more for", su_worth_lead: "You'd go over your budget for these. Pick a feature and how much more.",
      su_worth_add: "+ Add something worth more", su_worth_more: "up to +₪", su_effect: "What this does",
      ef_hide_without: "Listings without it are hidden. If a listing doesn't say, it's shown with a reminder to ask.",
      ef_rank_with: "Listings with it rank higher.",
      ef_commute_must: "Up to {ideal} min is perfect; longer trips rank lower, and over {limit} min is hidden.",
      ef_commute_soft: "Up to {ideal} min is perfect; longer trips rank lower, down to nothing at {limit} min.",
      ef_commute_line: "Over {limit} min is hidden.",
      ef_rent: "{ideal} or less is perfect; up to {max} ranks a bit lower.", ef_rent_hide: " Over {hide} is hidden.",
      ef_rent_soft: " Over {max} ranks lower but still shows.", ef_rent_min: " Under {min} is hidden.",
      ef_rent_tol: " Between {max} and {hide} shows, marked over budget.", ef_rent_worth: " With {what}: up to {to}.",
      ef_min_must: "Under {limit} is hidden.", ef_min_soft: "Under {limit} ranks lower.",
      ef_size_must: "Smaller than {limit} m² is hidden.", ef_size_ideal: "Bigger ranks higher, up to {ideal} m².", ef_size_soft: "Smaller than {limit} m² ranks lower.",
      ef_rooms_must: "Fewer than {limit} rooms is hidden.", ef_rooms_soft: "Fewer than {limit} rooms ranks lower.",
      ef_ground_hidden: "Ground-floor apartments are hidden.", ef_ground_ok: "Ground-floor apartments are fine.",
      ef_high: "Above floor {limit} with no elevator is hidden.", ef_high_elev: " With an elevator, any floor is fine.",
      ef_movein_must: "Ready {ideal} is perfect; later ranks lower, and more than {limit} days away is hidden.",
      ef_movein_soft: "Ready {ideal} is perfect; later ranks lower.", ef_now: "now", ef_within: "within {n} days",
      ef_line_soft: "Over {limit} ranks lower.", ef_line_must: "Over {limit} is hidden.",
      ef_parking_must: "{ideal} is best; anything less than {limit} is hidden.", ef_parking_soft: "{ideal} is best; less ranks lower.",
      ef_items: "Listings that include these rank higher.",
      T_rent_min: "Minimum rent", t_rent_min: "the minimum rent", w_rent_min: "Cheaper than your minimum",
      n_rent_min: "₪{value}, under your ₪{limit} minimum", sg_rent_min: "Lower your minimum rent to ₪{to}",
      // v1.30: the quick setup
      su_quick: "Quick setup", wz_title: "Quick setup", wz_skip: "Skip, I'll set it up myself", wz_later: "Skip this",
      wz_hi: "Let's find your next home", wz_hi_x: "Answer a few quick questions and Rental Matcher will read the listings for you, keep the ones that fit, and show the best first. About two minutes. You can change anything later in Settings.",
      wz_start: "Let's start", wz_where: "Where would you like to live?", wz_where_x: "Type a city and pick it from the list. Add as many as you like.",
      wz_where_hint: "Want only some neighborhoods? You can choose them later in Settings.",
      wz_budget: "What's your monthly budget?", wz_budget_x: "Drag the two handles. Listings outside this range won't be shown.",
      wz_budget_hint: "The low end hides listings too cheap to be what you're looking for, like single rooms. Leave it at ₪0 for no minimum.",
      wz_rooms: "How many rooms, at least?", wz_rooms_x: "Listings with fewer rooms won't be shown.", wz_any: "Any",
      wz_place: "Where do you go most days?", wz_place_x: "Work, studies, family. Every listing will show how long the trip takes.",
      wz_place_name: "For example: Work", wz_place_what: "What is it?", wz_place_how: "How do you get there?", wz_place_max: "Longest trip you'd accept",
      wz_place_find: "Find the address first, or press Skip this.",
      wz_needs: "What can't you live without?", wz_needs_x: "Tap once for a must-have, twice for nice-to-have, a third time to clear.",
      wz_must: "Must-have", wz_must_x: "listings without it are hidden", wz_nice: "Nice to have", wz_nice_x: "ranks listings with it higher",
      wz_needs_hint: "If a listing doesn't say, it isn't hidden: you'll see it with a reminder to ask.",
      wz_n_mamad: "Safe room or shelter", wz_n_no_roommates: "Whole apartment", wz_n_air_conditioning: "Air conditioning", wz_n_parking: "Parking",
      wz_n_balcony: "Balcony", wz_n_elevator: "Elevator", wz_n_not_ground_floor: "Not ground floor", wz_n_pets_allowed: "Pets allowed", wz_n_renovated: "Renovated",
      wz_done: "Here's your search", wz_done_x: "Check it over, then save. You can change any of it later in Settings.",
      wz_s_where: "Where", wz_s_budget: "Budget", wz_s_rooms: "Rooms", wz_s_place: "Trip",
      wz_keeps: "This changes only what you answered here. Everything else in your settings stays as it was.",
      wz_save: "Save", wz_ready: "All set!", wz_ready_x: "Press Find listings to search now. Next time, click the Rental Matcher icon in your browser's toolbar and press Find listings.",
      wz_settings: "Fine-tune in Settings", wz_find: "Find listings",
      b_drop: "{n} cheaper", b_drop_tip: "Was {was}, now {now}", b_deal: "Good deal",
      b_deal_tip_hood: "{n} below the usual rent for {rooms} rooms in {place} ({count} listings)",
      b_deal_tip_city: "{n} below the usual rent for {rooms} rooms in {place} ({count} listings)",
      // v1.31: photos, the simple card, the detailed card's numbers
      no_photos: "No photos", photo_n: "Photo {n} of {of}", photo_prev: "Previous photo", photo_next: "Next photo",
      save_listing: "Save", saved: "Saved", not_for_me: "Not for me", more_actions: "More", details_show: "All details", details_hide: "Simple view",
      to_place: "to {place}", view_simple: "Simple", view_detailed: "Detailed", view_label: "Cards",
      k_numbers: "The numbers", k_match: "Expected match", k_likely: "Likely range", k_range: "Full range (all unknowns either way)",
      k_risk: "Chance a must-have fails", k_per_m2: "Rent per m²", k_listed: "Listed by", k_agency: "An agency", k_private: "The owner",
      k_photos: "Photos", k_source: "Source · ID", k_usual: "Usual rent nearby (listings)", k_read: "Read", k_engine: "The engine's own notes ({n})",
      su_all_saved: "All changes saved ✓", su_whole_now: "The whole area is searched. Click neighborhoods on the map to keep to them.",
      su_pruned: "{n} listings from places you no longer search were removed.",
      su_all_of: "All of {x}", su_link: "From a Yad2 link", su_n_hoods: "{n} neighborhoods", su_and_more: "and {n} more", su_edit_map: "Edit on the map",
      su_save_place: "Save these neighborhoods", su_saved_place: "Saved {x}'s neighborhoods.", su_pick_some: "Pick at least one neighborhood, or choose the whole city.",
      su_map_none: "None picked yet: click the neighborhoods on the map.",
      su_pick_hoods_map: "Pick neighborhoods on the map", su_map_picked: "{n} picked",
      su_map_note: "Click the neighborhoods you'd live in; click again to drop one. Drag to move, scroll to zoom. The outlines are drawn from Yad2's neighborhood centers, so they're close, not exact.",
      rs_shelves: "Shelves", rs_grid: "Grid",
      // v1.32: tune the ranking by picking between two
      cp_title: "Which would you rather live in?", cp_tune: "🎯 Teach it your taste",
      cp_lead: "Pick the one you'd rather live in. After a few picks, the ranking's weights are checked against your choices.",
      cp_lead_x: "The pairs are ones the ranking finds close but that differ in what they have, so each pick teaches it the most.",
      cp_count: "{n} picks · this round {r} of {of}", cp_result: "See what it learned", cp_need: "{n} more picks first",
      cp_this: "This one", cp_locked: "must-have", cp_locked_x: "🔒 Must-haves are locked: their weights are never suggested or changed here. Change them on the setup page.", cp_or: "or", cp_same: "Can't decide", cp_neither: "Neither", cp_neither_x: "You wouldn't live in either. Nothing is hidden or rejected: it teaches the ranking that both come after the ones you do pick.", cp_none: "Search first: there are no listings to compare yet.",
      cp_all_asked: "You've compared every pair worth asking about. Search again for new ones.", cp_round_done: "That's a round.", cp_more: "Keep going",
      cp_working: "Fitting the weights to your picks…", cp_report_title: "What {n} picks say",
      cp_explain: "How often the ranking puts the one you picked first. \"Held out\" checks each pick with weights fit without it, so it's the honest number.",
      cp_before: "Your weights now", cp_held: "Suggested, on picks it didn't see", cp_after: "Suggested, on all your picks",
      cp_crit: "What counts", cp_now: "Now", cp_new: "Suggested", cp_apply: "Use the suggested weights",
      cp_applied: "Saved. The next search ranks with them (your old file is backed up).",
      cp_keep: "Your current weights already agree with your picks as well as anything it found, so nothing to change.",
      // v1.32: the results page's views, named by what they do
      rs_picks: "✨ Picks for you", rs_picks_x: "Grouped: deals, new, nearest…", rs_every: "▦ Every listing", rs_every_x: "One list to filter and sort",
      rs_stats_v: "📊 Statistics", rs_stats_x: "What the searches found", rs_filters: "Filters", rs_filters_n: "Filters ({n})", rs_up_to: "Up to", rs_within_min: "Within {n} min", rs_parking: "Parking", rs_with_photos: "With photos",
      sh_new: "New since your last search", sh_new_x: "Listed since you last looked.", sh_drop: "Price dropped", sh_drop_x: "Cheaper than when a search first saw them.",
      sh_deal: "Good deals", sh_deal_x: "Clearly under the usual rent for the same rooms nearby.", sh_saved: "Saved", sh_saved_x: "The ones you hearted.",
      sh_best: "Best for you", sh_best_x: "The closest to everything you asked for.", sh_near: "Closest to {place}", sh_near_any: "Shortest trip",
      sh_near_x: "The shortest trip first.", sh_cheap: "Cheapest", sh_cheap_x: "The lowest rent first.", sh_all: "See all ({n})", sh_back: "All shelves",
      cheaper_on: "{n} less on {site}",
      cost_vaad: "Building fee {n}", cost_vaad_in: "No separate building fee", cost_arnona: "Arnona {n}", cost_arnona_in: "No separate arnona",
      cost_total: "Total a month {n}",
    },

    he: {
      app: "Rental Matcher", close: "סגירה", save: "שמירה", undo: "ביטול", apply: "החלה", remove: "הסרה", add: "הוספה",
      cancel: "ביטול", next: "הבא", back: "הקודם", done: "סיום", language: "שפה",
      pull: "חיפוש מודעות", stop: "עצירה", wider: "הרחבה", narrower: "צמצום", all_listings: "כל המודעות", setup: "הגדרות",
      show_panel: "הצגת החלונית", your_listings: "המודעות שלך", open_yad2: "פתיחה ביד2", a_month: "לחודש",
      sec: "{n} שנ'", min_sec: "{m} דק' {s} שנ'", min: "{n} דק'", h_min: "{h} שע' {m} דק'",
      left_less: "פחות מדקה", left_about: "עוד כ-{n} דק'",
      st_starting: "מתכוננים", st_search: "קוראים את החיפושים שלך", st_search_x: "קוראים את החיפושים שלך: {x}",
      st_plan: "בוחרים מה לפתוח", st_route: "מחשבים זמני הגעה", st_read: "פותחים מודעות: {done} מתוך {asked}",
      st_read_cache: " ({n} כבר נקראו)", st_traffic: "בודקים זמני נסיעה ברכב", st_check: "ממתינים לבדיקה של יד2",
      st_cooldown: "הפסקה קצרה", st_done: "הסתיים תוך {t}", st_last: "חיפוש אחרון: {when}", st_idle: "לחצו על חיפוש מודעות כדי להתחיל.",
      st_suggest: "מחפשים דרכים למצוא לך עוד",
      n_matches: "{n} התאמות", n_match: "התאמה אחת", n_checked: "{n} מודעות נבדקו", n_so_far: "{n} עד עכשיו",
      matches_best: "ההתאמות, הטובות ביותר קודם", sort_by: "מיון", sort_match: "ההתאמה הטובה ביותר", sort_price: "שכר דירה נמוך",
      sort_commute: "הגעה מהירה", sort_marked: "סומנו לאחרונה",
      sec_rejected: "מודעות שדחית ({n})", sec_hidden: "נקראו אבל לא מתאימות ({n})", sec_skipped: "לא עמדו בדרישות החובה ({n})", sec_skipped_see: "כל אחת עם הסיבה וקישור: המודעות שלך ← כל המודעות ← לא מתאימות.",
      sec_notopened: "לא הצלחנו לפתוח, כדאי להציץ בעצמכם ({n})", empty_now: "כרגע אין בחיפושים שלך מודעות שמתאימות.",
      fit_great: "התאמה מצוינת", fit_good: "התאמה טובה", fit_fair: "התאמה סבירה", fit_basic: "עונה על דרישות החובה",
      fit_tip: "עד כמה הדירה מתאימה למה שרציתם. דרישות החובה כבר מתקיימות.",
      rooms_n: "{n} חד'", floor_n: "קומה {n}", floor_maybe: "קומה {n}? (ייתכן שזה גובה הבניין: כדאי לבדוק)", ground: "קומת קרקע", m2: "{n} מ\"ר", agency: "תיווך", new_badge: "חדש",
      what_it_has: "מה יש בה", worth_asking: "כדאי לברר", heads_up: "שימו לב", why_hidden: "למה היא לא מתאימה",
      ask_about: "כדאי לשאול על: {list}",
      fav: "מועדף", interested: "מעניין אותי", viewing: "נקבעה צפייה", viewing_at: "צפייה {when}", reject: "לא מתאים",
      rejected_undo: "נדחתה · ביטול", viewing_when: "מתי הצפייה? (לא חובה)", gone: "לא הופיעה בחיפוש האחרון: ייתכן שהמודעה הוסרה.",
      read_ago: "נקראה לפני {t}", ago_min: "{n} דק'", ago_h: "{n} שע'",
      trip_car: "≈{u} דק' · עד {w} בשעת עומס", trip_car_est: "≈{u} דק' · עד {w} בשעת עומס (הערכה)",
      trip_about: "כ-{n} דק' (הערכה)", trip_traffic: "{n} דק' בתנועה רגילה",
      tone_good: "עונה על ההעדפה שלך", tone_weak: "בתוך הגבול, אבל לא מה שקיוויתם", tone_bad: "לא עומד בדרישת חובה", tone_info: "מצוין במודעה",
      t_rent: "שכר הדירה", t_size: "הגודל", t_rooms: "מספר החדרים", t_floor_ground: "קומת הקרקע", t_floor_high: "הקומה", t_parking: "חניה",
      t_balcony: "מרפסת", t_elevator: "מעלית", t_ac: "מיזוג אוויר", t_shelter: "ממ\"ד או מקלט",
      t_whole: "אם זו דירה שלמה", t_movein: "תאריך הכניסה", t_renovated: "שיפוץ", t_furniture: "ריהוט", t_photos: "תמונות", t_unit: "אם זו יחידה בבית של מישהו", t_lease: "משך השכירות",
      t_pets: "בעלי חיים", t_accessible: "נגישות", t_commute: "הדרך ל{place}",
      T_rent: "שכר דירה", T_size: "גודל", T_rooms: "חדרים", T_floor: "קומה", T_parking: "חניה", T_balcony: "מרפסת",
      T_elevator: "מעלית", T_ac: "מיזוג אוויר", T_shelter: "ממ\"ד או מקלט", T_whole: "דירה שלמה (בלי שותפים)",
      T_movein: "תאריך כניסה", T_renovated: "משופצת", T_furniture: "ריהוט", T_photos: "יש תמונות", T_unit: "דירה עצמאית (לא יחידה בבית של מישהו)", T_lease: "לא לתקופה קצרה", T_pets: "מותר בעלי חיים", T_accessible: "נגישה",
      T_commute: "{mode} עד {place}",
      mode_ebike: "אופניים חשמליים", mode_bike: "אופניים", mode_walk: "הליכה", mode_car: "רכב",
      by_ebike: "באופניים חשמליים", by_bike: "באופניים", by_walk: "ברגל", by_car: "ברכב",
      n_risk: "המודעה לא מציינת {topic}, וזו דרישת חובה שלך. לכ-{pct}% ממודעות דומות אין את זה.",
      n_must_unstated: "המודעה לא מציינת {topic}, וזו דרישת חובה שלך. כדאי לברר לפני שהולכים לראות.",
      n_unclear: "המודעה לא ברורה לגבי {topic}. כדאי לברר.",
      n_verify: "כדאי לבדוק שוב במודעה את {topic}.",
      n_companion: "ייתכן שבחלק מהחדרים יש רק מאוורר. כדאי לשאול באילו יש מזגן.",
      n_needs_floor: "קומה {value} מתאימה רק אם יש מעלית. כדאי לברר.",
      n_needs: "מתאים רק אם יש {needs}. כדאי לברר.",
      n_rent_over: "{over} ₪ מעל התקציב שלך ({limit} ₪)", n_rent_within_if: "; בתוך התקציב אם יש {needs}",
      n_size_under: "{value} מ\"ר, קטנה מה-{limit} מ\"ר שרציתם", n_rooms_under: "{value} חדרים, פחות מ-{limit}",
      n_commute_over: "{value} דק' {by}, יותר מה-{limit} דק' שהגדרתם", n_movein_late: "פנויה בעוד {value} ימים, מאוחר ממה שרציתם",
      n_floor_high: "קומה {value} בלי מעלית, גבוה ממה שרציתם", n_floor_ground: "הדירה בקומת קרקע",
      n_parking_low: "החניה לא כמו שרציתם", n_generic: "{topic}: {value} (הגבול שלך {limit})",
      n_exception: "{text}. נשארת כחריג.", n_no_whole: "זה חדר בדירת שותפים", n_no_unit: "זו יחידה בבית של מישהו", n_no_lease: "מוצעת לתקופה קצרה", n_no: "אין {topic}",
      f_ac: "מיזוג", f_mamad: "ממ\"ד", f_building_shelter: "מקלט בבניין", f_balcony: "מרפסת", f_no_balcony: "אין מרפסת",
      f_elevator: "מעלית", f_no_elevator: "אין מעלית", f_parking_own: "חניה פרטית", f_parking_building: "חניה בבניין",
      f_parking_street: "חניה ברחוב", f_parking_none: "אין חניה", f_renovated: "משופצת", f_not_renovated: "לא משופצת", f_no_photos: "בלי תמונות",
      f_pets: "מותר בעלי חיים", f_accessible: "נגישה", f_bars: "סורגים", f_room_share: "חדר בדירת שותפים", f_whole: "דירה שלמה", f_housing_unit: "יחידה בבית של מישהו", f_short_lease: "לתקופה קצרה", f_furniture_for_sale: "ריהוט למכירה (לא כלול)",
      f_suits_roommates: "מתאימה לשותפים", f_garden: "דירת גן", f_roof: "דירת גג", f_house: "בית פרטי", f_studio: "סטודיו",
      f_available_now: "פנויה מיד", f_available_from: "פנויה מ-{date}",
      f_parking_any: "חניה (לא נאמר של מי)", f_public_shelter: "מקלט ציבורי במרחק {m} מ'",
      f_no_building_shelter: "לא סומן ממ\"ד או מקלט בבניין", f_agency_no_fee: "מודעת תיווך, בלי דמי תיווך",
      f_no_parking_space: "אין חניה צמודה לדירה",
      f_floor_shelter: "ממ\"ק", f_solar_heater: "דוד שמש", f_tornado_ac: "מזגן טורנדו",
      f_storage: "מחסן", f_kosher_kitchen: "מטבח כשר", f_maybe_furnished: "אולי מרוהטת (סומן ריהוט, בלי פירוט)", f_pandor_doors: "דלתות פנדור",
      f_item_sofa: "ספה", f_item_bed: "מיטה", f_item_table_chairs: "שולחן וכיסאות", f_item_cabinet: "רהיט אחסון",
      f_item_fridge: "מקרר", f_item_washer: "מכונת כביסה", f_item_dryer: "מייבש", f_item_dishwasher: "מדיח כלים",
      f_item_microwave: "מיקרוגל", f_item_tv: "טלוויזיה", f_item_closets: "ארונות", f_item_oven_stove: "תנור וכיריים",
      f_item_says_furnished: "מרוהטת", f_item_says_partly_furnished: "מרוהטת חלקית", f_item_says_unfurnished: "לא מרוהטת",
      f_item_says_equipped: "מאובזרת",
      w_rent: "שכר דירה", w_commute: "רחוק מדי", w_size: "קטנה מדי", w_rooms: "מעט מדי חדרים", w_floor_ground: "קומת קרקע",
      w_floor_high: "גבוהה מדי בלי מעלית", w_parking: "חניה", w_movein: "תאריך כניסה", w_shelter: "אין ממ\"ד או מקלט",
      w_whole: "דירת שותפים", w_unit: "יחידה בבית של מישהו", w_lease: "לתקופה קצרה", w_ac: "אין מיזוג", w_rejected: "דחית", w_other: "לא דירה, או בלי מחיר",
      w_custom: "{label}",
      m_hoods_unsure: "יד2 לא ציינה באיזו שכונה נמצאות המודעות ב{x}, אז מוצגת כל העיר. בחרו שוב את השכונות על המפה בהגדרות כדי להישאר בהן.",
      m_read_short: "ביד2 הוצגו יותר מודעות ממה שנקרא בחיפושים: {x}. ייתכן שחסרות מודעות; בסטטיסטיקה רואים כל חיפוש.",
      ph_none: "אין תמונות במודעה", ph_none_x: "המפרסם לא העלה תמונות. מודעות בלי תמונות הן לעתים קרובות יותר לא מה שהן נראות: בקשו תמונות לפני שהולכים לראות.",
      ph_unread: "התמונות לא נקראו", ph_unread_x: "האתר לא מסר לנו אותן למודעה הזו. פתחו אותה כדי לראות.",
      drag_width: "גררו כדי להרחיב או לצמצם",
      sg_line: "{k} דרכים לראות עד {n} מודעות נוספות", sg_line1: "דרך אחת לראות עוד {n} מודעות",
      sg_title: "רוצים יותר אפשרויות?", sg_count: "עוד {n} מודעות", sg_rent: "להעלות את תקרת שכר הדירה ל-{to} ₪",
      sg_commute: "לאפשר עד {to} דק' {by}", sg_size: "לקבל דירות מ-{to} מ\"ר", sg_rooms: "לקבל גם {to} חדרים ומעלה",
      sg_floor_ground: "לקבל גם דירות בקומת קרקע", sg_floor_high: "לקבל עד קומה {to} בלי מעלית",
      sg_movein: "לקבל כניסה בתוך {to} ימים", sg_parking: "לקבל גם דירות בלי חניה", sg_soften: "להפוך את {topic} לרצוי במקום חובה",
      sg_saved: "נשמר. חפשו שוב כדי לראות אותן.",
      ck_title: "יד2 רוצה לוודא שאתם לא רובוט",
      ck_text: "השלימו את הבדיקה בלשונית של יד2. אחרי זה החיפוש ימשיך לבד, קצת יותר לאט. מה שכבר נקרא נשמר.",
      ck_again: "יד2 ביקשה בדיקה בפעם השנייה היום, ולכן החיפוש נעצר עד מחר. כל מה שנקרא עד עכשיו נשמר.",
      ck_soft: "יד2 ביקשה הפסקה קצרה.", ck_soft_stop: "יד2 ביקשה הפסקה שלוש פעמים היום, ולכן החיפוש נעצר עד מחר. כל מה שנקרא עד עכשיו נשמר.",
      ck_solved: "תודה! ממשיכים בעוד כמה שניות.", ck_solved_title: "תודה, החיפוש ממשיך",
      ck_reload: "יד2 ביקשה להאט. בודקים אם היא רוצה בדיקה…", ck_countdown: "{why} ממשיכים בעוד {n} שנ', קצת יותר לאט.",
      ck_pause_title: "הפסקה קצרה", ck_stopped_title: "החיפוש נעצר להיום", ck_go: "מעבר לבדיקה", ck_stop: "עצירת החיפוש",
      ck_never: "Rental Matcher אף פעם לא עונה על הבדיקה במקומכם. החלון ייסגר לבד כשהבדיקה תסתיים.", ck_done_short: "הבדיקה הושלמה.",
      e_not_installed: "הרכיב המקומי עוד לא מותקן במחשב הזה: הפעילו פעם אחת את install.bat שבתיקיית הפרויקט.",
      e_helper_stopped: "הרכיב המקומי נעצר ({why}).", e_generic: "משהו השתבש: {detail}",
      e_running_here: "חיפוש כבר רץ.", e_running_other: "חיפוש כבר רץ בלשונית אחרת של יד2. היא מוצגת עכשיו.",
      e_tab_closed: "הלשונית של יד2 נסגרה, ולכן החיפוש נעצר. מה שנקרא נשמר.",
      m_no_searches: "עוד לא הוגדרו חיפושים. פתחו את ההגדרות והוסיפו עיר.",
      m_pages_failed: "חלק מעמודי החיפוש לא נקראו, והמודעות שבהם חסרות בחיפוש הזה.",
      m_elsewhere: "יד2 מציגה את {x} באתר נפרד ({site}) שהגרסה הזו עדיין לא יודעת לקרוא, ולכן המודעות של יד2 שם חסרות.",
      m_routes_failed: "חלק מזמני ההגעה לא חושבו, ובמודעות האלה מוצגת הערכה.",
      m_stopped: "נעצר. מה שנקרא מופיע למטה.", m_score_retry: "הדירוג נעצר לרגע וינסה שוב בסוף.",
      pp_intro: "קורא את החיפושים שלך ומציג את המודעות שמתאימות.", pp_takes: "לוקח בערך {t} ({what}).",
      pp_first: "החיפוש הראשון היום", pp_repeat: "חיפוש חוזר: מודעות שנקראו ביממה האחרונה לא נפתחות שוב",
      pp_avg: "חיפוש ראשון ביום ≈ {a}{am} · חיפוש חוזר ≈ {b}{bm}.", pp_yours: " (הממוצע שלך)", pp_est: " (הערכה)",
      pp_done: "הסתיים: {n} התאמות", pp_done1: "הסתיים: התאמה אחת", pp_done0: "הסתיים",
      rs_title: "המודעות שלך", rs_tab_listings: "מודעות", rs_tab_stats: "סטטיסטיקה", rs_all: "הכל", rs_fav: "★ מועדפים",
      rs_interested: "מעניינות אותי", sx_btn: "📤 שיתוף מודעות", sx_title_dlg: "שיתוף מודעות", sx_x: "שיתוף עם מי שאין לו את התוסף: דף שנפתח בכל דפדפן, גם בטלפון, או טקסט להדבקה בוואטסאפ או במייל. מה לשלוח:",
      sx_all: "כל המודעות שמתאימות", sx_name: "כותרת", sx_title: "דירות שאני בודק", sx_page: "הורדת דף לשיתוף", sx_text: "העתקה כטקסט",
      sx_system: "שיתוף דרך אפליקציה…", sx_pick: "בחרו לפחות רשימה אחת.", sx_page_done: "נשמר דף עם {n} מודעות. שתפו את הקובץ כמו כל קובץ (וואטסאפ, מייל).",
      sx_text_done: "הועתקו {n} מודעות. הדביקו בצ'אט או במייל.", sx_sub: "{n} מודעות · {when}",
      sx_building: "מכינים את הדף (טוענים תמונות)…",
      sx_photo_note: "חלק מהתמונות צריכות חיבור לאינטרנט כדי להיטען. אם הדף נראה שבור בטלפון (וואטסאפ והודעות לעיתים מציגים תצוגה מקדימה בלי חיבור), כדאי לפתוח אותו בדפדפן: לחצו על שיתוף (או התפריט •••) ואז על \"פתיחה בספארי\" או \"פתיחה בכרום\".",
      sx_footer: "נוצר עם Rental Matcher. המחיר, התמונות והפרטים הם של המודעות עצמן; כדאי לבדוק באתר לפני שהולכים.",
      sx_privacy: "הוא נוצר כאן ומגיע רק למי שתשתפו איתו.", rs_notopened: "נראו בחיפוש ולא נפתחו ({n})", rs_notopened_x: "כבר מדף החיפוש נראה שהן לא עומדות בדרישת חובה, ולכן לא נפתחו. כל אחת עם הסיבה וקישור: אם אחת נראית לכם מתאימה, הסיבה אומרת איזו הגדרה לשנות.",
      fd_btn: "🔎 חסרה מודעה?", fd_title: "חסרה מודעה?", fd_x: "הדביקו קישור למודעה שציפיתם לראות. כאן תראו מה החיפוש האחרון עשה איתה.", fd_go: "בדיקה",
      fd_bad: "זה לא קישור למודעה ביד2, בקומו או במדלן.", fd_rejected: "סימנתם אותה \"לא בשבילי\", ולכן היא לא מוצגת ולא נפתחת.",
      fd_shown: "היא ברשימות שלכם: מקום {n}.", fd_hidden: "החיפוש קרא אותה והסתיר אותה בגלל:",
      fd_merged: "זו מודעה נוספת של דירה שכבר ברשימות שלכם: יש אליה קישור מהכרטיס של הדירה.",
      fd_skipped: "החיפוש ראה אותה אבל לא פתח אותה, כי בדף החיפוש נראה:", fd_unread: "החיפוש ניסה לפתוח אותה אבל הדף לא נטען. החיפוש הבא ינסה שוב.",
      fd_outside: "החיפוש ראה אותה, אבל יד2 משייכים אותה ל{hood}, שלא נמצאת בשכונות שבחרתם.",
      fd_unseen: "החיפוש האחרון ({when}) לא ראה אותה. ייתכן שהיא חדשה מהחיפוש, יקרה מתקרת המחיר של החיפוש, או בעיר שלא מחפשים בה. מה כל חיפוש קרא:",
      fd_cover: "ביד2 {total}, נקראו {seen}",
      cv_title: "מה כל חיפוש כיסה", cv_x: "הספירה של יד2 לכל חיפוש, כמה נקראו, וכמה בשכונות שבחרתם. ⚠ אומר שנקראו פחות ממה שיד2 הציגו.",
      cv_search: "חיפוש", cv_total: "ביד2", cv_seen: "נקראו", cv_kept: "בשכונות שלכם", cv_failed: "{n} דפים נכשלו",
      rooms_short: "חד׳", floor_short: "קומה", rs_photoless: "{n} מודעות בלי תמונות לא מוצגות (הגדרות ← הסתרת מודעות בלי תמונות).", rs_viewing: "נקבעה צפייה", rs_rejected: "נדחו", rs_hidden: "לא מתאימות",
      rs_filter: "סינון לפי רחוב או עיר", rs_last: "חיפוש אחרון: {when} · {n} מודעות בחיפושים שלך", rs_viewings: "הצפיות הקרובות",
      rs_no_date: "לא נקבע תאריך", rs_empty: "אין כאן עדיין כלום.", rs_none: "עוד לא היה חיפוש: לחצו על חיפוש מודעות.",
      ss_checked: "מודעות שנבדקו", ss_matches: "התאמות", ss_new: "חדשות בחיפוש האחרון", ss_rent: "שכר דירה ממוצע בהתאמות",
      ss_commute: "זמן הגעה ממוצע ל{place}", ss_favs: "מועדפים", ss_viewings: "צפיות", ss_week: "חיפושים השבוע",
      ss_first: "חיפוש ראשון טיפוסי", ss_repeat: "חיפוש חוזר טיפוסי", ss_saved: "זמן שנחסך",
      ss_saved_note: "לקרוא את המודעות האלה אחת אחת היה לוקח בערך {t} (הערכה).", ss_recent: "חיפושים אחרונים",
      ss_when: "מתי", ss_took: "משך", ss_listings: "מודעות", ss_opened: "נפתחו", ss_result: "תוצאה",
      ss_complete: "הושלם", ss_stopped: "נעצר", ss_kind_first: "ראשון היום", ss_kind_repeat: "חוזר",
      ss_label_title: "לעזור לו לקרוא מודעות טוב יותר", ss_label_x: "המודעות שהחיפושים שלך קראו, כקובץ: הטקסט והפרטים של האתר עצמו, בלי שמות ומספרי טלפון. אחרי תיוג ידני הן מראות איפה כללי הקריאה טועים.",
      ss_label_dl: "הורדת המודעות שנקראו ({n})",
      ss_log: "יומן חיבור", ss_log_empty: "אין מה לדווח: יד2 לא ביקשה להאט.",
      lg_pushback: "יד2 ביקשה להאט ב{what}, והחיפוש הואט", lg_what_search: "עמוד חיפוש", lg_what_listing: "מודעה",
      lg_check: "יד2 הציגה בדיקה", lg_check_again: "יד2 הציגה בדיקה בפעם השנייה היום, והחיפוש נעצר עד מחר",
      lg_nocheck: "לא נדרשה בדיקה, והחיפוש המשיך אחרי הפסקה קצרה", lg_solved: "הבדיקה הושלמה והחיפוש המשיך",
      su_title: "הגדרות", su_where: "איפה לחפש", su_where_lead: "הערים, או רק השכונות, שבהן מחפשים ביד2.",
      su_city_ph: "הוספת עיר: הקלידו את שמה", su_none: "עוד לא נבחרו ערים.", su_whole_city: "כל העיר", su_pick_hoods: "בחירת שכונות",
      su_tlv_no_jaffa: "תל אביב בלי יפו", su_jaffa: "יפו", su_hoods_loading: "טוענים שכונות…",
      su_hoods_failed: "לא הצלחנו לטעון את השכונות, ולכן נחפש בכל העיר.", su_hoods_n: "{n} שכונות",
      su_added: "נוסף: {x}.", su_already: "{x} כבר ברשימה.", su_pick_city: "בחרו עיר מהרשימה תוך כדי הקלדה.",
      su_finding: "מחפשים את {x} ביד2…", su_link: "או הדביקו קישור לחיפוש ביד2", su_link_name: "שם", su_link_bad: "זה לא חיפוש דירות להשכרה ביד2. פתחו את החיפוש ביד2 והעתיקו את הכתובת.",
      su_not_link: "זה לא קישור.", su_my_search: "החיפוש שלי", su_hood_filter: "חיפוש", su_select_all: "בחירת הכל", su_select_none: "ניקוי",
      su_places: "מקומות שאתם מגיעים אליהם", su_places_lead: "עבודה, לימודים, משפחה: לכל מקום יוצג זמן ההגעה מכל דירה.",
      su_place: "מקום", su_name: "שם", su_name_ph: "למשל: עבודה", su_address: "כתובת", su_address_ph: "למשל: דיזנגוף 50, תל אביב", su_find: "חיפוש",
      su_by: "איך מגיעים", su_speed: "המהירות שלך (קמ\"ש)", su_usual: "{n} (רגיל)", su_time: "שעה ביום", su_rush: "שעת עומס",
      su_offpeak: "שעה רגילה", su_full_marks: "מושלם עד (דק')", su_at_most: "הכי ארוך שתסכימו (דק')", su_looking: "מחפשים…",
      su_nothing: "לא נמצא. נסו רחוב ועיר.", su_from: "מקור: {src}.", su_find_first: "חפשו את הכתובת כדי למקם אותה במפה.",
      su_add_place: "+ הוספת מקום", su_no_places: "עוד אין מקומות.", su_lookup_failed: "החיפוש לא הצליח.",
      su_basics: "תקציב ודירה", su_basics_lead: "דרישת חובה מסתירה מודעות שלא עומדות בה. כל השאר משפיע על ההתאמה.",
      su_features: "מאפיינים", su_features_lead: "מה צריך להיות בדירה.", su_add_pref: "הוספת העדפה…",
      su_must: "חובה", su_must_on: "חובה: מודעות בלי זה מוסתרות", su_counts: "כמה זה חשוב",
      su_rent_ideal: "שכר דירה אידיאלי (₪)", su_rent_limit: "הכי הרבה שתשלמו (₪)", su_rent_tol: "גמישות עד +₪", su_none_ph: "אין",
      su_size_min: "לפחות (מ\"ר)", su_size_ideal: "אידיאלי (מ\"ר)", su_rooms_min: "לפחות (חדרים)", su_floor: "קומה", su_floor_ground: "קומת קרקע מתאימה",
      su_floor_max: "הקומה הגבוהה ביותר בלי מעלית", su_floor_elev: "עם מעלית, כל קומה מתאימה",
      su_movein: "תאריך כניסה", su_movein_ideal: "באופן אידיאלי", su_movein_latest: "לכל המאוחר",
      mv_0: "כמה שיותר מהר", mv_14: "תוך שבועיים", mv_30: "תוך חודש", mv_45: "תוך 6 שבועות", mv_60: "תוך חודשיים",
      mv_90: "תוך 3 חודשים", mv_180: "תוך חצי שנה",
      pk_3: "חניה פרטית", pk_2: "חניה בבניין", pk_1: "חניה ברחוב", pk_0: "לא צריך", su_pk_ideal: "אידיאלי", su_pk_min: "המינימום",
      su_ideal: "אידיאלי", su_limit: "גבול", su_tol: "גמישות", su_items: "פריטים רצויים",
      su_saved_hint: "השינויים ייכנסו לתוקף בחיפוש הבא.", su_unsaved: "יש שינויים שלא נשמרו.", su_undo: "ביטול השינויים",
      su_saving: "שומרים…", su_saved: "נשמר. החיפוש הבא ישתמש בזה.", su_nothing_changed: "לא היו שינויים.", su_not_saved: "לא נשמר: {e}",
      su_find_addr_first: "קודם חפשו את הכתובת של {x}.", su_no_helper: "הרכיב המקומי לא ענה: הפעילו פעם אחת את install.bat שבתיקיית הפרויקט.",
      // v1.27: אתרים נוספים
      site_yad2: "יד2", site_komo: "קומו", site_madlan: "מדלן", site_facebook: "פייסבוק", fb_keep: "שמירת המודעה (Rental Matcher)", fb_title: "Rental Matcher", fb_kept: "המודעה נשמרה לחיפוש הבא", fb_too_short: "יש לסמן קודם את טקסט המודעה, ואז לבחור שמירת המודעה", fb_no_price: "לא נמצא מחיר בטקסט המסומן: יש לסמן את כל המודעה, כולל המחיר", open_on: "פתיחה ב{site}", also_on: "מופיעה גם ב{site}", also_post: "מודעה נוספת ב{site}", maybe_same: "ייתכן שזו אותה דירה ב{site} ({what}): האתרים לא מסכימים, כדאי לבדוק לפני שמתקשרים", maybe_floor: "שם קומה {there}, כאן {here}", maybe_size: "שם {there} מ״ר, כאן {here} מ״ר",
      approx_place: "שכונה בלבד",
      approx_tip: "ב{site} אין כתובת מדויקת, לכן זמני ההגעה מוערכים ממרכז השכונה.",
      st_sites: "מחפשים באתרים נוספים", st_sites_x: "מחפשים בקומו: {x}",
      m_komo_wall: "קומו ביקש להתחבר, לכן נקרא רק העמוד הראשון שלו. מודעות שתפתחו בעצמכם בקומו עדיין יתווספו.",
      m_komo_pushback: "קומו ביקש להאט, לכן הפסקנו לקרוא אותו בחיפוש הזה. יד2 לא הושפע.",
      ss_sources: "מאיפה הגיעו ההתאמות", ss_from: "מ{site}",
      su_sites: "אתרים נוספים", su_show: "מה להציג", su_nophotos: "הסתרת מודעות בלי תמונות", su_nophotos_x: "מופעל כברירת מחדל. מודעה ביד2 או במדלן בלי תמונות לא תופיע ברשימות, בחלונית ובלימוד הטעם. את התמונות בקומו לפעמים אי אפשר לקרוא, ולכן מודעות משם נשארות.", su_sites_lead: "מלבד יד2, מודעות יכולות להגיע גם מ:",
      su_komo_x: "המודעות החדשות ביותר בערים שלכם נקראות בכל חיפוש (העמוד הראשון, שפתוח לכולם; השאר דורש חשבון בקומו). גם מודעות קומו שתפתחו בעצמכם מתווספות.",
      su_madlan_x: "מדלן חוסם קריאה אוטומטית, לכן מתווסף רק מה שראיתם בעצמכם במדלן: פתחו עמוד חיפוש או מודעה במדלן, והם יישמרו לחיפוש הבא למשך 3 ימים.",
      cap_kept: "Rental Matcher שמר {n} מודעות לחיפוש הבא", cap_kept1: "Rental Matcher שמר את המודעה הזו לחיפוש הבא",
      // v1.30: ההגדרות במילים פשוטות
      su_must_hint: "להסתיר מודעות בלי זה", su_imp_better: "כמה שווה יותר טוב", su_imp_lo: "קצת", su_imp_hi: "הרבה",
      imp_1: "קצת", imp_2: "קצת", imp_3: "במידה", imp_4: "במידה", imp_5: "חשוב", imp_6: "חשוב",
      imp_7: "חשוב מאוד", imp_8: "חשוב מאוד", imp_9: "בראש סדר העדיפויות", imp_10: "בראש סדר העדיפויות", imp_of: "{n} מתוך 10 · {w}",
      su_budget: "התקציב שלכם", su_budget_from: "מ-", su_budget_to: "עד", su_budget_none: "בלי מינימום",
      su_rent_perfect: "מחיר מושלם: עד ₪", su_over_ok: "להציג גם מודעות קצת מעל התקציב, מסומנות \"מעל התקציב\"",
      su_over_up_to: "עד +₪", su_worth: "שווה לשלם יותר בשביל", su_worth_lead: "בשביל אלה תעברו את התקציב. בחרו מה ובכמה יותר.",
      su_worth_add: "+ להוסיף משהו ששווה יותר", su_worth_more: "עד +₪", su_effect: "מה זה עושה",
      ef_hide_without: "מודעות בלי זה מוסתרות. אם המודעה לא אומרת, היא מוצגת עם תזכורת לשאול.",
      ef_rank_with: "מודעות עם זה מדורגות גבוה יותר.",
      ef_commute_must: "עד {ideal} דק' מושלם; נסיעה ארוכה יותר מדורגת נמוך יותר, ומעל {limit} דק' מוסתרת.",
      ef_commute_soft: "עד {ideal} דק' מושלם; נסיעה ארוכה יותר מדורגת נמוך יותר, עד אפס ב-{limit} דק'.",
      ef_commute_line: "מעל {limit} דק' מוסתר.",
      ef_rent: "עד {ideal} מושלם; עד {max} מדורג קצת נמוך יותר.", ef_rent_hide: " מעל {hide} מוסתר.",
      ef_rent_soft: " מעל {max} מדורג נמוך יותר אבל מוצג.", ef_rent_min: " מתחת ל-{min} מוסתר.",
      ef_rent_tol: " בין {max} ל-{hide} מוצג, מסומן מעל התקציב.", ef_rent_worth: " עם {what}: עד {to}.",
      ef_min_must: "מתחת ל-{limit} מוסתר.", ef_min_soft: "מתחת ל-{limit} מדורג נמוך יותר.",
      ef_size_must: "קטן מ-{limit} מ\"ר מוסתר.", ef_size_ideal: "גדולה יותר מדורגת גבוה יותר, עד {ideal} מ\"ר.", ef_size_soft: "קטן מ-{limit} מ\"ר מדורג נמוך יותר.",
      ef_rooms_must: "פחות מ-{limit} חדרים מוסתר.", ef_rooms_soft: "פחות מ-{limit} חדרים מדורג נמוך יותר.",
      ef_ground_hidden: "דירות בקומת קרקע מוסתרות.", ef_ground_ok: "קומת קרקע מתאימה.",
      ef_high: "מעל קומה {limit} בלי מעלית מוסתר.", ef_high_elev: " עם מעלית, כל קומה מתאימה.",
      ef_movein_must: "פנויה {ideal} מושלם; מאוחר יותר מדורג נמוך יותר, ויותר מ-{limit} ימים מהיום מוסתר.",
      ef_movein_soft: "פנויה {ideal} מושלם; מאוחר יותר מדורג נמוך יותר.", ef_now: "עכשיו", ef_within: "תוך {n} ימים",
      ef_line_soft: "מעל {limit} מדורג נמוך יותר.", ef_line_must: "מעל {limit} מוסתר.",
      ef_parking_must: "{ideal} הכי טוב; פחות מ{limit} מוסתר.", ef_parking_soft: "{ideal} הכי טוב; פחות מזה מדורג נמוך יותר.",
      ef_items: "מודעות שכוללות את אלה מדורגות גבוה יותר.",
      T_rent_min: "שכר דירה מינימלי", t_rent_min: "שכר הדירה המינימלי", w_rent_min: "זול מהמינימום שלכם",
      n_rent_min: "₪{value}, מתחת למינימום של ₪{limit}", sg_rent_min: "להוריד את שכר הדירה המינימלי ל-₪{to}",
      // v1.30: ההגדרה המהירה
      su_quick: "הגדרה מהירה", wz_title: "הגדרה מהירה", wz_skip: "דילוג, אגדיר בעצמי", wz_later: "לדלג על זה",
      wz_hi: "בואו נמצא לכם בית", wz_hi_x: "ענו על כמה שאלות קצרות, ו-Rental Matcher יקרא בשבילכם את המודעות, ישאיר את המתאימות ויציג קודם את הטובות. בערך שתי דקות. אפשר לשנות הכל אחר כך בהגדרות.",
      wz_start: "בואו נתחיל", wz_where: "איפה תרצו לגור?", wz_where_x: "הקלידו עיר ובחרו אותה מהרשימה. אפשר להוסיף כמה שתרצו.",
      wz_where_hint: "רוצים רק חלק מהשכונות? אפשר לבחור אותן אחר כך בהגדרות.",
      wz_budget: "מה התקציב החודשי?", wz_budget_x: "גררו את שתי הידיות. מודעות מחוץ לטווח לא יוצגו.",
      wz_budget_hint: "הקצה התחתון מסתיר מודעות זולות מכדי להיות מה שאתם מחפשים, כמו חדר בודד. השאירו ₪0 בלי מינימום.",
      wz_rooms: "כמה חדרים לפחות?", wz_rooms_x: "מודעות עם פחות חדרים לא יוצגו.", wz_any: "לא משנה",
      wz_place: "לאן אתם נוסעים רוב הימים?", wz_place_x: "עבודה, לימודים, משפחה. בכל מודעה יוצג כמה זמן לוקחת הנסיעה.",
      wz_place_name: "למשל: עבודה", wz_place_what: "מה זה?", wz_place_how: "איך מגיעים?", wz_place_max: "הנסיעה הכי ארוכה שתסכימו",
      wz_place_find: "קודם מצאו את הכתובת, או לחצו על לדלג על זה.",
      wz_needs: "בלי מה אי אפשר?", wz_needs_x: "לחיצה אחת: חובה. שתיים: נחמד שיהיה. שלוש: ביטול.",
      wz_must: "חובה", wz_must_x: "מודעות בלי זה מוסתרות", wz_nice: "נחמד שיהיה", wz_nice_x: "מודעות עם זה מדורגות גבוה יותר",
      wz_needs_hint: "אם מודעה לא אומרת, היא לא מוסתרת: היא תוצג עם תזכורת לשאול.",
      wz_n_mamad: "ממ\"ד או מקלט", wz_n_no_roommates: "דירה שלמה", wz_n_air_conditioning: "מזגן", wz_n_parking: "חניה",
      wz_n_balcony: "מרפסת", wz_n_elevator: "מעלית", wz_n_not_ground_floor: "לא קומת קרקע", wz_n_pets_allowed: "מותר בעלי חיים", wz_n_renovated: "משופצת",
      wz_done: "זה החיפוש שלכם", wz_done_x: "בדקו ושמרו. אפשר לשנות כל דבר אחר כך בהגדרות.",
      wz_s_where: "איפה", wz_s_budget: "תקציב", wz_s_rooms: "חדרים", wz_s_place: "נסיעה",
      wz_keeps: "זה משנה רק את מה שעניתם כאן. כל השאר בהגדרות נשאר כמו שהיה.",
      wz_save: "שמירה", wz_ready: "הכל מוכן!", wz_ready_x: "לחצו על חיפוש מודעות כדי לחפש עכשיו. בפעם הבאה, לחצו על הסמל של Rental Matcher בסרגל הדפדפן ואז על חיפוש מודעות.",
      wz_settings: "כיוון עדין בהגדרות", wz_find: "חיפוש מודעות",
      b_drop: "ירד ב-{n}", b_drop_tip: "היה {was}, עכשיו {now}", b_deal: "מציאה",
      b_deal_tip_hood: "{n} מתחת למחיר הרגיל ל-{rooms} חדרים ב{place} ({count} מודעות)",
      b_deal_tip_city: "{n} מתחת למחיר הרגיל ל-{rooms} חדרים ב{place} ({count} מודעות)",
      // v1.31: תמונות, הכרטיס הפשוט, המספרים בכרטיס המפורט
      no_photos: "אין תמונות", photo_n: "תמונה {n} מתוך {of}", photo_prev: "התמונה הקודמת", photo_next: "התמונה הבאה",
      save_listing: "שמירה", saved: "נשמר", not_for_me: "לא בשבילי", more_actions: "עוד", details_show: "כל הפרטים", details_hide: "תצוגה פשוטה",
      to_place: "עד {place}", view_simple: "פשוט", view_detailed: "מפורט", view_label: "כרטיסים",
      k_numbers: "המספרים", k_match: "התאמה צפויה", k_likely: "טווח סביר", k_range: "טווח מלא (כל הלא-ידוע לכל כיוון)",
      k_risk: "סיכוי שדרישת חובה לא מתקיימת", k_per_m2: "שכר דירה למ\"ר", k_listed: "מפורסם על ידי", k_agency: "תיווך", k_private: "בעלים",
      k_photos: "תמונות", k_source: "מקור · מזהה", k_usual: "המחיר הרגיל באזור (מודעות)", k_read: "נקרא", k_engine: "ההערות של המנוע ({n})",
      su_all_saved: "כל השינויים נשמרו ✓", su_whole_now: "מחפשים בכל האזור. לחצו על שכונות במפה כדי להישאר בהן.",
      su_pruned: "הוסרו {n} מודעות ממקומות שכבר לא מחפשים בהם.",
      su_all_of: "כל {x}", su_link: "מקישור של יד2", su_n_hoods: "{n} שכונות", su_and_more: "ועוד {n}", su_edit_map: "עריכה על המפה",
      su_save_place: "שמירת השכונות האלה", su_saved_place: "השכונות של {x} נשמרו.", su_pick_some: "בחרו לפחות שכונה אחת, או את כל העיר.",
      su_map_none: "עוד לא נבחרו: לחצו על השכונות במפה.",
      su_pick_hoods_map: "בחירת שכונות על המפה", su_map_picked: "נבחרו {n}",
      su_map_note: "לחצו על השכונות שהייתם גרים בהן; לחיצה נוספת מסירה. גוררים כדי לזוז, גלגלת להגדלה. הגבולות משורטטים לפי מרכזי השכונות של יד2, כך שהם קרובים ולא מדויקים.",
      rs_shelves: "מדפים", rs_grid: "רשת",
      cp_title: "באיזו הייתם מעדיפים לגור?", cp_tune: "🎯 ללמד אותו את הטעם שלך",
      cp_lead: "בחרו את הדירה שבה הייתם מעדיפים לגור. אחרי כמה בחירות, משקלי הדירוג נבדקים מול הבחירות שלכם.",
      cp_lead_x: "הזוגות הם כאלה שהדירוג מחשיב קרובים אבל שונים במה שיש בהם, כך שכל בחירה מלמדת הכי הרבה.",
      cp_count: "{n} בחירות · בסבב הזה {r} מתוך {of}", cp_result: "מה זה למד", cp_need: "עוד {n} בחירות קודם",
      cp_this: "את זו", cp_locked: "חובה", cp_locked_x: "🔒 דרישות חובה נעולות: המשקל שלהן לא משתנה ולא מוצע לשינוי כאן. אפשר לשנות אותן בדף ההגדרות.", cp_or: "או", cp_same: "לא יכול להחליט", cp_neither: "אף אחת", cp_neither_x: "לא הייתם גרים באף אחת. שום דבר לא מוסתר או נדחה: זה מלמד את הדירוג ששתיהן אחרי אלה שאתם כן בוחרים.", cp_none: "קודם חפשו: אין עדיין מודעות להשוות.",
      cp_all_asked: "השוויתם כל זוג ששווה לשאול עליו. חפשו שוב בשביל חדשים.", cp_round_done: "זה סבב.", cp_more: "להמשיך",
      cp_working: "מתאים את המשקלים לבחירות שלכם…", cp_report_title: "מה אומרות {n} בחירות",
      cp_explain: "באיזו תדירות הדירוג שם ראשונה את מה שבחרתם. \"על בחירות שלא ראה\" בודק כל בחירה עם משקלים שהותאמו בלעדיה, אז זה המספר הכן.",
      cp_before: "המשקלים שלך עכשיו", cp_held: "המוצעים, על בחירות שלא ראו", cp_after: "המוצעים, על כל הבחירות",
      cp_crit: "מה נחשב", cp_now: "עכשיו", cp_new: "מוצע", cp_apply: "להשתמש במשקלים המוצעים",
      cp_applied: "נשמר. החיפוש הבא ידרג לפיהם (הקובץ הקודם גובה).",
      cp_keep: "המשקלים הנוכחיים שלך כבר מתאימים לבחירות שלך כמו כל מה שנמצא, אז אין מה לשנות.",
      rs_picks: "✨ בחירות בשבילך", rs_picks_x: "בקבוצות: מציאות, חדשות, הכי קרובות…", rs_every: "▦ כל המודעות", rs_every_x: "רשימה אחת לסינון ומיון",
      rs_stats_v: "📊 סטטיסטיקה", rs_stats_x: "מה החיפושים מצאו", rs_filters: "סינון", rs_filters_n: "סינון ({n})", rs_up_to: "עד", rs_within_min: "עד {n} דק'", rs_parking: "חניה", rs_with_photos: "עם תמונות",
      sh_new: "חדש מאז החיפוש הקודם", sh_new_x: "פורסמו מאז שהסתכלתם לאחרונה.", sh_drop: "המחיר ירד", sh_drop_x: "זולות יותר מאשר כשחיפוש ראה אותן לראשונה.",
      sh_deal: "מציאות", sh_deal_x: "מתחת למחיר הרגיל לאותו מספר חדרים באזור.", sh_saved: "שמורות", sh_saved_x: "אלה שסימנתם בלב.",
      sh_best: "הכי מתאימות לכם", sh_best_x: "הכי קרובות לכל מה שביקשתם.", sh_near: "הכי קרובות ל{place}", sh_near_any: "הנסיעה הקצרה ביותר",
      sh_near_x: "הנסיעה הקצרה ביותר קודם.", sh_cheap: "הכי זולות", sh_cheap_x: "שכר הדירה הנמוך ביותר קודם.", sh_all: "הכל ({n})", sh_back: "כל המדפים",
      cheaper_on: "זול ב-{n} ב{site}",
      cost_vaad: "ועד בית {n}", cost_vaad_in: "אין ועד בית בנפרד", cost_arnona: "ארנונה {n}", cost_arnona_in: "אין ארנונה בנפרד",
      cost_total: "סה״כ לחודש {n}",
    },
  };

  const LOCALE = { en: "en-GB", he: "he-IL" };
  let lang = "en";

  function fill(s, p) {
    return String(s).replace(/(.?)\{(\w+)\}/g, (m, before, k) => {
      if (!p || p[k] == null) return m;
      let v = String(p[k]);
      // Hebrew joins "to" onto the word (לעבודה); before a name in Latin letters it takes a hyphen (ל-Work)
      if (lang === "he" && k === "place" && /[לבמ]$/.test(before) && /^\u2068?[A-Za-z0-9]/.test(v)) v = `-${v}`;
      return before + v;
    });
  }

  function t(key, p) {
    const s = (S[lang] && S[lang][key]) != null ? S[lang][key] : S.en[key];
    return s == null ? key : fill(s, p);
  }

  function setLang(l) {
    lang = S[l] ? l : "en";
    return lang;
  }

  function guess() {
    const n = (root.navigator && (root.navigator.language || "")) || "";
    return /^he|^iw/i.test(n) ? "he" : "en";
  }

  /** The saved choice, or the browser's language. */
  async function load(storage) {
    try {
      const o = storage ? await storage.get("ui") : {};
      return setLang((o.ui && o.ui.lang) || guess());
    } catch (e) {
      return setLang(guess());
    }
  }

  const dir = () => (lang === "he" ? "rtl" : "ltr");
  const num = (n, d) => Number(n).toLocaleString(LOCALE[lang], { maximumFractionDigits: d == null ? 1 : d });
  const money = (n) => (lang === "he" ? `${num(n, 0)} ₪` : `₪${num(n, 0)}`);
  const date = (d, withTime) => {
    const x = d instanceof Date ? d : new Date(d);
    if (isNaN(x)) return "";
    return x.toLocaleString(LOCALE[lang], withTime ? { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }
      : { day: "numeric", month: "short" });
  };
  const when = (d) => {
    const x = new Date(d);
    return isNaN(x) ? "" : x.toLocaleString(LOCALE[lang], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  };

  function duration(ms) {
    const s = Math.round((ms || 0) / 1000);
    if (s < 60) return t("sec", { n: s });
    const m = Math.round(s / 60);
    return m < 60 ? t("min", { n: m }) : t("h_min", { h: Math.floor(m / 60), m: m % 60 });
  }

  function elapsed(ms) {
    const s = Math.round((ms || 0) / 1000);
    return s < 60 ? t("sec", { n: s }) : t("min_sec", { m: Math.floor(s / 60), s: String(s % 60).padStart(2, "0") });
  }

  function timeLeft(ms) {
    if (ms == null) return "";
    return ms < 60e3 ? t("left_less") : t("left_about", { n: Math.round(ms / 60e3) });
  }

  // a name from the user or a listing keeps its own direction inside a sentence
  const iso = (s) => `\u2068${s}\u2069`;

  /** "the trip to Work", "parking": a topic inside a sentence. */
  function topicText(info) {
    if (!info) return "";
    if (info.topic === "commute") return t("t_commute", { place: iso(info.place || "") });
    if (info.topic === "custom") return info.label || "";
    const k = `t_${info.topic}`;
    return S.en[k] ? t(k) : info.label || info.topic;
  }

  /** "Parking", "E-bike to Work": a topic as a title. */
  function topicTitle(info) {
    if (!info) return "";
    if (info.topic === "commute") return t("T_commute", { mode: t(`mode_${info.mode}`), place: iso(info.place || "") });
    if (info.topic === "custom") return info.label || "";
    const k = info.topic === "floor_ground" || info.topic === "floor_high" ? "T_floor" : `T_${info.topic}`;
    return S.en[k] ? t(k) : info.label || info.topic;
  }

  function feature(f) {
    if (f.key === "available") return f.days <= 0 ? t("f_available_now") : t("f_available_from", { date: date(Date.now() + f.days * 864e5) });
    if (f.key === "public_shelter") return t("f_public_shelter", { m: num(f.m, 0) });
    return S.en[`f_${f.key}`] ? t(`f_${f.key}`) : f.key;
  }

  const fmtV = (v) => (typeof v === "number" ? num(v) : String(v));

  /** One note about a listing, in words. info: the preference it's about (config.prefs[name]). */
  function note(n, info) {
    if (!info) return null;
    const tp = info.topic;
    const topic = topicText(info);
    const needs = (n.needs || []).map((s) => t(`t_${s}`) !== `t_${s}` ? t(`t_${s}`) : s.replace(/_/g, " ")).join(" / ");
    const over = () => {
      const v = n.value, lim = n.limit != null ? n.limit : info.limit;
      if (tp === "rent") return t("n_rent_over", { over: num(v - (info.limit != null ? info.limit : lim), 0), limit: num(info.limit != null ? info.limit : lim, 0) })
        + (n.needs && n.needs.length ? t("n_rent_within_if", { needs }) : "");
      if (tp === "rent_min") return t("n_rent_min", { value: num(v, 0), limit: num(lim, 0) });
      if (tp === "size") return t("n_size_under", { value: fmtV(v), limit: fmtV(lim) });
      if (tp === "rooms") return t("n_rooms_under", { value: fmtV(v), limit: fmtV(lim) });
      if (tp === "commute") return t("n_commute_over", { value: fmtV(v), limit: fmtV(lim), by: t(`by_${info.mode}`) });
      if (tp === "movein") return t("n_movein_late", { value: fmtV(v) });
      if (tp === "floor_high") return t("n_floor_high", { value: fmtV(v) });
      if (tp === "floor_ground") return t("n_floor_ground");
      if (tp === "parking") return t("n_parking_low");
      return t("n_generic", { topic: topicTitle(info), value: fmtV(v), limit: fmtV(lim) });
    };
    switch (n.reason) {
      case "unstated": return info.must ? t("n_must_unstated", { topic }) : t("ask_about", { list: topic });
      case "unclear": case "unexpected": return t("n_unclear", { topic });
      case "verify": return t("n_verify", { topic });
      case "companion": return t("n_companion");
      case "needs": return tp === "floor_high" ? t("n_needs_floor", { value: fmtV(n.value) }) : `${over()}. ${t("n_needs", { needs })}`;
      case "exception": return t("n_exception", { text: over() });
      case "over": case "past": return over();
      case "no": return tp === "whole" ? t("n_no_whole") : tp === "unit" ? t("n_no_unit") : tp === "lease" ? t("n_no_lease") : t("n_no", { topic });
      default: return null;
    }
  }

  /** Why listings were left out, by preference: "Too far". */
  function why(name, info) {
    if (name === "rejected") return t("w_rejected");
    if (name === "other" || !info) return t("w_other");
    const k = `w_${info.topic}`;
    return S.en[k] ? t(k) : info.label || name;
  }

  /** "Raise your rent limit to ₪4,750". */
  function suggestion(s) {
    const to = s.now;
    switch (s.topic) {
      case "rent": return t("sg_rent", { to: num(to, 0) });
      case "rent_min": return t("sg_rent_min", { to: num(to, 0) });
      case "commute": return t("sg_commute", { to: fmtV(to), by: t(`by_${s.mode}`) });
      case "size": return t("sg_size", { to: fmtV(to) });
      case "rooms": return t("sg_rooms", { to: fmtV(to) });
      case "floor_ground": return t("sg_floor_ground");
      case "floor_high": return t("sg_floor_high", { to: fmtV(to) });
      case "movein": return t("sg_movein", { to: fmtV(to) });
      case "parking": return t("sg_parking");
      default: return t("sg_soften", { topic: topicText(s) });
    }
  }

  /** Static text on a page: data-i18n, data-i18n-ph (placeholder), data-i18n-title. */
  function apply(doc) {
    doc.documentElement.lang = lang;
    doc.documentElement.dir = dir();
    for (const e of doc.querySelectorAll("[data-i18n]")) e.textContent = t(e.dataset.i18n);
    for (const e of doc.querySelectorAll("[data-i18n-ph]")) e.placeholder = t(e.dataset.i18nPh);
    for (const e of doc.querySelectorAll("[data-i18n-title]")) e.title = t(e.dataset.i18nTitle);
  }

  /** A message the extension made: a key with its values, or plain text. */
  function msg(m) {
    if (!m) return "";
    if (typeof m === "string") return m;
    return t(m.key, m.params);
  }

  const api = {
    S, t, setLang, load, guess, dir, iso, num, money, date, when, duration, elapsed, timeLeft, topicText, topicTitle, feature, note, why,
    suggestion, apply, msg, get lang() { return lang; },
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.RentalI18n = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
