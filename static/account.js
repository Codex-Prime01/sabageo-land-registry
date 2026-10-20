/* Client account login, shared by My account, checkout and the menus.
   Kept in this browser for up to 7 days (like a shop account), until "Log out". */
window.Account = (function () {
  const get = (k) => { try { return localStorage.getItem(k) || ""; } catch (e) { return ""; } };
  const set = (k, v) => { try { v ? localStorage.setItem(k, v) : localStorage.removeItem(k); } catch (e) {} };
  const who = () => { try { return JSON.parse(get("accountWho") || "null"); } catch (e) { return null; } };

  return {
    token: () => get("accountToken"),
    headers: () => (get("accountToken") ? { "X-Account-Token": get("accountToken") } : {}),
    who, // { name, email } of whoever is logged in on this browser, or null
    save(d) { set("accountToken", d.token); set("accountWho", JSON.stringify({ name: d.name, email: d.email })); },
    clear() { set("accountToken", ""); set("accountWho", ""); },
    logout() {
      const t = get("accountToken");
      this.clear();
      if (t) return fetch("/api/account/logout", { method: "POST", headers: { "X-Account-Token": t } }).catch(() => {});
      return Promise.resolve();
    },
    // My account, coming back to this page afterwards; mode "signup" opens Create account first
    loginUrl: (mode) => "/account?next=" + encodeURIComponent(location.pathname + location.search) + (mode ? "&mode=" + mode : ""),
  };
})();
