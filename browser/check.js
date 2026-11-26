/* Rental Matcher: the window that pops up when Yad2 shows its check (v1.26). */
"use strict";

const $ = (id) => document.getElementById(id);

$("go").addEventListener("click", async () => {
  await chrome.runtime.sendMessage({ type: "show" });
});
$("stop").addEventListener("click", async () => {
  await chrome.runtime.sendMessage({ type: "stop" });
  window.close();
});
chrome.storage.onChanged.addListener((c) => {
  if (c.pull && c.pull.newValue && c.pull.newValue.phase !== "check") window.close();
});
RentalI18n.load(chrome.storage.local).then(async () => {
  RentalI18n.apply(document);
  const { status } = await chrome.storage.local.get("status");
  if (status && status.message) $("text").textContent = RentalI18n.msg(status.message);
});
