/* Admin login, shared by every page with admin tools (map, dashboard, payments, admin page).
   The login token lives in this browser tab only (sessionStorage) and lasts 12 hours at most. */
window.Staff = (function () {
  const get = (k) => { try { return sessionStorage.getItem(k) || ""; } catch (e) { return ""; } };
  const set = (k, v) => { try { v ? sessionStorage.setItem(k, v) : sessionStorage.removeItem(k); } catch (e) {} };
  const who = () => { try { return JSON.parse(get("staffWho") || "null"); } catch (e) { return null; } };

  return {
    token: () => get("staffToken"),
    headers: () => (get("staffToken") ? { "X-Staff-Token": get("staffToken") } : {}),
    who, // { username, name } of whoever logged in on this tab, or null
    save(d) { set("staffToken", d.token); set("staffWho", JSON.stringify({ username: d.username, name: d.name })); },
    clear() { set("staffToken", ""); set("staffWho", ""); },
    logout() {
      const t = get("staffToken");
      this.clear();
      if (t) return fetch("/api/staff/logout", { method: "POST", headers: { "X-Staff-Token": t } }).catch(() => {});
      return Promise.resolve();
    },
    // the login page, coming back here afterwards
    loginUrl: () => "/staff?next=" + encodeURIComponent(location.pathname + location.search),
  };
})();
