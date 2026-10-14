/* SABAGeo Land Registry: map page.
   One tidy file that replaces every paste we added over the rounds. */

const $ = (id) => document.getElementById(id);

/* ---------- Map ---------- */
const map = L.map("map", { zoomControl: false, zoomSnap: 0.25 }).setView([10.6, 12.19], 13);
L.control.zoom({ position: "topright" }).addTo(map);

const esri = (path, o) =>
  L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/" + path + "/MapServer/tile/{z}/{y}/{x}", { maxZoom: 20, ...o });
const hybrid = L.layerGroup([
  esri("World_Imagery", { maxNativeZoom: 17, zIndex: 1, attribution: "Tiles © Esri, Maxar, Earthstar Geographics" }),
  esri("Reference/World_Transportation", { maxNativeZoom: 17, zIndex: 2 }),
  esri("Reference/World_Boundaries_and_Places", { maxNativeZoom: 17, zIndex: 3 }),
]).addTo(map);
const streets = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 20, maxNativeZoom: 19, attribution: "© OpenStreetMap contributors",
});
L.control.scale({ imperial: false, position: "bottomleft" }).addTo(map);
L.control.layers({ "Satellite with names": hybrid, "Street map": streets }, null, { position: "topright", collapsed: true }).addTo(map);

const panel = $("panel");
const isMobile = () => window.innerWidth <= 800;
map.attributionControl.setPrefix(false);
if (isMobile()) map.attributionControl.setPosition("topright");

/* ---------- Constants ---------- */
const COLORS = {
  saved: { color: "#00D1FF", fillColor: "#00D1FF", fillOpacity: 0.28, weight: 3 },
  synth: { color: "#8FA8FF", fillColor: "#8FA8FF", fillOpacity: 0.2, weight: 2.5 },
  clear: { color: "#2BFF88", fillColor: "#2BFF88", fillOpacity: 0.4, weight: 3.5, dashArray: "8 6" },
  flag: { color: "#FF2D4D", fillColor: "#FF2D4D", fillOpacity: 0.6, weight: 4 },
  hit: { color: "#FF2D4D", fillColor: "#FF2D4D", fillOpacity: 0.18, weight: 3 },
  zone: { color: "#FFFFFF", fillColor: "#FF1744", fillOpacity: 0.9, weight: 2, dashArray: "4 4" },
};
const CHECK_ICON = '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
const FLAG_ICON = '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke-width="3" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>';
const TYPES = {
  wgs84: { hint: "One corner per line: latitude, longitude (decimal degrees), like 10.6120, 12.1950. Use at least 3 corners. A CSV needs the same order.", foot: "WGS84 latitude and longitude, in decimal degrees" },
  utm31: { hint: "One corner per line: easting, northing in metres. Use at least 3 corners. A CSV needs the same order.", foot: "UTM Zone 31N (EPSG:32631), in metres" },
  utm32: { hint: "One corner per line: easting, northing in metres. Use at least 3 corners. A CSV needs the same order.", foot: "UTM Zone 32N (EPSG:32632), in metres" },
  utm33: { hint: "One corner per line: easting, northing in metres. Use at least 3 corners. A CSV needs the same order.", foot: "UTM Zone 33N (EPSG:32633), in metres" },
};
const CRS_NAMES = {
  wgs84: { head: "Latitude, Longitude", sub: "WGS84, decimal degrees" },
  utm31: { head: "Easting, Northing", sub: "UTM Zone 31N, metres" },
  utm32: { head: "Easting, Northing", sub: "UTM Zone 32N, metres" },
  utm33: { head: "Easting, Northing", sub: "UTM Zone 33N, metres" },
};
const EXAMPLES = {
  overlap: "10.61115, 12.19360\n10.61115, 12.19390\n10.61145, 12.19390\n10.61145, 12.19360",
  clear: "10.61400, 12.19800\n10.61400, 12.19830\n10.61430, 12.19830\n10.61430, 12.19800",
};
const CT_SHORT = { DISJOINT_NODE: "DISJOINT", ADJOINING_CLUSTER: "ADJOINING" };
// menu groups; the ledger tool buttons from index.html go under "Ledger tools"
const MENU = [
  ["Registry", [["Registered plots", "/registry"], ["Register New Plot", "/register-plot"], ["Parcel report", "/report"]]],
  ["Payments", [["Token payment", "/payments"], ["Payment receipt", "/receipt"]]],
  ["About", [["About us", "/about"], ["How it works", "/how-it-works"], ["Architecture", "/architecture"]]],
];

/* ---------- State ---------- */
let savedLayer = null, newLayer = null, zoneLayer = null, lastOverlaps = [];
let regionData = [], nextSlot = null;
let armed = false, armTimer = null;
let shownCode = null, currentCorners = [];
let panelMemory = null, photoCode = null;

/* ---------- Styles for the overlap zones (added here, so the CSS file needs no change) ---------- */
(function () {
  const css = document.createElement("style");
  css.textContent =
    ".overlap-zone{animation:zonePulse 1.6s ease-in-out infinite}" +
    "@keyframes zonePulse{50%{fill-opacity:.45}}" +
    ".zone-tip{background:#FF1744;color:#fff;border:0;border-radius:999px;padding:3px 10px;font:600 12px/1.4 'Public Sans',sans-serif;box-shadow:0 4px 14px rgba(0,0,0,.35)}" +
    ".zone-tip::before{display:none}" +
    ".ov-list{list-style:none;margin:10px 0 0;padding:0;display:grid;gap:8px}" +
    ".ov-list li{padding:10px 12px;border-radius:12px;background:rgba(255,45,77,.12);border:1px solid rgba(255,45,77,.35)}" +
    ".ov-list .ov-top{display:flex;justify-content:space-between;align-items:center;gap:8px}" +
    ".ov-list small{display:block;margin-top:4px;font-size:12.5px;opacity:.85;line-height:1.5}" +
    ".ov-list button{flex:none;padding:5px 11px;border-radius:999px;border:1px solid currentColor;background:transparent;color:inherit;font:600 12px 'Public Sans',sans-serif;cursor:pointer}" +
    ".ov-list button:hover{background:rgba(255,255,255,.12)}" +
    ".ex-links{margin-top:6px;font-size:12.5px;opacity:.85}" +
    ".ex-links button{background:none;border:0;padding:0 2px;color:#D9A441;font:inherit;font-weight:600;text-decoration:underline;cursor:pointer}" +
    "@media (prefers-reduced-motion:reduce){.overlap-zone{animation:none}}";
  document.head.appendChild(css);
})();

/* ---------- Theme ---------- */
function setTheme(t) {
  document.documentElement.dataset.theme = t;
  document.querySelectorAll(".tswitch").forEach((b) => b.setAttribute("aria-checked", t !== "light"));
  document.querySelector('meta[name="theme-color"]').content = t === "light" ? "#FFFFFF" : "#0A1628";
  try { localStorage.setItem("theme", t); } catch (e) {}
}
function toggleTheme() {
  setTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light");
}

/* ---------- Panel, plots list and menu: one thing open at a time ---------- */
function setPanel(open) {
  panel.classList.toggle("collapsed", !open);
  $("chevron").setAttribute("aria-expanded", open);
}
function togglePanel() { setPanel(panel.classList.contains("collapsed")); }
function tuck() {
  if (panelMemory === null) panelMemory = !panel.classList.contains("collapsed");
  setPanel(false);
}
function untuck(restore) {
  if (restore && panelMemory) setPanel(true);
  panelMemory = null;
}
function openMenu() {
  $("pop").classList.remove("open");
  $("plotsChip").setAttribute("aria-expanded", "false");
  tuck();
  $("drawer").classList.add("open");
  $("scrim").classList.add("open");
}
function closeMenu(restore = true) {
  if (!$("drawer").classList.contains("open")) return;
  $("drawer").classList.remove("open");
  $("scrim").classList.remove("open");
  untuck(restore);
}
function togglePop() {
  if ($("pop").classList.contains("open")) { closePop(true); return; }
  tuck();
  $("pop").classList.add("open");
  $("plotsChip").setAttribute("aria-expanded", "true");
}
function closePop(restore = false) {
  if (!$("pop").classList.contains("open")) return;
  $("pop").classList.remove("open");
  $("plotsChip").setAttribute("aria-expanded", "false");
  untuck(restore);
}
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeMenu(); closePop(); } });
document.addEventListener("click", (e) => { if (!e.target.closest("#pop,#plotsChip")) closePop(); });

/* swipe the card down to close it and up to open it (phones) */
let swipeY = null;
panel.addEventListener("touchstart", (e) => { if (e.target.closest(".grip,.bar")) swipeY = e.touches[0].clientY; }, { passive: true });
panel.addEventListener("touchend", (e) => {
  if (swipeY === null) return;
  const dy = e.changedTouches[0].clientY - swipeY;
  swipeY = null;
  if (dy > 40) setPanel(false);
  else if (dy < -40) setPanel(true);
}, { passive: true });
/* swipe the menu left to close it */
let swipeX = null;
$("drawer").addEventListener("touchstart", (e) => { swipeX = e.touches[0].clientX; }, { passive: true });
$("drawer").addEventListener("touchend", (e) => {
  if (swipeX !== null && e.changedTouches[0].clientX - swipeX < -60) closeMenu();
  swipeX = null;
}, { passive: true });

/* ---------- Menu rows ---------- */
function buildMenu() {
  const body = document.querySelector(".drawer-body");
  body.querySelectorAll(":scope > .acc, :scope > a.row").forEach((el) => el.remove());
  const arrow = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6" /></svg>';
  const tools = [...body.querySelectorAll(":scope > button.row")];
  const label = (text) => {
    const p = document.createElement("p");
    p.className = "menu-sec";
    p.textContent = text;
    return p;
  };
  MENU.forEach(([group, links]) => {
    body.append(label(group));
    links.forEach(([name, href]) => {
      const a = document.createElement("a");
      a.className = "row";
      a.href = href;
      a.innerHTML = "<span>" + name + "</span>" + arrow;
      body.append(a);
    });
  });
  if (tools.length) body.append(label("Ledger tools"), ...tools); // moving keeps their onclick
  [...body.children].forEach((el, i) => el.style.setProperty("--i", i)); // items slide in one by one
  document.querySelectorAll(".content > *").forEach((el, i) => el.style.setProperty("--k", i));
}

/* ---------- Camera ---------- */
function flyTo(bounds, maxZoom) {
  const p = panel.getBoundingClientRect();
  const opts = isMobile()
    ? { paddingTopLeft: [40, 90], paddingBottomRight: [40, p.height + 50] }
    : { paddingTopLeft: [p.right + 80, 90], paddingBottomRight: [90, 90] };
  map.flyToBounds(bounds, { ...opts, maxZoom: maxZoom || 17, duration: 1.8, easeLinearity: 0.12 });
}

/* ---------- Saved plots ---------- */
const styleFor = (f) => (f.properties.source === "synthetic" ? COLORS.synth : COLORS.saved);
const classFor = (f) => (f.properties.source === "synthetic" ? "plot-synth" : "plot-saved");
function popupFor(l) {
  const p = l.feature.properties;
  return p.title_code + (p.label ? "<br>" + p.label : "") + "<br>" +
    (p.source === "synthetic" ? "Synthetic data" : "Field data") + "<br>Beacon photos: " + (p.photo_count || 0);
}
function resetSaved() {
  if (!savedLayer) return;
  savedLayer.eachLayer((l) => {
    l.setStyle(styleFor(l.feature));
    const el = l.getElement();
    if (el) el.classList.remove("plot-flag");
  });
}
/* one row in the quick plots list. DISJOINT and ADJOINING tags show here, never on the map */
function plotItemHtml(p) {
  const sub = p.cluster_type
    ? '<span class="pi-sub"><b class="ct ' + (p.cluster_type === "DISJOINT_NODE" ? "dj" : "aj") + '">' + CT_SHORT[p.cluster_type] + "</b>" +
      p.ref_lat.toFixed(6) + ", " + p.ref_lon.toFixed(6) + "</span>"
    : "";
  return '<li><button class="plot-item two" onclick="goToPlot(\'' + p.title_code + '\')"><span class="pi-main">' + p.title_code +
    (p.source === "synthetic" ? '<span class="tag">synthetic</span>' : "") + "</span>" + sub + "</button></li>";
}
function loadPlots(zoomToThem, focusCode) {
  Promise.all([fetch("/plots").then((r) => r.json()), fetch("/regions").then((r) => r.json())])
    .then(([data, regions]) => {
      regionData = regions;
      const feats = data.features, n = feats.length;
      const pilot = regions.find((r) => r.is_pilot);
      $("plotCount").textContent = n + (n === 1 ? " plot" : " plots") +
        (pilot ? ", pilot " + pilot.registered + " of " + (pilot.registered + pilot.reserved) : "");

      const sel = $("regionSel");
      if (sel.options.length <= 1) {
        sel.innerHTML = regions.map((r) => '<option value="' + r.code + '">' + r.name + "</option>").join("");
        sel.value = "TST";
      }

      if (savedLayer) map.removeLayer(savedLayer);
      savedLayer = L.geoJSON(data, { style: (f) => ({ ...styleFor(f), className: classFor(f) }) }).bindPopup(popupFor).addTo(map);

      const byRegion = {};
      feats.forEach((f) => (byRegion[f.properties.region] = byRegion[f.properties.region] || []).push(f));
      const html = regions.map((r) => {
        const list = byRegion[r.code] || [];
        const total = r.registered + r.reserved;
        const filled = new Set(list.map((f) => f.properties.title_code));
        const open = [];
        if (r.is_pilot) {
          for (let i = 1; i <= total; i++) {
            const c = "SABA-" + r.code + "-RES-" + String(i).padStart(3, "0");
            if (!filled.has(c)) open.push(c);
          }
          nextSlot = open[0] || null;
        }
        if (!list.length && !open.length) return "";
        const items = list.map((f) => plotItemHtml(f.properties)).join("") +
          open.map((c) => `<li><div class="plot-item reserved">${c}<span class="tag">reserved</span></div></li>`).join("");
        return `<div class="grp"><button class="grp-h" onclick="goToRegion('${r.code}')">${r.name}<span>${r.is_pilot ? list.length + " of " + total : list.length}</span></button><ul>${items}</ul></div>`;
      }).join("");

      $("plotPop").innerHTML = html || "<li class='note'>No plots yet. Check a plot, then register it.</li>";
      $("plotBadge").textContent = n;
      updateRegionNote();
      if (zoomToThem && n > 0) map.fitBounds(savedLayer.getBounds(), { padding: [80, 80], maxZoom: 16 });
      if (focusCode) goToPlot(focusCode, true);
    })
    .catch(() => { $("plotCount").textContent = "Could not load plots"; });
}
function goToPlot(code, keepPanel) {
  closeMenu(false);
  closePop(false);
  if (!keepPanel) showPlotCard(code);
  savedLayer.eachLayer((l) => {
    if (l.feature.properties.title_code === code) {
      setTimeout(() => { flyTo(l.getBounds()); setTimeout(() => l.openPopup(), 1900); }, 650);
    }
  });
}
function goToRegion(code) {
  closeMenu(false);
  closePop(false);
  if (isMobile()) setPanel(false);
  const layers = [];
  savedLayer.eachLayer((l) => { if (l.feature.properties.region === code) layers.push(l); });
  if (layers.length) setTimeout(() => flyTo(L.featureGroup(layers).getBounds()), 350);
}
/* tapping a plot on the map opens its card too */
map.on("popupopen", (e) => {
  const l = e.popup._source;
  if (l && l.feature && l.feature.properties.title_code !== shownCode) showPlotCard(l.feature.properties.title_code);
});

/* ---------- Plot card: coordinates of the selected plot ---------- */
function syncSeg() {
  const v = $("crsSel").value;
  document.querySelectorAll("#pcSeg button").forEach((b) => b.classList.toggle("on", b.dataset.crs === v));
}
function setCrs(v) { $("crsSel").value = v; onPickersChange(); }
function showPlotCard(code) {
  shownCode = code;
  const meta = $("pcMeta");
  $("pcCode").textContent = code;
  meta.textContent = "Loading…";
  $("pcCoords").innerHTML = "";
  $("pcType").textContent = "";
  panel.classList.add("viewing");
  setPanel(true);
  syncSeg();
  fetch("/plots/" + encodeURIComponent(code) + "/coordinates?crs=" + $("crsSel").value)
    .then((r) => r.json())
    .then((d) => {
      if (shownCode !== code) return; // another plot was picked meanwhile
      if (d.detail) { meta.textContent = typeof d.detail === "string" ? d.detail : "Could not load this plot."; return; }
      currentCorners = d.corners;
      const t = CRS_NAMES[d.crs];
      meta.innerHTML = d.region + (d.label ? " | " + d.label : "") + (d.cluster_type ? " | " + d.cluster_type : "") + "<br>" +
        (d.ref ? "Dataset point: " + d.ref[0] + ", " + d.ref[1] + "<br>" : "") +
        (d.source === "synthetic" ? "Synthetic data" : "Field data") +
        (d.area_m2 ? " | " + d.area_m2 + " m²" : "") + " | Photos: " + d.photo_count;
      $("pcType").innerHTML = "<b>" + t.head + "</b> <span>" + t.sub + "</span>";
      $("pcCoords").innerHTML = d.corners
        .map((c, i) => '<li><span class="n">' + (i + 1) + '</span><span class="v">' + c[0] + ", " + c[1] + "</span></li>").join("");
    })
    .catch(() => { if (shownCode === code) meta.textContent = "Could not load this plot."; });
}
function closePlotCard() { shownCode = null; panel.classList.remove("viewing"); }
function copyCoords() {
  const b = $("pcCopy");
  const text = currentCorners.map((c) => c[0] + ", " + c[1]).join("\n");
  const say = (m) => { b.textContent = m; setTimeout(() => (b.textContent = "Copy corners"), 1600); };
  if (navigator.clipboard) navigator.clipboard.writeText(text).then(() => say("Copied"), () => say("Could not copy"));
  else say("Could not copy");
}

/* ---------- Coordinate type and region ---------- */
function isPilotSelected() {
  const r = regionData.find((x) => x.code === $("regionSel").value);
  return !!(r && r.is_pilot);
}
function updateTypeUI() {
  const t = TYPES[$("crsSel").value];
  document.querySelector(".hint").textContent = t.hint;
  document.querySelector(".foot").innerHTML = "Coordinates: <b>" + t.foot + "</b>";
}
function updateRegionNote() {
  const note = $("regionNote");
  const r = regionData.find((x) => x.code === $("regionSel").value);
  note.classList.toggle("pilot", !!(r && r.is_pilot));
  if (!r) { note.textContent = ""; return; }
  if (r.is_pilot) note.textContent = nextSlot
    ? "Real field data only. The next plot you register fills pilot slot " + nextSlot + "."
    : "All pilot slots are filled.";
  else if (r.code === "TST") note.textContent = "Practice area. Safe for testing.";
  else note.textContent = "Plots here are stored under " + r.name + ".";
}
function onPickersChange() {
  updateTypeUI();
  updateRegionNote();
  onCornersChange();
  clearZones();
  syncSeg();
  if (shownCode && panel.classList.contains("viewing")) showPlotCard(shownCode);
}
function loadExample(kind) {
  $("crsSel").value = "wgs84";
  $("corners").value = EXAMPLES[kind];
  onPickersChange();
  setPanel(true);
}

/* ---------- Corner box ---------- */
/* lat/long is typed as latitude, longitude. UTM is typed as easting, northing. */
function getCorners() {
  const wgs = $("crsSel").value === "wgs84";
  return $("corners").value.split("\n").filter((l) => l.trim() !== "").map((line) => {
    const [a, b] = line.split(",").map(Number);
    return wgs ? { easting: b, northing: a } : { easting: a, northing: b };
  });
}
function syncGutter() { $("gutter").scrollTop = $("corners").scrollTop; }
function onCornersChange() {
  showRegister(false);
  const wgs = $("crsSel").value === "wgs84";
  const lines = $("corners").value.split("\n");
  const n = lines.filter((l) => l.trim() !== "").length;
  const num = "-?\\d+(?:\\.\\d+)?";
  const ok = new RegExp("^\\s*" + num + "\\s*,\\s*" + num + "\\s*$");
  let bad = lines.findIndex((l) => l.trim() !== "" && !ok.test(l));
  let why = wgs ? "use latitude, longitude" : "use easting, northing";
  if (bad < 0 && wgs) {
    bad = lines.findIndex((l) => {
      if (l.trim() === "") return false;
      const [a, b] = l.split(",").map(Number);
      return Math.abs(a) > 90 || Math.abs(b) > 180;
    });
    why = "latitude within 90, longitude within 180";
  }
  const count = $("count");
  count.textContent = bad >= 0 ? "Line " + (bad + 1) + ": " + why : n === 1 ? "1 corner" : n + " corners";
  count.style.color = bad >= 0 ? "#FF5C77" : "";
  $("checkBtn").disabled = bad >= 0 || n < 3;
  $("gutter").textContent = lines.map((_, i) => i + 1).join("\n");
  syncGutter();
}

/* ---------- Result card and buttons ---------- */
function showRegister(on) {
  const b = $("registerBtn");
  armed = false;
  clearTimeout(armTimer);
  if (on) b.textContent = isPilotSelected() ? "Register as pilot plot" + (nextSlot ? " " + nextSlot.slice(-3) : "") : "Register this plot";
  b.classList.toggle("show", on);
}
function setBusy(id, busy, text) { const b = $(id); b.disabled = busy; b.textContent = text; }
function showResult(kind, title, detail) {
  const box = $("result");
  box.classList.remove("show");
  void box.offsetWidth;
  box.className = "result " + kind;
  $("resultCard").innerHTML = '<div class="seal">' + (kind === "clear" ? CHECK_ICON : FLAG_ICON) + "</div>" +
    '<div><div class="verdict">' + title + '</div><div class="detail">' + detail + "</div></div>";
  requestAnimationFrame(() => box.classList.add("show"));
  setTimeout(() => box.scrollIntoView({ behavior: "smooth", block: "nearest" }), 400);
}
function clearZones() { if (zoneLayer) { map.removeLayer(zoneLayer); zoneLayer = null; } lastOverlaps = []; }

/* ---------- Admin key ---------- */
const adminHeaders = () => { const k = sessionStorage.getItem("adminKey"); return k ? { "X-Admin-Key": k } : {}; };
function refreshAdminState() { $("adminState").textContent = sessionStorage.getItem("adminKey") ? "Unlocked" : "Locked"; }
function unlockAdmin() {
  if (sessionStorage.getItem("adminKey")) { sessionStorage.removeItem("adminKey"); refreshAdminState(); return; }
  const k = prompt("Enter the admin key");
  if (k) sessionStorage.setItem("adminKey", k.trim());
  refreshAdminState();
}

/* ---------- Check and register ---------- */
const jsonPost = (url, payload, extra) => fetch(url, {
  method: "POST", headers: { "Content-Type": "application/json", ...(extra || {}) }, body: JSON.stringify(payload),
});
const bodyFor = () => ({ corners: getCorners(), crs: $("crsSel").value, region: $("regionSel").value });

/* ---------- Where exactly is the overlap? ---------- */
const m2 = (n) => Number(n).toLocaleString("en", { maximumFractionDigits: n < 10 ? 2 : 1 });
function drawZones(overlaps) {
  lastOverlaps = overlaps;
  zoneLayer = L.featureGroup().addTo(map);
  overlaps.forEach((o, i) => {
    const z = L.geoJSON(o.zone, { style: { ...COLORS.zone, className: "overlap-zone" }, interactive: false });
    z.addTo(zoneLayer);
    if (i < 6) {
      const zb = z.getBounds();
      L.tooltip({ permanent: true, direction: "bottom", offset: [0, 6], className: "zone-tip", interactive: false })
        .setLatLng([zb.getSouth(), zb.getCenter().lng]).setContent("Overlap " + m2(o.overlap_m2) + " m²").addTo(zoneLayer);
    }
  });
  zoneLayer.bringToFront();
}
function overlapHtml(data) {
  const n = data.overlaps.length;
  return "This plot overlaps <b>" + n + "</b> registered plot" + (n === 1 ? "" : "s") + ", <b>" + m2(data.total_overlap_m2) +
    " m²</b> in total. The exact overlap is shaded on the map." +
    '<ul class="ov-list">' + data.overlaps.map((o, i) =>
      '<li><div class="ov-top"><b>' + o.title_code + '</b><button type="button" onclick="showZone(' + i + ')">Show</button></div>' +
      "<small>" + (o.label ? o.label + ", " : "") + (o.region || "") + "<br>" +
      m2(o.overlap_m2) + " m² overlap" + (o.share_of_plot_pct != null ? " (" + o.share_of_plot_pct + "% of that plot)" : "") + "<br>" +
      "Overlap centre: " + o.centre[0].toFixed(6) + ", " + o.centre[1].toFixed(6) + "</small></li>").join("") + "</ul>";
}
function showZone(i) {
  const o = lastOverlaps[i];
  if (!o) return;
  const b = L.geoJSON(o.zone).getBounds();
  const zb = b.isValid() ? b : L.latLngBounds([o.centre, o.centre]);
  flyTo(zb, 20);
  if (isMobile()) setPanel(false);
}

function checkPlot() {
  showRegister(false);
  setPanel(true);
  setBusy("checkBtn", true, "Checking…");
  jsonPost("/check", bodyFor())
    .then((r) => r.json())
    .then((data) => {
      if (data.detail) {
        showResult("flag", "Cannot check this plot", typeof data.detail === "string" ? data.detail : "Check that every line is two numbers.");
        return;
      }
      const isRed = data.status === "RED FLAG";
      resetSaved();
      clearZones();
      if (newLayer) map.removeLayer(newLayer);
      newLayer = L.geoJSON(data.shape, { style: { ...(isRed ? COLORS.flag : COLORS.clear), className: isRed ? "plot-flag" : "plot-new" } }).addTo(map);
      if (isRed) {
        const hit = data.overlaps.map((o) => o.title_code);
        savedLayer.eachLayer((l) => {
          if (hit.includes(l.feature.properties.title_code)) {
            l.setStyle(COLORS.hit);
            if (l.getElement()) l.getElement().classList.add("plot-flag");
            l.bringToFront();
          }
        });
        newLayer.setStyle({ fillOpacity: 0.12 });
        newLayer.bringToFront();
        drawZones(data.overlaps);
        showResult("flag", "RED FLAG", overlapHtml(data));
      } else {
        showResult("clear", "0 OVERLAP", "No registered plot shares area with this one. It can be registered.");
        showRegister(true);
      }
      setTimeout(() => flyTo(newLayer.getBounds(), 19), 500);
    })
    .catch(() => showResult("flag", "Something went wrong", "Check your corners and that the server is running."))
    .finally(() => setBusy("checkBtn", false, "Check for overlap"));
}

function registerPlot() {
  const b = $("registerBtn");
  /* pilot plots need a second tap, so a slot is never filled by accident */
  if (isPilotSelected() && !armed) {
    armed = true;
    b.textContent = "Tap again to confirm pilot plot" + (nextSlot ? " " + nextSlot.slice(-3) : "");
    clearTimeout(armTimer);
    armTimer = setTimeout(() => showRegister(true), 4500);
    return;
  }
  armed = false;
  clearTimeout(armTimer);
  setBusy("registerBtn", true, "Registering…");
  jsonPost("/register", bodyFor(), adminHeaders())
    .then((r) => r.json())
    .then((data) => {
      if (data.detail) {
        showResult("flag", "Not registered", typeof data.detail === "string" ? data.detail : "Check your corners and try again.");
        return;
      }
      showResult("clear", "Registered", "Title code: <b>" + data.title_code + "</b><br>Area: <b>" + data.area_m2 + " m²</b>");
      showRegister(false);
      if (newLayer) map.removeLayer(newLayer);
      newLayer = null;
      clearZones();
      offerPhoto(data.title_code);
      loadPlots(false, data.title_code);
    })
    .catch(() => showResult("flag", "Something went wrong", "The plot was not saved. Please try again."))
    .finally(() => { b.disabled = false; if (b.classList.contains("show")) showRegister(true); });
}

/* ---------- CSV import: first two columns, in the same order as the coordinate type ---------- */
function importCsv(input) {
  const file = input.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    const rows = reader.result.split(/\r?\n/).map((l) => l.trim()).filter(Boolean)
      .map((l) => l.split(/[,;\t]/).map((x) => x.trim()))
      .filter((c) => c.length >= 2 && c[0] !== "" && c[1] !== "" && !isNaN(Number(c[0])) && !isNaN(Number(c[1])));
    const note = $("csvNote");
    if (rows.length < 3) {
      note.textContent = "Found " + rows.length + " valid corners in " + file.name + ". A plot needs at least 3.";
      return;
    }
    $("corners").value = rows.map((c) => c[0] + ", " + c[1]).join("\n");
    onCornersChange();
    setPanel(true);
    note.textContent = rows.length + " corners loaded from " + file.name + ". Now press Check for overlap.";
  };
  reader.readAsText(file);
  input.value = "";
}

/* ---------- Beacon photo ---------- */
function offerPhoto(code) {
  photoCode = code;
  const b = $("photoBtn");
  b.textContent = "Add beacon photo for " + code;
  b.classList.add("show");
}
function uploadPhoto(input) {
  const file = input.files[0];
  if (!file || !photoCode) return;
  const fd = new FormData();
  fd.append("file", file);
  const b = $("photoBtn");
  b.disabled = true;
  fetch("/plots/" + photoCode + "/photo", { method: "POST", headers: adminHeaders(), body: fd })
    .then((r) => r.json())
    .then((d) => {
      if (d.detail) { showResult("flag", "Photo not saved", typeof d.detail === "string" ? d.detail : "Use a JPG or PNG under 10 MB."); return; }
      const near = d.has_gps && d.distance_m <= 100;
      const msg = !d.has_gps
        ? "This photo has no GPS tag. Take it with your phone camera with Location turned on."
        : "The photo was taken <b>" + d.distance_m + " m</b> from the plot." + (near ? "" : " That is far. Check it was taken at the beacon.");
      showResult(near ? "clear" : "flag", near ? "Photo saved" : "Photo saved, needs a look", msg);
      loadPlots(false);
    })
    .catch(() => showResult("flag", "Something went wrong", "The photo was not saved. Please try again."))
    .finally(() => { b.disabled = false; input.value = ""; });
}

/* ---------- Ledger and Polygon ---------- */
function verifyLedger() {
  const s = $("ledgerState");
  s.textContent = "Checking…";
  fetch("/ledger/verify").then((r) => r.json()).then((d) => {
    s.textContent = d.valid ? "Intact" : "Broken";
    closeMenu();
    setPanel(true);
    if (d.valid) {
      showResult("clear", "Ledger intact", d.records + " records checked. Nothing has been changed." +
        (d.not_in_ledger ? " " + d.not_in_ledger + " plots were registered before the ledger existed." : ""));
    } else {
      showResult("flag", "Ledger broken", "Problem at record " + d.broken_at + ": " + d.reason + ".");
    }
  }).catch(() => { s.textContent = "Error"; });
}
function anchorLedger() {
  const s = $("anchorState");
  s.textContent = "Sending…";
  fetch("/ledger/anchor", { method: "POST", headers: adminHeaders() }).then((r) => r.json()).then((d) => {
    closeMenu();
    setPanel(true);
    if (d.detail) {
      s.textContent = "Failed";
      showResult("flag", "Not anchored", typeof d.detail === "string" ? d.detail : "Something went wrong.");
      return;
    }
    s.textContent = "Done";
    showResult("clear", d.already ? "Already anchored" : "Anchored on Polygon",
      (d.already ? "The latest ledger record was already posted. " : "Ledger record " + d.ledger_id + " is now public. ") +
      '<a href="' + d.url + '" target="_blank" rel="noopener" style="color:inherit;text-decoration:underline">View on PolygonScan</a>');
  }).catch(() => { s.textContent = "Failed"; });
}
function verifyAnchors() {
  fetch("/ledger/anchors").then((r) => r.json()).then((d) => {
    closeMenu();
    setPanel(true);
    const a = d.anchors;
    if (!a.length) { showResult("flag", "No anchors yet", "Tap Anchor to Polygon first."); return; }
    const bad = a.filter((x) => !x.matches_ledger || x.matches_chain === false);
    const unknown = a.filter((x) => x.matches_chain === null).length;
    if (bad.length) {
      showResult("flag", "Mismatch found", "The anchor for ledger record " + bad[0].ledger_id + " does not match. The ledger may have been rewritten.");
    } else {
      showResult("clear", "Anchors match", a.length + " anchor(s) checked. " +
        (unknown ? "Could not reach Polygon for " + unknown + ", try again. " : "The public chain agrees with your ledger. ") +
        '<a href="' + a[0].url + '" target="_blank" rel="noopener" style="color:inherit;text-decoration:underline">Latest on PolygonScan</a>');
    }
  });
}

/* ---------- Start up ---------- */
let savedTheme = "dark";
try { savedTheme = localStorage.getItem("theme") || "dark"; } catch (e) {}
setTheme(savedTheme);
buildMenu();
refreshAdminState();
if (isMobile()) setPanel(false);

$("crsSel").value = "wgs84";
$("corners").value = ""; // start empty; the examples are one tap away
$("corners").placeholder = "10.6120, 12.1950\n10.6120, 12.1954\n10.6124, 12.1954\n10.6124, 12.1950";
(function () {
  const hint = document.querySelector(".hint");
  if (!hint || document.querySelector(".ex-links")) return;
  const ex = document.createElement("div");
  ex.className = "ex-links";
  ex.innerHTML = 'Try an example: <button type="button" onclick="loadExample(\'overlap\')">overlapping plot</button> or <button type="button" onclick="loadExample(\'clear\')">clear plot</button>';
  hint.after(ex);
})();
onPickersChange();
loadPlots(true);

/* open a plot from a link like /?plot=SABA-LAG-SYN-001 (used by the Registry and Report pages) */
(function () {
  const code = new URLSearchParams(location.search).get("plot");
  if (!code) return;
  const wait = setInterval(() => {
    if (savedLayer) {
      clearInterval(wait);
      goToPlot(code);
      history.replaceState(null, "", location.pathname);
    }
  }, 300);
  setTimeout(() => clearInterval(wait), 10000);
})();
