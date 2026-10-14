/* SABAGeo shared navigation for the content pages (not the map page).
   All page links live in PAGES below. Add a new page here once and it shows up
   in the top bar, the slide-out menu and the footer of every page.
   Loaded right after </header>, so the header is ready before page scripts run. */
(function () {
  const PAGES = [
    {
      group: "Registry",
      links: [
        ["Registry", "/registry"],
        ["Register plot", "/register-plot"],
        ["Parcel report", "/report"],
        ["Verify a title", "/verify"],
      ],
    },
    {
      group: "Payments",
      links: [
        ["Token payment", "/payments"],
        ["Receipt", "/receipt"],
      ],
    },
    {
      group: "About",
      links: [
        ["About us", "/about"],
        ["How it works", "/how-it-works"],
        ["Architecture", "/architecture"],
      ],
    },
    {
      group: "Admin",
      links: [["Dashboard", "/admin"]],
    },
  ];

  // /receipt/SABA-RCPT-... still counts as the Receipt page
  const path = location.pathname.replace(/\/+$/, "") || "/";
  const isOn = (href) => path === href || path.startsWith(href + "/");
  const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");
  const arrow =
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>';

  const header = document.querySelector("header.top");
  if (!header) return;

  /* ---- top bar: every page, grouped, current one highlighted ---- */
  const nav = header.querySelector("nav");
  if (nav) {
    nav.innerHTML = PAGES.map((g) =>
      g.links
        .map(([name, href]) =>
          isOn(href)
            ? `<a href="${href}" class="on" aria-current="page">${esc(name)}</a>`
            : `<a href="${href}">${esc(name)}</a>`,
        )
        .join(""),
    ).join('<span class="sx-sep" aria-hidden="true"></span>');

    // fade the edges when there are more links off to the side
    const fade = () => {
      const more = nav.scrollWidth - nav.clientWidth > 2;
      nav.classList.toggle("sx-fade-l", more && nav.scrollLeft > 2);
      nav.classList.toggle(
        "sx-fade-r",
        more && nav.scrollLeft < nav.scrollWidth - nav.clientWidth - 2,
      );
    };
    // bring the current page into view without scrolling the whole page
    const on = nav.querySelector("a.on");
    if (on) nav.scrollLeft = on.offsetLeft - nav.clientWidth / 2 + on.offsetWidth / 2;
    nav.addEventListener("scroll", fade, { passive: true });
    addEventListener("resize", fade);
    requestAnimationFrame(fade);
  }

  /* ---- menu button (the map page has one, now every page does) ---- */
  const btn = document.createElement("button");
  btn.className = "sx-menu";
  btn.type = "button";
  btn.setAttribute("aria-label", "Open menu");
  btn.setAttribute("aria-controls", "sxDrawer");
  btn.setAttribute("aria-expanded", "false");
  btn.innerHTML =
    '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h10"/></svg>';
  header.prepend(btn);

  /* ---- slide-out menu ---- */
  const scrim = document.createElement("div");
  scrim.className = "sx-scrim";
  const drawer = document.createElement("aside");
  drawer.className = "sx-drawer";
  drawer.id = "sxDrawer";
  drawer.setAttribute("aria-label", "Site menu");

  let i = 0;
  const body = [
    `<a class="sx-map" href="/" style="--i:${i++}"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2z"/><path d="M9 4v14M15 6v14"/></svg><span>Open the map</span></a>`,
  ];
  PAGES.forEach((g) => {
    body.push(`<p class="sx-label" style="--i:${i++}">${esc(g.group)}</p>`);
    g.links.forEach(([name, href]) => {
      const cur = isOn(href) ? ' class="sx-link on" aria-current="page"' : ' class="sx-link"';
      body.push(`<a${cur} href="${href}" style="--i:${i++}"><span>${esc(name)}</span>${arrow}</a>`);
    });
  });
  body.push(
    `<button class="sx-theme" type="button" style="--i:${i++}"><span>Theme</span><em></em></button>`,
  );

  drawer.innerHTML = `
    <div class="sx-head">
      <svg width="28" height="28" viewBox="0 0 44 44" aria-hidden="true"><polygon points="8,12 34,7 37,32 11,37" fill="rgba(217,164,65,.18)" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round"/><circle cx="8" cy="12" r="3.6" fill="#D9A441"/><circle cx="34" cy="7" r="3.6" fill="#D9A441"/><circle cx="37" cy="32" r="3.6" fill="#D9A441"/><circle cx="11" cy="37" r="3.6" fill="#D9A441"/></svg>
      <strong>SABAGeo</strong>
      <button class="sx-x" type="button" aria-label="Close menu"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg></button>
    </div>
    <div class="sx-body">${body.join("")}</div>`;
  document.body.append(scrim, drawer);

  const closeBtn = drawer.querySelector(".sx-x");
  const open = () => {
    drawer.classList.add("open");
    scrim.classList.add("open");
    btn.setAttribute("aria-expanded", "true");
    document.body.classList.add("sx-lock");
    closeBtn.focus();
  };
  const close = () => {
    if (!drawer.classList.contains("open")) return;
    drawer.classList.remove("open");
    scrim.classList.remove("open");
    btn.setAttribute("aria-expanded", "false");
    document.body.classList.remove("sx-lock");
    btn.focus();
  };
  btn.addEventListener("click", open);
  closeBtn.addEventListener("click", close);
  scrim.addEventListener("click", close);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") close();
  });

  // swipe left to close, same as the map page
  let sx = null;
  drawer.addEventListener("touchstart", (e) => (sx = e.touches[0].clientX), { passive: true });
  drawer.addEventListener("touchend", (e) => {
    if (sx !== null && e.changedTouches[0].clientX - sx < -60) close();
    sx = null;
  });

  /* ---- theme switch (same "theme" key the map page uses) ---- */
  const themeBtn = drawer.querySelector(".sx-theme");
  const showTheme = () => {
    const light = document.documentElement.dataset.theme === "light";
    themeBtn.querySelector("em").textContent = light ? "Light" : "Dark";
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = light ? "#F1F4F9" : "#0A1628";
  };
  themeBtn.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("theme", next);
    } catch (e) {}
    showTheme();
  });
  showTheme();

  /* ---- footer links (the footer is further down, so wait for it) ---- */
  document.addEventListener("DOMContentLoaded", () => {
    const footer = document.querySelector("body > footer");
    if (!footer) return;
    const links = document.createElement("div");
    links.className = "sx-foot";
    links.innerHTML = PAGES.map(
      (g) =>
        `<div><b>${esc(g.group)}</b>${g.links
          .map(([name, href]) => `<a href="${href}">${esc(name)}</a>`)
          .join("")}</div>`,
    ).join("");
    footer.prepend(links);
  });
})();
