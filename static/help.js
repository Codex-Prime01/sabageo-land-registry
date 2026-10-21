/* SABAGeo Help chat: a "Help" button on every page that opens a small chat.
   It suggests questions before you type, explains the last error the page showed you, and,
   when you are logged in, gives tips about your own receipts, code and plots.
   Loaded by site.js on content pages and by index.html on the map. */
(function () {
  if (window.HelpChat) return;
  const ERR_KEY = "helpLastError";
  const store = (k, v) => { try { v == null ? sessionStorage.removeItem(k) : sessionStorage.setItem(k, v); } catch (e) {} };
  const read = (k, where) => { try { return (where || sessionStorage).getItem(k) || ""; } catch (e) { return ""; } };
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  // plain text from the server: escape it, keep line breaks, and turn /page addresses into links
  const format = (s) => esc(s).replace(/(^|[\s(])(\/[a-z][a-z0-9\-\/]*)/g, '$1<a href="$2">$2</a>').replace(/\n/g, "<br>");

  /* ---- remember the last error any page request got, so the chat can explain it ---- */
  let lastError = null;
  try { lastError = JSON.parse(read(ERR_KEY) || "null"); } catch (e) {}
  if (lastError && Date.now() - lastError.at > 15 * 60 * 1000) lastError = null; // older than 15 minutes: forget it
  const realFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    return realFetch(input, init).then((r) => {
      const url = typeof input === "string" ? input : (input && input.url) || "";
      const ours = url.startsWith("/") || url.startsWith(location.origin);
      if (!r.ok && ours && !url.includes("/api/help/")) {
        r.clone().json().then((d) => {
          // "please log in" just means a login ended; the page already says so, no need to flag it
          if (d && typeof d.detail === "string" && !/^Please log in/.test(d.detail)) noteError(d.detail);
        }).catch(() => {}); // not JSON: nothing to explain
      }
      return r;
    });
  };
  function noteError(msg) {
    lastError = { msg: msg.slice(0, 300), at: Date.now() };
    store(ERR_KEY, JSON.stringify(lastError));
    if (fab) fab.querySelector(".hc-dot").hidden = false;
    if (opened && panel.classList.contains("open")) errorChip();
  }

  // the person's own logins, so the chat can see their receipts and plots (only theirs)
  function headers() {
    const h = { "Content-Type": "application/json" };
    const acc = read("accountToken", localStorage), code = read("clientToken"), staff = read("staffToken");
    if (acc) h["X-Account-Token"] = acc;
    if (code) h["X-Client-Token"] = code;
    if (staff) h["X-Staff-Token"] = staff;
    return h;
  }

  /* ---- build the button and the panel ---- */
  const css = document.createElement("link");
  css.rel = "stylesheet";
  css.href = "/static/help.css";
  document.head.append(css);

  const icon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a8.5 8.5 0 0 1-12.4 7.6L3 21l1.4-5.6A8.5 8.5 0 1 1 21 12z"/><path d="M9.7 9.4a2.4 2.4 0 0 1 4.6.9c0 1.6-2.3 2-2.3 3.4"/><path d="M12 16.6h.01"/></svg>';
  let fab, panel, scrim, logEl, input, sendBtn, opened = false, busy = false;

  function build() {
    fab = document.createElement("button");
    fab.type = "button";
    fab.setAttribute("aria-haspopup", "dialog");
    fab.setAttribute("aria-controls", "hcPanel");
    fab.innerHTML = icon + "<span>Help</span>" + '<i class="hc-dot" hidden></i>';
    const dock = document.querySelector(".dock"); // the map page's floating dock
    if (dock) {
      fab.className = "chip hc-fab in-dock";
      dock.prepend(fab);
    } else {
      fab.className = "hc-fab hc-glass";
      document.body.append(fab);
    }
    if (lastError) fab.querySelector(".hc-dot").hidden = false;

    scrim = document.createElement("div");
    scrim.className = "hc-scrim";
    panel = document.createElement("section");
    panel.className = "hc-panel hc-glass";
    panel.id = "hcPanel";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "Help chat");
    panel.innerHTML =
      '<div class="hc-head"><div><b>Help</b><small>Questions about SABAGeo and how to use it</small></div>' +
      '<button class="hc-x" type="button" aria-label="Close help"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg></button></div>' +
      '<div class="hc-log" aria-live="polite"></div>' +
      '<form class="hc-form"><input type="text" maxlength="300" placeholder="Ask a question…" aria-label="Your question" autocomplete="off" enterkeyhint="send">' +
      '<button type="submit" aria-label="Send"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg></button></form>' +
      '<p class="hc-note">Answers are general help, not legal advice. Never type passwords or codes here.</p>';
    document.body.append(scrim, panel);
    logEl = panel.querySelector(".hc-log");
    input = panel.querySelector("input");
    sendBtn = panel.querySelector(".hc-form button");

    fab.addEventListener("click", () => (panel.classList.contains("open") ? close() : open()));
    panel.querySelector(".hc-x").addEventListener("click", close);
    scrim.addEventListener("click", close);
    panel.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
    panel.querySelector("form").addEventListener("submit", (e) => {
      e.preventDefault();
      const q = input.value.trim();
      if (q) ask({ question: q });
    });
    logEl.addEventListener("click", (e) => {
      const chip = e.target.closest(".hc-chip");
      if (chip && !busy) {
        if (chip.dataset.error) ask({ question: "I got this message: " + chip.dataset.error, error: chip.dataset.error });
        else ask({ question: chip.textContent, key: chip.dataset.key });
        return;
      }
      const rate = e.target.closest(".hc-rate button");
      if (rate) feedback(rate);
    });
  }

  function open() {
    panel.classList.add("open");
    scrim.classList.add("open");
    fab.setAttribute("aria-expanded", "true");
    fab.querySelector(".hc-dot").hidden = true;
    if (!opened) { opened = true; start(); }
    else if (lastError) errorChip();
    // on phones the keyboard would cover half the sheet, so only focus the box on bigger screens
    if (matchMedia("(min-width: 700px)").matches) setTimeout(() => input.focus(), 50);
  }
  function close() {
    if (!panel.classList.contains("open")) return;
    panel.classList.remove("open");
    scrim.classList.remove("open");
    fab.setAttribute("aria-expanded", "false");
    fab.focus();
  }

  function add(html, cls) {
    const el = document.createElement("div");
    el.className = cls;
    el.innerHTML = html;
    logEl.append(el);
    logEl.scrollTop = logEl.scrollHeight;
    return el;
  }
  const chips = (list) => list.length
    ? add(list.map((s) => '<button type="button" class="hc-chip" data-key="' + esc(s.key) + '">' + esc(s.question) + "</button>").join(""), "hc-chips")
    : null;

  // a chip that explains the error the page just showed (once per error)
  function errorChip() {
    if (!lastError || logEl.querySelector('.hc-chip.err[data-at="' + lastError.at + '"]')) return;
    add('<button type="button" class="hc-chip err" data-at="' + lastError.at + '" data-error="' + esc(lastError.msg) + '">' +
        "Explain this error: “" + esc(lastError.msg.length > 70 ? lastError.msg.slice(0, 70) + "…" : lastError.msg) + "”</button>", "hc-chips");
  }

  async function start() {
    const typing = add('<span class="hc-typing" aria-label="Loading"><i></i><i></i><i></i></span>', "hc-msg bot");
    let d = null;
    try {
      const r = await realFetch("/api/help/start?page=" + encodeURIComponent(location.pathname), { headers: headers() });
      if (r.ok) d = await r.json();
    } catch (e) {}
    typing.remove();
    if (!d) {
      add("Sorry, help can't load right now. Please check your connection and try again.", "hc-msg bot");
      opened = false;
      return;
    }
    add((d.name ? "Hi " + esc(d.name) + "! " : "Hi! ") + "What can I help you with? Tap a question or type your own.", "hc-msg bot");
    if (d.tips.length) add("<b>About your account</b>" + d.tips.map((t) => "<p>" + format(t) + "</p>").join(""), "hc-tips");
    errorChip();
    chips(d.suggestions);
  }

  async function ask(body) {
    if (busy) return;
    busy = true;
    sendBtn.disabled = true;
    add(esc(body.question), "hc-msg me");
    input.value = "";
    const typing = add('<span class="hc-typing" aria-label="Thinking"><i></i><i></i><i></i></span>', "hc-msg bot");
    body.page = location.pathname;
    try {
      const r = await realFetch("/api/help/ask", { method: "POST", headers: headers(), body: JSON.stringify(body) });
      const d = await r.json().catch(() => null);
      typing.remove();
      if (!r.ok) {
        add(esc(d && typeof d.detail === "string" ? d.detail : "Sorry, something went wrong. Please try again."), "hc-msg bot");
        return;
      }
      const msg = add(format(d.answer), "hc-msg bot");
      if (d.log && d.sure) {
        msg.insertAdjacentHTML("beforeend", '<div class="hc-rate" data-id="' + d.log.id + '" data-key="' + esc(d.log.key) + '">Helpful? ' +
          '<button type="button" data-up="1" aria-label="Yes, helpful">👍</button><button type="button" data-up="0" aria-label="No, not helpful">👎</button></div>');
      }
      if (body.error && lastError && body.error === lastError.msg) { lastError = null; store(ERR_KEY, null); }
      chips(d.related);
    } catch (e) {
      typing.remove();
      add("Sorry, I couldn't reach the server. Please check your connection and try again.", "hc-msg bot");
    } finally {
      busy = false;
      sendBtn.disabled = false;
    }
  }

  async function feedback(btn) {
    const box = btn.parentElement;
    const helpful = btn.dataset.up === "1";
    box.querySelectorAll("button").forEach((b) => (b.disabled = true));
    try {
      const r = await realFetch("/api/help/feedback", { method: "POST", headers: headers(),
        body: JSON.stringify({ id: Number(box.dataset.id), key: box.dataset.key, helpful }) });
      box.textContent = r.ok ? (helpful ? "Thanks!" : "Thanks. We'll use this to write a better answer.") : "Couldn't save that, sorry.";
    } catch (e) {
      box.textContent = "Couldn't save that, sorry.";
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", build);
  else build();
  window.HelpChat = { open: () => open(), close: () => close() };
})();
