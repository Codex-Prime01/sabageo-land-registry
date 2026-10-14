const map = L.map("map", { zoomControl: false, zoomSnap: 0.25 }).setView(
  [10.6, 12.19],
  13,
);
L.control.zoom({ position: "topright" }).addTo(map);

/* Keyless basemaps (CARTO now needs an API key, so we use Esri instead) */
const esri = (path, o) =>
  L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/" +
      path +
      "/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 20, ...o },
  );
const hybrid = L.layerGroup([
  esri("World_Imagery", {
    maxNativeZoom: 17,
    zIndex: 1,
    attribution: "Tiles © Esri, Maxar, Earthstar Geographics",
  }),
  esri("Reference/World_Transportation", {
    maxNativeZoom: 17,
    zIndex: 2,
  }),
  esri("Reference/World_Boundaries_and_Places", {
    maxNativeZoom: 17,
    zIndex: 3,
  }),
]).addTo(map);
const streets = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 20,
  maxNativeZoom: 19,
  attribution: "© OpenStreetMap contributors",
});
L.control.scale({ imperial: false, position: "bottomleft" }).addTo(map);
L.control
  .layers({ "Satellite with names": hybrid, "Street map": streets }, null, {
    position: "topright",
    collapsed: true,
  })
  .addTo(map);

const panel = document.getElementById("panel");
const isMobile = () => window.innerWidth <= 800;
map.attributionControl.setPrefix(false);
if (isMobile()) map.attributionControl.setPosition("topright");

const COLORS = {
  saved: {
    color: "#00D1FF",
    fillColor: "#00D1FF",
    fillOpacity: 0.28,
    weight: 3,
  },
  clear: {
    color: "#2BFF88",
    fillColor: "#2BFF88",
    fillOpacity: 0.4,
    weight: 3.5,
    dashArray: "8 6",
  },
  flag: {
    color: "#FF2D4D",
    fillColor: "#FF2D4D",
    fillOpacity: 0.6,
    weight: 4,
  },
};
const CHECK_ICON =
  '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
const FLAG_ICON =
  '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke-width="3" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>';
let savedLayer = null,
  newLayer = null;

/* theme: dark or light, remembered on this device */
function setTheme(t) {
  document.documentElement.dataset.theme = t;
  document
    .querySelectorAll(".tswitch")
    .forEach((b) => b.setAttribute("aria-checked", t !== "light"));
  document.querySelector('meta[name="theme-color"]').content =
    t === "light" ? "#FFFFFF" : "#0A1628";
  try {
    localStorage.setItem("theme", t);
  } catch (e) {}
}
function toggleTheme() {
  setTheme(
    document.documentElement.dataset.theme === "light" ? "dark" : "light",
  );
}
let savedTheme = "dark";
try {
  savedTheme = localStorage.getItem("theme") || "dark";
} catch (e) {}
setTheme(savedTheme);

/* drawer sections open and close */
function toggleAcc(btn) {
  const open = btn.parentElement.classList.toggle("open");
  btn.setAttribute("aria-expanded", open);
}

/* panel open / close */
function setPanel(open) {
  panel.classList.toggle("collapsed", !open);
  document.getElementById("chevron").setAttribute("aria-expanded", open);
}
function togglePanel() {
  setPanel(panel.classList.contains("collapsed"));
}
if (isMobile()) setPanel(false);

/* menu drawer */
function openMenu() {
  document.getElementById("drawer").classList.add("open");
  document.getElementById("scrim").classList.add("open");
}
function closeMenu() {
  document.getElementById("drawer").classList.remove("open");
  document.getElementById("scrim").classList.remove("open");
}
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeMenu();
});

/* gentle camera: slower, never zooms in too close, keeps the shape clear of the panel */
function flyTo(bounds) {
  const p = panel.getBoundingClientRect();
  const opts = isMobile()
    ? {
        paddingTopLeft: [40, 90],
        paddingBottomRight: [40, p.height + 50],
      }
    : {
        paddingTopLeft: [p.right + 80, 90],
        paddingBottomRight: [90, 90],
      };
  map.flyToBounds(bounds, {
    ...opts,
    maxZoom: 17,
    duration: 1.8,
    easeLinearity: 0.12,
  });
}

/* saved plots */
function resetSaved() {
  if (!savedLayer) return;
  savedLayer.setStyle(COLORS.saved);
  savedLayer.eachLayer(
    (l) => l.getElement() && l.getElement().classList.remove("plot-flag"),
  );
}
function loadPlots(zoomToThem, focusCode) {
  fetch("/plots")
    .then((r) => r.json())
    .then((data) => {
      const n = data.features.length;
      document.getElementById("plotCount").textContent =
        n === 1 ? "1 registered plot" : n + " registered plots";
      if (savedLayer) map.removeLayer(savedLayer);
      savedLayer = L.geoJSON(data, {
        style: () => ({ ...COLORS.saved, className: "plot-saved" }),
      })
        .bindPopup(
          (l) =>
            l.feature.properties.title_code +
            "<br>Beacon photos: " +
            (l.feature.properties.photo_count || 0),
        )
        .addTo(map);
      const items =
        n === 0
          ? "<li class='note'>No plots yet. Check a plot, then register it.</li>"
          : data.features
              .map(
                (f) =>
                  '<li><button class="plot-item" onclick="goToPlot(\'' +
                  f.properties.title_code +
                  "')\">" +
                  f.properties.title_code +
                  "</button></li>",
              )
              .join("");
      document.getElementById("plotList").innerHTML = items;
      document.getElementById("plotPop").innerHTML = items;
      document.getElementById("plotBadge").textContent = n;
      if (zoomToThem && n > 0)
        map.fitBounds(savedLayer.getBounds(), {
          padding: [80, 80],
          maxZoom: 16,
        });
      if (focusCode) goToPlot(focusCode, true);
    })
    .catch(() => {
      document.getElementById("plotCount").textContent = "Could not load plots";
    });
}
function goToPlot(code, keepPanel) {
  closeMenu();
  closePop();
  if (isMobile() && !keepPanel) setPanel(false);
  savedLayer.eachLayer((l) => {
    if (l.feature.properties.title_code === code) {
      setTimeout(() => {
        flyTo(l.getBounds());
        setTimeout(() => l.openPopup(), 1900);
      }, 400);
    }
  });
}
loadPlots(true);

/* form */
function getCorners() {
  return document
    .getElementById("corners")
    .value.split("\n")
    .filter((l) => l.trim() !== "")
    .map((line) => {
      const [e, n] = line.split(",").map(Number);
      return { easting: e, northing: n };
    });
}
function syncGutter() {
  document.getElementById("gutter").scrollTop =
    document.getElementById("corners").scrollTop;
}
function onCornersChange() {
  showRegister(false);
  const lines = document.getElementById("corners").value.split("\n");
  const n = lines.filter((l) => l.trim() !== "").length;
  const num = "-?\\d+(?:\\.\\d+)?";
  const ok = new RegExp("^\\s*" + num + "\\s*,\\s*" + num + "\\s*$");
  const bad = lines.findIndex((l) => l.trim() !== "" && !ok.test(l));
  const count = document.getElementById("count");
  count.textContent =
    bad >= 0
      ? "Line " + (bad + 1) + ": use easting, northing"
      : n === 1
        ? "1 corner"
        : n + " corners";
  count.style.color = bad >= 0 ? "#FF5C77" : "";
  document.getElementById("checkBtn").disabled = bad >= 0 || n < 3;
  document.getElementById("gutter").textContent = lines
    .map((_, i) => i + 1)
    .join("\n");
  syncGutter();
}
onCornersChange();
function showRegister(on) {
  document.getElementById("registerBtn").classList.toggle("show", on);
}
function setBusy(id, busy, text) {
  const b = document.getElementById(id);
  b.disabled = busy;
  b.textContent = text;
}

function showResult(kind, title, detail) {
  const box = document.getElementById("result");
  box.classList.remove("show");
  void box.offsetWidth;
  box.className = "result " + kind;
  document.getElementById("resultCard").innerHTML =
    '<div class="seal">' +
    (kind === "clear" ? CHECK_ICON : FLAG_ICON) +
    "</div>" +
    '<div><div class="verdict">' +
    title +
    '</div><div class="detail">' +
    detail +
    "</div></div>";
  requestAnimationFrame(() => box.classList.add("show"));
  setTimeout(
    () => box.scrollIntoView({ behavior: "smooth", block: "nearest" }),
    400,
  );
}

function checkPlot() {
  showRegister(false);
  setPanel(true);
  setBusy("checkBtn", true, "Checking…");
  fetch("/check", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ corners: getCorners() }),
  })
    .then((r) => r.json())
    .then((data) => {
      if (data.detail) {
        showResult(
          "flag",
          "Cannot check this plot",
          typeof data.detail === "string"
            ? data.detail
            : "Check that every line is two numbers, like 850040, 1172010.",
        );
        return;
      }
      const isRed = data.status === "RED FLAG";
      resetSaved();
      if (newLayer) map.removeLayer(newLayer);
      newLayer = L.geoJSON(data.shape, {
        style: {
          ...(isRed ? COLORS.flag : COLORS.clear),
          className: isRed ? "plot-flag" : "plot-new",
        },
      }).addTo(map);

      if (isRed) {
        const hit = data.overlaps.map((o) => o.title_code);
        savedLayer.eachLayer((l) => {
          if (hit.includes(l.feature.properties.title_code)) {
            l.setStyle(COLORS.flag);
            l.getElement() && l.getElement().classList.add("plot-flag");
            l.bringToFront();
          }
        });
        newLayer.bringToFront();
        showResult(
          "flag",
          "RED FLAG",
          "This plot overlaps registered land:<br>" +
            data.overlaps
              .map(
                (o) =>
                  "<b>" +
                  o.title_code +
                  "</b>, " +
                  o.overlap_m2 +
                  " m² overlap",
              )
              .join("<br>"),
        );
      } else {
        showResult(
          "clear",
          "0 OVERLAP",
          "No registered plot shares area with this one. It can be registered.",
        );
        showRegister(true);
      }
      placeMark(isRed);
      setTimeout(() => flyTo(newLayer.getBounds()), 500);
    })
    .catch(() =>
      showResult(
        "flag",
        "Something went wrong",
        "Check that every line is two numbers, like 850040, 1172010, and that the server is running.",
      ),
    )
    .finally(() => setBusy("checkBtn", false, "Check for overlap"));
}

function registerPlot() {
  setBusy("registerBtn", true, "Registering…");
  fetch("/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ corners: getCorners() }),
  })
    .then((r) => r.json())
    .then((data) => {
      if (data.detail) {
        showResult(
          "flag",
          "Not registered",
          typeof data.detail === "string"
            ? data.detail
            : "Check your corners and try again.",
        );
        return;
      }
      showResult(
        "clear",
        "Registered",
        "Title code: <b>" +
          data.title_code +
          "</b><br>Area: <b>" +
          data.area_m2 +
          " m²</b>",
      );
      showRegister(false);
      if (newLayer) map.removeLayer(newLayer);
      newLayer = null;
      offerPhoto(data.title_code);
      loadPlots(false, data.title_code);
    })
    .catch(() =>
      showResult(
        "flag",
        "Something went wrong",
        "The plot was not saved. Please try again.",
      ),
    )
    .finally(() => setBusy("registerBtn", false, "Register this plot"));
}

/* map credits */
let creditsTimer;
function toggleCredits() {
  const on = document.body.classList.toggle("attr");
  clearTimeout(creditsTimer);
  if (on)
    creditsTimer = setTimeout(
      () => document.body.classList.remove("attr"),
      8000,
    );
}

/* floating plots list */
function togglePop() {
  document.getElementById("pop").classList.toggle("open");
}
function closePop() {
  document.getElementById("pop").classList.remove("open");
}
document.addEventListener("click", (e) => {
  if (!e.target.closest("#pop,#plotsChip")) closePop();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closePop();
});

/* swipe the card down to close, up to open (phones) */
let y0 = null;
panel.addEventListener(
  "touchstart",
  (e) => {
    if (e.target.closest(".grip,.bar")) y0 = e.touches[0].clientY;
  },
  { passive: true },
);
panel.addEventListener(
  "touchend",
  (e) => {
    if (y0 === null) return;
    const dy = e.changedTouches[0].clientY - y0;
    y0 = null;
    if (dy > 40) setPanel(false);
    else if (dy < -40) setPanel(true);
  },
  { passive: true },
);

/* CSV import: first two columns are easting, northing. A header row is fine. */
function importCsv(input) {
  const file = input.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    const rows = reader.result
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter(Boolean)
      .map((l) => l.split(/[,;\t]/).map((x) => x.trim()))
      .filter(
        (c) =>
          c.length >= 2 &&
          c[0] !== "" &&
          c[1] !== "" &&
          !isNaN(Number(c[0])) &&
          !isNaN(Number(c[1])),
      );
    const note = document.getElementById("csvNote");
    if (rows.length < 3) {
      note.textContent =
        "Found " +
        rows.length +
        " valid corners in " +
        file.name +
        ". A plot needs at least 3.";
      return;
    }
    document.getElementById("corners").value = rows
      .map((c) => c[0] + ", " + c[1])
      .join("\n");
    onCornersChange();
    setPanel(true);
    note.textContent =
      rows.length +
      " corners loaded from " +
      file.name +
      ". Now press Check for overlap.";
  };
  reader.readAsText(file);
  input.value = "";
}

/* Beacon photo */
let photoCode = null;
function offerPhoto(code) {
  photoCode = code;
  const b = document.getElementById("photoBtn");
  b.textContent = "Add beacon photo for " + code;
  b.classList.add("show");
}
function uploadPhoto(input) {
  const file = input.files[0];
  if (!file || !photoCode) return;
  const fd = new FormData();
  fd.append("file", file);
  const b = document.getElementById("photoBtn");
  b.disabled = true;
  fetch("/plots/" + photoCode + "/photo", { method: "POST", body: fd })
    .then((r) => r.json())
    .then((d) => {
      if (d.detail) {
        showResult(
          "flag",
          "Photo not saved",
          typeof d.detail === "string"
            ? d.detail
            : "Use a JPG or PNG under 10 MB.",
        );
        return;
      }
      const near = d.has_gps && d.distance_m <= 100;
      const msg = !d.has_gps
        ? "This photo has no GPS tag. Take it with your phone camera with Location turned on."
        : "The photo was taken <b>" +
          d.distance_m +
          " m</b> from the plot." +
          (near ? "" : " That is far. Check it was taken at the beacon.");
      showResult(
        near ? "clear" : "flag",
        near ? "Photo saved" : "Photo saved, needs a look",
        msg,
      );
      loadPlots(false);
    })
    .catch(() =>
      showResult(
        "flag",
        "Something went wrong",
        "The photo was not saved. Please try again.",
      ),
    )
    .finally(() => {
      b.disabled = false;
      input.value = "";
    });
}

/* Ledger check */
function verifyLedger() {
  const s = document.getElementById("ledgerState");
  s.textContent = "Checking…";
  fetch("/ledger/verify")
    .then((r) => r.json())
    .then((d) => {
      s.textContent = d.valid ? "Intact" : "Broken";
      closeMenu();
      setPanel(true);
      if (d.valid) {
        showResult(
          "clear",
          "Ledger intact",
          d.records +
            " records checked. Nothing has been changed." +
            (d.not_in_ledger
              ? " " +
                d.not_in_ledger +
                " older plots were registered before the ledger existed."
              : ""),
        );
      } else {
        showResult(
          "flag",
          "Ledger broken",
          "Problem at record " + d.broken_at + ": " + d.reason + ".",
        );
      }
    })
    .catch(() => {
      s.textContent = "Error";
    });
}

/* Admin key */
/* Admin key: kept only for this browser tab, and sent along with every request to our own server */
const _fetch = window.fetch;
window.fetch = (url, opts = {}) => {
  const key = sessionStorage.getItem("adminKey");
  if (key && typeof url === "string" && url.startsWith("/")) {
    opts.headers = { ...(opts.headers || {}), "X-Admin-Key": key };
  }
  return _fetch(url, opts);
};
function refreshAdminState() {
  document.getElementById("adminState").textContent = sessionStorage.getItem(
    "adminKey",
  )
    ? "Unlocked"
    : "Locked";
}
function unlockAdmin() {
  if (sessionStorage.getItem("adminKey")) {
    sessionStorage.removeItem("adminKey");
    refreshAdminState();
    return;
  }
  const k = prompt("Enter the admin key");
  if (k) sessionStorage.setItem("adminKey", k.trim());
  refreshAdminState();
}
refreshAdminState();

/* Anchor the ledger on Polygon */
function anchorLedger() {
  const s = document.getElementById("anchorState");
  s.textContent = "Sending…";
  fetch("/ledger/anchor", { method: "POST" })
    .then((r) => r.json())
    .then((d) => {
      closeMenu();
      setPanel(true);
      if (d.detail) {
        s.textContent = "Failed";
        showResult(
          "flag",
          "Not anchored",
          typeof d.detail === "string" ? d.detail : "Something went wrong.",
        );
        return;
      }
      s.textContent = "Done";
      showResult(
        "clear",
        d.already ? "Already anchored" : "Anchored on Polygon",
        (d.already
          ? "The latest ledger record was already posted. "
          : "Ledger record " + d.ledger_id + " is now public. ") +
          '<a href="' +
          d.url +
          '" target="_blank" rel="noopener" style="color:inherit;text-decoration:underline">View on PolygonScan</a>',
      );
    })
    .catch(() => {
      s.textContent = "Failed";
    });
}

/* Check the anchors against the public chain */
function verifyAnchors() {
  fetch("/ledger/anchors")
    .then((r) => r.json())
    .then((d) => {
      closeMenu();
      setPanel(true);
      const a = d.anchors;
      if (!a.length) {
        showResult("flag", "No anchors yet", "Tap Anchor to Polygon first.");
        return;
      }
      const bad = a.filter(
        (x) => !x.matches_ledger || x.matches_chain === false,
      );
      const unknown = a.filter((x) => x.matches_chain === null).length;
      if (bad.length) {
        showResult(
          "flag",
          "Mismatch found",
          "The anchor for ledger record " +
            bad[0].ledger_id +
            " does not match. The ledger may have been rewritten.",
        );
      } else {
        showResult(
          "clear",
          "Anchors match",
          a.length +
            " anchor(s) checked. " +
            (unknown
              ? "Could not reach Polygon for " + unknown + ", try again. "
              : "The public chain agrees with your ledger. ") +
            '<a href="' +
            a[0].url +
            '" target="_blank" rel="noopener" style="color:inherit;text-decoration:underline">Latest on PolygonScan</a>',
        );
      }
    });
}

/* Green tick for 0 overlap, red X for overlap, shown on the map */
let mark = null;
function clearMark() {
  if (mark) {
    map.removeLayer(mark);
    mark = null;
  }
}
function placeMark(isRed) {
  clearMark();
  const icon = isRed
    ? '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke-width="4" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>'
    : '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
  mark = L.marker(newLayer.getBounds().getCenter(), {
    icon: L.divIcon({
      className: "verdict-marker",
      html: '<div class="vm ' + (isRed ? "bad" : "ok") + '">' + icon + "</div>",
      iconSize: [46, 46],
      iconAnchor: [23, 23],
    }),
    interactive: false,
    keyboard: false,
  }).addTo(map);
}
document.getElementById("corners").addEventListener("input", clearMark);
/* one thing open at a time: panel, plots list, menu */
let panelMemory = null;
function tuck() {
  if (panelMemory === null)
    panelMemory = !panel.classList.contains("collapsed");
  setPanel(false);
}
function untuck(restore) {
  if (restore && panelMemory) setPanel(true);
  panelMemory = null;
}

function openMenu() {
  const pop = document.getElementById("pop");
  pop.classList.remove("open"); // close the plots list, but keep what the panel was doing
  document.getElementById("plotsChip").setAttribute("aria-expanded", "false");
  tuck();
  document.getElementById("drawer").classList.add("open");
  document.getElementById("scrim").classList.add("open");
}
function closeMenu(restore = true) {
  const d = document.getElementById("drawer");
  if (!d.classList.contains("open")) return;
  d.classList.remove("open");
  document.getElementById("scrim").classList.remove("open");
  untuck(restore);
}

function togglePop() {
  const pop = document.getElementById("pop");
  if (pop.classList.contains("open")) {
    closePop(true);
    return;
  }
  tuck();
  pop.classList.add("open");
  document.getElementById("plotsChip").setAttribute("aria-expanded", "true");
}
function closePop(restore = false) {
  const pop = document.getElementById("pop");
  if (!pop.classList.contains("open")) return;
  pop.classList.remove("open");
  document.getElementById("plotsChip").setAttribute("aria-expanded", "false");
  untuck(restore);
}

/* items slide in one after another */
document
  .querySelectorAll(".drawer-body > *")
  .forEach((el, i) => el.style.setProperty("--i", i));
document
  .querySelectorAll(".content > *")
  .forEach((el, i) => el.style.setProperty("--k", i));

/* swipe the menu left to close it */
let sx = null;
const menuEl = document.getElementById("drawer");
menuEl.addEventListener(
  "touchstart",
  (e) => {
    sx = e.touches[0].clientX;
  },
  { passive: true },
);
menuEl.addEventListener(
  "touchend",
  (e) => {
    if (sx !== null && e.changedTouches[0].clientX - sx < -60) closeMenu();
    sx = null;
  },
  { passive: true },
);

/* ===== Round 2: coordinate type, regions, pilot slots ===== */
COLORS.synth = {
  color: "#8FA8FF",
  fillColor: "#8FA8FF",
  fillOpacity: 0.2,
  weight: 2.5,
};
var armed = false,
  armTimer = null,
  regionData = [],
  nextSlot = null;

const TYPES = {
  wgs84: {
    hint: "One corner per line: latitude, longitude (decimal degrees), like 10.6120, 12.1950. Use at least 3 corners. A CSV needs the same order.",
    foot: "WGS84 latitude and longitude, in decimal degrees",
  },
  utm31: {
    hint: "One corner per line: easting, northing in metres. Use at least 3 corners. A CSV needs the same order.",
    foot: "UTM Zone 31N (EPSG:32631), in metres",
  },
  utm32: {
    hint: "One corner per line: easting, northing in metres. Use at least 3 corners. A CSV needs the same order.",
    foot: "UTM Zone 32N (EPSG:32632), in metres",
  },
  utm33: {
    hint: "One corner per line: easting, northing in metres. Use at least 3 corners. A CSV needs the same order.",
    foot: "UTM Zone 33N (EPSG:32633), in metres",
  },
};
const EXAMPLES = {
  overlap:
    "10.61115, 12.19360\n10.61115, 12.19390\n10.61145, 12.19390\n10.61145, 12.19360",
  clear:
    "10.61400, 12.19800\n10.61400, 12.19830\n10.61430, 12.19830\n10.61430, 12.19800",
};

function styleFor(f) {
  return f.properties.source === "synthetic" ? COLORS.synth : COLORS.saved;
}
function classFor(f) {
  return f.properties.source === "synthetic" ? "plot-synth" : "plot-saved";
}
function popupFor(l) {
  const p = l.feature.properties;
  return (
    p.title_code +
    (p.label ? "<br>" + p.label : "") +
    "<br>" +
    (p.source === "synthetic" ? "Synthetic data" : "Field data") +
    "<br>Beacon photos: " +
    (p.photo_count || 0)
  );
}
function isPilotSelected() {
  const r = regionData.find(
    (x) => x.code === document.getElementById("regionSel").value,
  );
  return !!(r && r.is_pilot);
}

function updateTypeUI() {
  const t = TYPES[document.getElementById("crsSel").value];
  document.querySelector(".hint").textContent = t.hint;
  document.querySelector(".foot").innerHTML =
    "Coordinates: <b>" + t.foot + "</b>";
}
function updateRegionNote() {
  const note = document.getElementById("regionNote");
  const r = regionData.find(
    (x) => x.code === document.getElementById("regionSel").value,
  );
  note.classList.toggle("pilot", !!(r && r.is_pilot));
  if (!r) {
    note.textContent = "";
    return;
  }
  if (r.is_pilot)
    note.textContent = nextSlot
      ? "Real field data only. The next plot you register fills pilot slot " +
        nextSlot +
        "."
      : "All pilot slots are filled.";
  else if (r.code === "TST")
    note.textContent = "Practice area. Safe for testing.";
  else note.textContent = "Plots here are stored under " + r.name + ".";
}
function onPickersChange() {
  updateTypeUI();
  updateRegionNote();
  onCornersChange();
  clearMark();
}
function loadExample(kind) {
  document.getElementById("crsSel").value = "wgs84";
  document.getElementById("corners").value = EXAMPLES[kind];
  onPickersChange();
  setPanel(true);
}

/* corners: lat/long is typed as latitude, longitude; UTM as easting, northing */
function getCorners() {
  const wgs = document.getElementById("crsSel").value === "wgs84";
  return document
    .getElementById("corners")
    .value.split("\n")
    .filter((l) => l.trim() !== "")
    .map((line) => {
      const [a, b] = line.split(",").map(Number);
      return wgs ? { easting: b, northing: a } : { easting: a, northing: b };
    });
}
function onCornersChange() {
  showRegister(false);
  const wgs = document.getElementById("crsSel").value === "wgs84";
  const lines = document.getElementById("corners").value.split("\n");
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
  const count = document.getElementById("count");
  count.textContent =
    bad >= 0
      ? "Line " + (bad + 1) + ": " + why
      : n === 1
        ? "1 corner"
        : n + " corners";
  count.style.color = bad >= 0 ? "#FF5C77" : "";
  document.getElementById("checkBtn").disabled = bad >= 0 || n < 3;
  document.getElementById("gutter").textContent = lines
    .map((_, i) => i + 1)
    .join("\n");
  syncGutter();
}

/* register button: the label follows the region, and pilot plots need a second tap */
function showRegister(on) {
  const b = document.getElementById("registerBtn");
  armed = false;
  clearTimeout(armTimer);
  if (on)
    b.textContent = isPilotSelected()
      ? "Register as pilot plot" + (nextSlot ? " " + nextSlot.slice(-3) : "")
      : "Register this plot";
  b.classList.toggle("show", on);
}
const _registerPlot = registerPlot;
registerPlot = function () {
  const b = document.getElementById("registerBtn");
  if (isPilotSelected() && !armed) {
    armed = true;
    b.textContent =
      "Tap again to confirm pilot plot" +
      (nextSlot ? " " + nextSlot.slice(-3) : "");
    clearTimeout(armTimer);
    armTimer = setTimeout(() => showRegister(true), 4500);
    return;
  }
  armed = false;
  clearTimeout(armTimer);
  _registerPlot();
};

/* send the chosen coordinate type and region along with every check and register */
const _fetch2 = window.fetch;
window.fetch = (url, opts = {}) => {
  if (
    (url === "/check" || url === "/register") &&
    typeof opts.body === "string"
  ) {
    const body = JSON.parse(opts.body);
    body.crs = document.getElementById("crsSel").value;
    body.region = document.getElementById("regionSel").value;
    opts = { ...opts, body: JSON.stringify(body) };
  }
  return _fetch2(url, opts);
};

/* saved plots: grouped by region, pilot first, empty pilot slots shown as reserved */
function resetSaved() {
  if (!savedLayer) return;
  savedLayer.eachLayer((l) => {
    l.setStyle(styleFor(l.feature));
    const el = l.getElement();
    if (el) el.classList.remove("plot-flag");
  });
}
function goToPlot(code, keepPanel) {
  closeMenu(false);
  closePop(false);
  if (isMobile() && !keepPanel) setPanel(false);
  savedLayer.eachLayer((l) => {
    if (l.feature.properties.title_code === code) {
      setTimeout(() => {
        flyTo(l.getBounds());
        setTimeout(() => l.openPopup(), 1900);
      }, 400);
    }
  });
}
function goToRegion(code) {
  closeMenu(false);
  closePop(false);
  if (isMobile()) setPanel(false);
  const layers = [];
  savedLayer.eachLayer((l) => {
    if (l.feature.properties.region === code) layers.push(l);
  });
  if (layers.length)
    setTimeout(() => flyTo(L.featureGroup(layers).getBounds()), 350);
}
function loadPlots(zoomToThem, focusCode) {
  Promise.all([
    fetch("/plots").then((r) => r.json()),
    fetch("/regions").then((r) => r.json()),
  ])
    .then(([data, regions]) => {
      regionData = regions;
      const feats = data.features;
      const n = feats.length;
      const pilot = regions.find((r) => r.is_pilot);
      document.getElementById("plotCount").textContent =
        n +
        (n === 1 ? " plot" : " plots") +
        (pilot
          ? ", pilot " +
            pilot.registered +
            " of " +
            (pilot.registered + pilot.reserved)
          : "");

      const sel = document.getElementById("regionSel");
      if (sel.options.length <= 1) {
        sel.innerHTML = regions
          .map((r) => '<option value="' + r.code + '">' + r.name + "</option>")
          .join("");
        sel.value = "TST";
      }

      if (savedLayer) map.removeLayer(savedLayer);
      savedLayer = L.geoJSON(data, {
        style: (f) => ({ ...styleFor(f), className: classFor(f) }),
      })
        .bindPopup(popupFor)
        .addTo(map);

      const byRegion = {};
      feats.forEach((f) =>
        (byRegion[f.properties.region] =
          byRegion[f.properties.region] || []).push(f),
      );
      const html = regions
        .map((r) => {
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
          const items =
            list
              .map((f) => {
                const p = f.properties;
                return `<li><button class="plot-item" onclick="goToPlot('${p.title_code}')">${p.title_code}${p.source === "synthetic" ? '<span class="tag">synthetic</span>' : ""}</button></li>`;
              })
              .join("") +
            open
              .map(
                (c) =>
                  `<li><div class="plot-item reserved">${c}<span class="tag">reserved</span></div></li>`,
              )
              .join("");
          return `<div class="grp"><button class="grp-h" onclick="goToRegion('${r.code}')">${r.name}<span>${r.is_pilot ? list.length + " of " + total : list.length}</span></button><ul>${items}</ul></div>`;
        })
        .join("");

      const empty =
        "<li class='note'>No plots yet. Check a plot, then register it.</li>";
      document.getElementById("plotList").innerHTML = html || empty;
      document.getElementById("plotPop").innerHTML = html || empty;
      document.getElementById("plotBadge").textContent = n;
      updateRegionNote();
      if (zoomToThem && n > 0)
        map.fitBounds(savedLayer.getBounds(), {
          padding: [80, 80],
          maxZoom: 16,
        });
      if (focusCode) goToPlot(focusCode, true);
    })
    .catch(() => {
      document.getElementById("plotCount").textContent = "Could not load plots";
    });
}

/* start-up: lat/long, with an overlap example so the red X shows at once */
document.querySelector(".drawer ol li").textContent =
  "Pick the coordinate type and region, then enter the plot corners.";
document.getElementById("crsSel").value = "wgs84";
document.getElementById("corners").value = EXAMPLES.overlap;
onPickersChange();

/* ===== Plot card: coordinates of the selected plot ===== */
var shownCode = null,
  currentCorners = [];
const CRS_NAMES = {
  wgs84: { head: "Latitude, Longitude", sub: "WGS84, decimal degrees" },
  utm31: { head: "Easting, Northing", sub: "UTM Zone 31N, metres" },
  utm32: { head: "Easting, Northing", sub: "UTM Zone 32N, metres" },
  utm33: { head: "Easting, Northing", sub: "UTM Zone 33N, metres" },
};
function syncSeg() {
  const v = document.getElementById("crsSel").value;
  document
    .querySelectorAll("#pcSeg button")
    .forEach((b) => b.classList.toggle("on", b.dataset.crs === v));
}
function setCrs(v) {
  document.getElementById("crsSel").value = v;
  onPickersChange();
}
function onPickersChange() {
  updateTypeUI();
  updateRegionNote();
  onCornersChange();
  clearMark();
  syncSeg();
  if (shownCode && panel.classList.contains("viewing")) showPlotCard(shownCode);
}
function showPlotCard(code) {
  shownCode = code;
  const crs = document.getElementById("crsSel").value;
  const meta = document.getElementById("pcMeta");
  document.getElementById("pcCode").textContent = code;
  meta.textContent = "Loading…";
  document.getElementById("pcCoords").innerHTML = "";
  document.getElementById("pcType").textContent = "";
  panel.classList.add("viewing");
  setPanel(true);
  syncSeg();
  fetch("/plots/" + encodeURIComponent(code) + "/coordinates?crs=" + crs)
    .then((r) => r.json())
    .then((d) => {
      if (shownCode !== code) return; // another plot was picked meanwhile
      if (d.detail) {
        meta.textContent =
          typeof d.detail === "string" ? d.detail : "Could not load this plot.";
        return;
      }
      currentCorners = d.corners;
      const t = CRS_NAMES[d.crs];
      meta.innerHTML =
        d.region +
        (d.label ? " | " + d.label : "") +
        (d.cluster_type ? " | " + d.cluster_type : "") +
        "<br>" +
        (d.ref ? "Dataset point: " + d.ref[0] + ", " + d.ref[1] + "<br>" : "") +
        "<br>" +
        (d.source === "synthetic" ? "Synthetic data" : "Field data") +
        (d.area_m2 ? " | " + d.area_m2 + " m²" : "") +
        " | Photos: " +
        d.photo_count;
      document.getElementById("pcType").innerHTML =
        "<b>" + t.head + "</b> <span>" + t.sub + "</span>";
      document.getElementById("pcCoords").innerHTML = d.corners
        .map(
          (c, i) =>
            '<li><span class="n">' +
            (i + 1) +
            '</span><span class="v">' +
            c[0] +
            ", " +
            c[1] +
            "</span></li>",
        )
        .join("");
    })
    .catch(() => {
      if (shownCode === code) meta.textContent = "Could not load this plot.";
    });
}
function closePlotCard() {
  shownCode = null;
  panel.classList.remove("viewing");
}
function copyCoords() {
  const b = document.getElementById("pcCopy");
  const text = currentCorners.map((c) => c[0] + ", " + c[1]).join("\n");
  const say = (msg) => {
    b.textContent = msg;
    setTimeout(() => (b.textContent = "Copy corners"), 1600);
  };
  if (navigator.clipboard)
    navigator.clipboard.writeText(text).then(
      () => say("Copied"),
      () => say("Could not copy"),
    );
  else say("Could not copy");
}

/* picking a plot (from the list or the map) opens its card; the map glides to it */
function goToPlot(code, keepPanel) {
  closeMenu(false);
  closePop(false);
  if (!keepPanel) showPlotCard(code);
  savedLayer.eachLayer((l) => {
    if (l.feature.properties.title_code === code) {
      setTimeout(() => {
        flyTo(l.getBounds());
        setTimeout(() => l.openPopup(), 1900);
      }, 650);
    }
  });
}
map.on("popupopen", (e) => {
  const l = e.popup._source;
  if (l && l.feature && l.feature.properties.title_code !== shownCode)
    showPlotCard(l.feature.properties.title_code);
});

/* About and How it works are now their own pages */
(function () {
  const arrow =
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6" /></svg>';
  const accs = document.querySelectorAll(".drawer-body > .acc");
  [
    ["About us", "/about", 1],
    ["How it works", "/how-it-works", 2],
  ].forEach(([name, href, i], k) => {
    const a = document.createElement("a");
    a.className = "row";
    a.href = href;
    a.style.setProperty("--i", i);
    a.innerHTML = "<span>" + name + "</span>" + arrow;
    accs[k].replaceWith(a);
  });
})();
syncSeg();
/* ===== Phase A: tags in the lists (never on the map) ===== */
const CT_SHORT = {
  DISJOINT_NODE: "DISJOINT",
  ADJOINING_CLUSTER: "ADJOINING",
};
function plotItemHtml(p) {
  const sub = p.cluster_type
    ? '<span class="pi-sub"><b class="ct ' +
      (p.cluster_type === "DISJOINT_NODE" ? "dj" : "aj") +
      '">' +
      CT_SHORT[p.cluster_type] +
      "</b>" +
      p.ref_lat.toFixed(6) +
      ", " +
      p.ref_lon.toFixed(6) +
      "</span>"
    : "";
  return (
    '<li><button class="plot-item two" onclick="goToPlot(\'' +
    p.title_code +
    '\')"><span class="pi-main">' +
    p.title_code +
    (p.source === "synthetic" ? '<span class="tag">synthetic</span>' : "") +
    "</span>" +
    sub +
    "</button></li>"
  );
}
function loadPlots(zoomToThem, focusCode) {
  Promise.all([
    fetch("/plots").then((r) => r.json()),
    fetch("/regions").then((r) => r.json()),
  ])
    .then(([data, regions]) => {
      regionData = regions;
      const feats = data.features;
      const n = feats.length;
      const pilot = regions.find((r) => r.is_pilot);
      document.getElementById("plotCount").textContent =
        n +
        (n === 1 ? " plot" : " plots") +
        (pilot
          ? ", pilot " +
            pilot.registered +
            " of " +
            (pilot.registered + pilot.reserved)
          : "");

      const sel = document.getElementById("regionSel");
      if (sel.options.length <= 1) {
        sel.innerHTML = regions
          .map((r) => '<option value="' + r.code + '">' + r.name + "</option>")
          .join("");
        sel.value = "TST";
      }

      if (savedLayer) map.removeLayer(savedLayer);
      savedLayer = L.geoJSON(data, {
        style: (f) => ({ ...styleFor(f), className: classFor(f) }),
      })
        .bindPopup(popupFor)
        .addTo(map);

      const byRegion = {};
      feats.forEach((f) =>
        (byRegion[f.properties.region] =
          byRegion[f.properties.region] || []).push(f),
      );
      const html = regions
        .map((r) => {
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
          const items =
            list.map((f) => plotItemHtml(f.properties)).join("") +
            open
              .map(
                (c) =>
                  `<li><div class="plot-item reserved">${c}<span class="tag">reserved</span></div></li>`,
              )
              .join("");
          return `<div class="grp"><button class="grp-h" onclick="goToRegion('${r.code}')">${r.name}<span>${r.is_pilot ? list.length + " of " + total : list.length}</span></button><ul>${items}</ul></div>`;
        })
        .join("");

      const empty =
        "<li class='note'>No plots yet. Check a plot, then register it.</li>";
      document.getElementById("plotList").innerHTML = html || empty;
      document.getElementById("plotPop").innerHTML = html || empty;
      document.getElementById("plotBadge").textContent = n;
      updateRegionNote();
      if (zoomToThem && n > 0)
        map.fitBounds(savedLayer.getBounds(), {
          padding: [80, 80],
          maxZoom: 16,
        });
      if (focusCode) goToPlot(focusCode, true);
    })
    .catch(() => {
      document.getElementById("plotCount").textContent = "Could not load plots";
    });
}

/* Architecture link, right under How it works */
(function () {
  const how = document.querySelector(
    '.drawer-body > a.row[href="/how-it-works"]',
  );
  if (!how) return;
  const link = how.cloneNode(true);
  link.href = "/architecture";
  link.querySelector("span").textContent = "Architecture";
  link.style.setProperty("--i", 3);
  how.after(link);
})();

/* Menu: Registered plots and Parcel report are now their own pages */
(function () {
  const arrow =
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6" /></svg>';
  const acc = document.querySelector(".drawer-body > .acc");
  if (!acc) return;
  // keep the old list element alive but hidden, because loadPlots still fills it
  const old = document.getElementById("plotList");
  if (old) {
    old.hidden = true;
    document.body.appendChild(old);
  }
  const make = (name, href, i) => {
    const a = document.createElement("a");
    a.className = "row";
    a.href = href;
    a.style.setProperty("--i", i);
    a.innerHTML = "<span>" + name + "</span>" + arrow;
    return a;
  };
  const registry = make("Registered plots", "/registry", 4);
  acc.replaceWith(registry);
  registry.after(make("Parcel report", "/report", 5));
})();

/* Open a plot from a link like /?plot=SABA-LAG-SYN-001 (used by the Registry and Report pages) */
(function () {
  const code = new URLSearchParams(location.search).get("plot");
  if (!code) return;
  const wait = setInterval(() => {
    if (typeof savedLayer !== "undefined" && savedLayer) {
      clearInterval(wait);
      goToPlot(code);
      history.replaceState(null, "", location.pathname);
    }
  }, 300);
  setTimeout(() => clearInterval(wait), 10000);
})();

/* Menu: Token payment and Payment receipt */
(function () {
  const rep = document.querySelector('.drawer-body > a.row[href="/report"]');
  if (!rep) return;
  const arrow =
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6" /></svg>';
  const make = (name, href, i) => {
    const a = document.createElement("a");
    a.className = "row";
    a.href = href;
    a.style.setProperty("--i", i);
    a.innerHTML = "<span>" + name + "</span>" + arrow;
    return a;
  };
  const pay = make("Token payment", "/payments", 6);
  rep.after(pay);
  pay.after(make("Payment receipt", "/receipt", 7));
})();

/* Menu: Register New Plot, right under Registered plots */
(function () {
  const registry = document.querySelector(
    '.drawer-body > a.row[href="/registry"]',
  );
  if (!registry) return;
  const a = document.createElement("a");
  a.className = "row";
  a.href = "/register-plot";
  a.style.setProperty("--i", 5);
  a.innerHTML =
    '<span>Register New Plot</span><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6" /></svg>';
  registry.after(a);
})();

/* Menu: sort the rows into labelled groups so the long list is easy to scan.
   This only moves existing rows; their click handlers move with them. */
(function () {
  const body = document.querySelector(".drawer-body");
  if (!body) return;
  const link = (href) => body.querySelector('a.row[href="' + href + '"]');
  const tools = [...body.querySelectorAll(":scope > button.row")];
  const groups = [
    ["Registry", ["/registry", "/register-plot", "/report"].map(link)],
    ["Payments", ["/payments", "/receipt"].map(link)],
    ["About", ["/about", "/how-it-works", "/architecture"].map(link)],
    ["Ledger tools", tools],
  ];
  groups.forEach(([name, rows]) => {
    rows = rows.filter(Boolean);
    if (!rows.length) return;
    const label = document.createElement("p");
    label.className = "menu-sec";
    label.textContent = name;
    body.append(label, ...rows);
  });
  // renumber so the slide-in animation runs top to bottom
  [...body.children].forEach((el, i) => el.style.setProperty("--i", i));
})();
