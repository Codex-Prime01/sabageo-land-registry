/* Guided tour of the map page.
   - First visit: a welcome screen asks first. Nothing starts without a "yes".
   - Each step lights up one control and explains it. It moves on ONLY when the visitor taps Next.
   - Some steps can show it working ("Fill a sample for me", "Run the check").
   - Skip any time (the x, "Skip tour" or Esc). Replay from the menu: "Take the tour".
   Uses functions from app.js (setPanel, openMenu, closeMenu, checkPlot, ...), so load it after app.js. */
window.Tour = (function () {
  const KEY = "tourSeen";
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const seen = () => { try { return localStorage.getItem(KEY) === "1"; } catch (e) { return true; } };
  const remember = () => { try { localStorage.setItem(KEY, "1"); } catch (e) {} };
  const q = (sel) => document.querySelector(sel);
  const visible = (el) => el && el.offsetParent !== null && el.getBoundingClientRect().width > 0;
  const wait = (ms) => new Promise((r) => setTimeout(r, still ? Math.min(ms, 60) : ms));

  /* ---------- the steps ---------- */
  // target: what to light up. prep: get the page ready (open the panel, the menu...).
  // demo: an optional "show me" button that does the step for the visitor.
  const STEPS = [
    {
      target: "#panel .bar", title: "The plot checker",
      text: "Everything starts here. Tap this bar to open or close the checker. On a phone, swipe it up or down.",
      prep: () => { closeMenu(false); closePlotCard(); setPanel(true); },
    },
    {
      target: () => q("#corners") && q("#corners").closest(".field"), title: "Type the corners",
      text: "Put each corner of the plot on its own line, like <b>10.6120, 12.1950</b>. Three corners or more. Your surveyor's beacon list works.",
      prep: () => { closeMenu(false); setPanel(true); },
      demo: { label: "Fill a sample for me", run: typeSample },
    },
    {
      target: "#moreOpts", title: "Got UTM or Minna numbers?",
      text: "Most people have latitude and longitude, so that is the default. If your survey plan uses <b>UTM</b> or the older <b>Minna</b> datum, pick it here.",
      prep: () => setPanel(true),
    },
    {
      target: ".actions .csv", title: "Or upload a file",
      text: "Have the corners in a spreadsheet? Save it as CSV and upload it. The Field kit page has a ready template.",
      prep: () => setPanel(true),
    },
    {
      target: "#checkBtn", title: "Check it",
      text: "Tap <b>Check for overlap</b>. SABAGeo compares your plot with every registered plot in a second or two. It is free, and you don't need an account.",
      prep: () => setPanel(true),
      demo: { label: "Run the check", run: runCheck },
    },
    {
      target: "#result", fallback: "#checkBtn", title: "Read the answer",
      text: "<b>0 OVERLAP</b> means the land is free. <b>RED FLAG</b> means it overlaps a registered plot: the exact overlap is shaded red on the map, with its size in m².",
      prep: () => setPanel(true),
      after: describeResult,
    },
    {
      target: "#plotsChip", title: "All registered plots",
      text: "Tap <b>Plots</b> to see every registered plot, grouped by area. Tap one to fly straight to it and see its corners.",
      prep: () => { closeMenu(false); if (isMobile()) setPanel(false); },
    },
    {
      target: "#menuBtn", title: "The menu",
      text: "Everything else lives here: the Registry, Verify a title, Plans, and <b>My account</b> for registering your own plots.",
      prep: () => { closeMenu(false); setPanel(true); },
    },
    {
      target: '.drawer-body button[onclick="verifyLedger()"]', title: "Check the ledger",
      text: "Every registration is written into a chained record. <b>Check ledger</b> proves no registered plot has been changed or deleted since.",
      prep: () => openMenu(),
    },
    {
      target: '.drawer-body button[onclick="verifyAnchors()"]', title: "Verify on Polygon",
      text: "A fingerprint of the ledger is also posted on a public blockchain (the Polygon <b>test</b> network). This compares the two, so nobody can quietly rewrite history.",
      prep: () => openMenu(),
    },
    {
      target: null, title: "You're ready",
      text: "Check any plot for free. To register one, buy a login code under <b>Plans</b> and use <b>My account</b>. You can replay this tour from the menu.",
      prep: () => { closeMenu(false); setPanel(true); },
    },
  ];

  /* ---------- demos ---------- */
  async function typeSample(btn) {
    const box = q("#corners");
    $("crsSel").value = "wgs84";
    onPickersChange();
    const text = EXAMPLES.overlap;
    box.value = "";
    box.focus({ preventScroll: true });
    if (still) box.value = text;
    else for (let i = 1; i <= text.length; i++) { box.value = text.slice(0, i); if (i % 2 === 0) await wait(14); }
    onCornersChange();
    btn.textContent = "Filled in";
  }
  async function runCheck(btn) {
    if (!getCorners().length) await typeSample({ set textContent(v) {} });
    btn.textContent = "Checking…";
    checkPlot();
    for (let i = 0; i < 60 && !q("#result.show"); i++) await wait(150);
    btn.textContent = q("#result.flag") ? "Red flag found" : q("#result.clear") ? "Land is free" : "Done";
  }
  function describeResult(card) {
    const r = q("#result");
    if (!r || !r.classList.contains("show")) return;
    const p = card.querySelector(".text p");
    if (r.classList.contains("flag")) p.innerHTML += " <b>Yours overlaps:</b> see the red zone on the map.";
    else if (r.classList.contains("clear")) p.innerHTML += " <b>Yours is clear.</b>";
  }

  /* ---------- drawing ---------- */
  let root, spot, card, i = 0, raf = 0, lastFocus = null, running = false;

  function build() {
    root = document.createElement("div");
    root.className = "tour-root";
    root.innerHTML = '<div class="tour-block"></div><div class="tour-spot"></div>' +
      '<div class="tour-card" role="dialog" aria-modal="true" aria-labelledby="tourTitle" tabindex="-1"></div>';
    document.body.append(root);
    spot = root.querySelector(".tour-spot");
    card = root.querySelector(".tour-card");
    document.addEventListener("keydown", onKey);
    addEventListener("resize", place);
  }

  function targetOf(step) {
    if (!step.target) return null;
    const el = typeof step.target === "function" ? step.target() : q(step.target);
    if (visible(el)) return el;
    const fb = step.fallback && q(step.fallback);
    return visible(fb) ? fb : null;
  }

  function place() {
    if (!running) return;
    const step = STEPS[i], el = targetOf(step);
    const vw = innerWidth, vh = innerHeight, pad = 8;
    let r = null;
    if (el) {
      const b = el.getBoundingClientRect();
      r = { x: Math.max(4, b.left - pad), y: Math.max(4, b.top - pad), w: Math.min(vw - 8, b.width + pad * 2), h: Math.min(vh - 8, b.height + pad * 2) };
      spot.classList.remove("none");
      Object.assign(spot.style, { left: r.x + "px", top: r.y + "px", width: r.w + "px", height: r.h + "px",
        borderRadius: Math.min(18, r.h / 2) + "px" });
    } else {
      spot.classList.add("none");
    }
    spot.classList.add("on");

    // the card goes where it covers nothing important
    const cw = card.offsetWidth, ch = card.offsetHeight, gap = 14;
    let x, y;
    if (!r) { x = (vw - cw) / 2; y = (vh - ch) / 2; }
    else if (vw <= 640) {                        // phone: dock top or bottom
      x = 12;
      y = r.y + r.h / 2 > vh / 2 ? Math.max(12, r.y - ch - gap) : Math.min(vh - ch - 12, r.y + r.h + gap);
      if (y < 12 || y + ch > vh - 12) y = r.y + r.h / 2 > vh / 2 ? 12 : vh - ch - 12;
    } else if (r.x + r.w + gap + cw < vw - 12) {  // room on the right
      x = r.x + r.w + gap; y = r.y + r.h / 2 - ch / 2;
    } else if (r.x - gap - cw > 12) {             // room on the left
      x = r.x - gap - cw; y = r.y + r.h / 2 - ch / 2;
    } else {                                     // below, or above
      x = r.x + r.w / 2 - cw / 2;
      y = r.y + r.h + gap + ch < vh - 12 ? r.y + r.h + gap : r.y - gap - ch;
    }
    card.style.left = Math.round(Math.min(Math.max(12, x), vw - cw - 12)) + "px";
    card.style.top = Math.round(Math.min(Math.max(12, y), vh - ch - 12)) + "px";
  }

  // keep following the target while panels slide open, then settle
  function follow(ms) {
    cancelAnimationFrame(raf);
    const end = performance.now() + ms;
    const tick = (t) => { place(); if (t < end) raf = requestAnimationFrame(tick); };
    raf = requestAnimationFrame(tick);
  }

  async function show(n) {
    i = Math.max(0, Math.min(STEPS.length - 1, n));
    const step = STEPS[i], last = i === STEPS.length - 1;
    try { step.prep && step.prep(); } catch (e) {}
    card.innerHTML =
      '<button class="tour-x" type="button" aria-label="Skip the tour"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg></button>' +
      '<div class="text"><div class="step">Step ' + (i + 1) + " of " + STEPS.length + '</div><h3 id="tourTitle">' + step.title + "</h3><p>" + step.text + "</p></div>" +
      (step.demo ? '<div style="margin-top:12px"><button class="tour-btn soft" type="button" data-demo>' + step.demo.label + "</button></div>" : "") +
      '<div class="tour-dots" aria-hidden="true">' + STEPS.map((_, k) => "<i" + (k === i ? ' class="on"' : "") + "></i>").join("") + "</div>" +
      '<div class="tour-nav">' +
        (i > 0 ? '<button class="tour-btn ghost" type="button" data-back>Back</button>' : '<button class="tour-btn ghost" type="button" data-skip>Skip tour</button>') +
        '<span class="grow"></span><button class="tour-btn" type="button" data-next>' + (last ? "Finish" : "Next") + "</button></div>";
    card.querySelector(".tour-x").onclick = () => end();
    const skip = card.querySelector("[data-skip]"); if (skip) skip.onclick = () => end();
    const back = card.querySelector("[data-back]"); if (back) back.onclick = () => show(i - 1);
    card.querySelector("[data-next]").onclick = () => (last ? end() : show(i + 1));
    const demo = card.querySelector("[data-demo]");
    if (demo) demo.onclick = async () => {
      demo.disabled = true;
      try { await step.demo.run(demo); } catch (e) { demo.textContent = "Could not do that, try it yourself"; }
      follow(1600); // the result card grows: keep the light on it
    };
    if (step.after) step.after(card);
    follow(900);
    await wait(320); // let the panel or menu finish opening
    const el = targetOf(step);
    if (el) { el.scrollIntoView({ block: "nearest", behavior: still ? "auto" : "smooth" }); follow(700); }
    await wait(30);
    card.querySelector("[data-next]").focus({ preventScroll: true });
  }

  function onKey(e) {
    if (!running) return;
    if (e.key === "Escape") { e.preventDefault(); end(); }
    else if (e.key === "ArrowRight") { e.preventDefault(); if (i < STEPS.length - 1) show(i + 1); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); if (i > 0) show(i - 1); }
    else if (e.key === "Tab") {                    // keep keyboard focus inside the card
      const f = [...card.querySelectorAll("button:not([disabled])")];
      if (!f.length) return;
      const a = f[0], z = f[f.length - 1];
      if (e.shiftKey && document.activeElement === a) { e.preventDefault(); z.focus(); }
      else if (!e.shiftKey && document.activeElement === z) { e.preventDefault(); a.focus(); }
    }
  }

  function begin() {
    if (!root) build();
    running = true;
    root.style.display = "";
    show(0);
  }
  function end() {
    running = false;
    remember();
    cancelAnimationFrame(raf);
    if (root) root.style.display = "none";
    closeMenu(false);
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  /* ---------- welcome (asks first) ---------- */
  function welcome() {
    lastFocus = document.activeElement;
    const w = document.createElement("div");
    w.className = "tour-root";
    w.innerHTML =
      '<div class="tour-welcome" role="dialog" aria-modal="true" aria-labelledby="tourHello"><canvas aria-hidden="true"></canvas>' +
      '<div class="tour-hello">' +
        '<svg class="mark" viewBox="0 0 44 44" aria-hidden="true"><polygon points="8,12 34,7 37,32 11,37" fill="rgba(217,164,65,.22)" stroke="#F4F6FA" stroke-width="2.5" stroke-linejoin="round"/><circle cx="8" cy="12" r="3.6" fill="#D9A441"/><circle cx="34" cy="7" r="3.6" fill="#D9A441"/><circle cx="37" cy="32" r="3.6" fill="#D9A441"/><circle cx="11" cy="37" r="3.6" fill="#D9A441"/></svg>' +
        '<h2 id="tourHello">Welcome to SABAGeo</h2>' +
        "<p>Check if a piece of land is already registered before you buy it. Free, and no account needed.</p>" +
        "<p>Want a quick look around? It takes about a minute, and you choose when to move on.</p>" +
        '<div class="tour-row"><button class="tour-btn big" type="button" data-yes>Show me around</button>' +
        '<button class="tour-btn ghost" type="button" data-no>Not now, I\'ll explore</button></div>' +
      "</div></div>";
    document.body.append(w);
    const screen = w.querySelector(".tour-welcome");
    const g = window.SabaGradient ? SabaGradient.mount(w.querySelector("canvas")) : { stop() {} };
    requestAnimationFrame(() => requestAnimationFrame(() => screen.classList.add("show")));
    const close = (go) => {
      screen.classList.remove("show");
      setTimeout(() => { g.stop(); w.remove(); if (go) begin(); else { remember(); if (lastFocus) lastFocus.focus(); } }, still ? 0 : 450);
    };
    w.querySelector("[data-yes]").onclick = () => close(true);
    w.querySelector("[data-no]").onclick = () => close(false);
    w.addEventListener("keydown", (e) => { if (e.key === "Escape") close(false); });
    setTimeout(() => w.querySelector("[data-yes]").focus(), 60);
  }

  // force: from the menu ("Take the tour") skips the welcome and goes straight to step 1
  function start(force) {
    if (running) return;
    lastFocus = document.activeElement;
    if (force) { closeMenu(false); setTimeout(begin, still ? 0 : 320); }
    else welcome();
  }

  // first visit only, and not when someone arrived to look at one plot (?plot=...)
  if (!seen() && !new URLSearchParams(location.search).get("plot")) setTimeout(() => start(false), 1200);

  return { start };
})();
