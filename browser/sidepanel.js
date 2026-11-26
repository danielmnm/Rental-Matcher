/*
 * Rental Matcher: the panel in Chrome's side panel (v1.32). Since v1.33 the
 * toolbar button puts the panel on the page you're on (overlay.js); the
 * side panel is where it goes on a page Chrome keeps extensions off
 * (Chrome's own pages, the Web Store). What the panel does: panelhost.js.
 */
"use strict";
RentalPanelHost.run({ embedded: true });
