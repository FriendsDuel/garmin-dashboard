// Garmin dashboard on Cloudflare.
// - Every hour a cron run pulls new data from Garmin and saves it (Store, below).
// - Opening the page just reads what's saved, so it loads instantly.
// - Everything sits behind APP_PASSWORD.
import { DurableObject } from "cloudflare:workers";
import PAGE from "./page.html";
import { GarminClient, AuthError, syncOnce } from "./garmin.js";
import { PROGRAM, HISTORY_DAYS, TIMEZONE } from "./settings.js";

const COOKIE = "gd_session";
const todayIn = (tz) => new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());

// ---------------------------------------------------------------- storage + sync
export class Store extends DurableObject {
  async load() { return (await this.ctx.storage.get("data")) || {}; }

  async sync(force) {
    if (this.running) return this.running; // one sync at a time
    this.running = (async () => {
      const data = await this.load();
      if (!this.env.GARMIN_PERSONAL_API_KEY) { data.meta = { ...(data.meta || {}), authError: "No Garmin key is set yet." }; await this.ctx.storage.put("data", data); return data; }
      const token = await this.ctx.storage.get("token");
      const client = new GarminClient({ key: this.env.GARMIN_PERSONAL_API_KEY, base: this.env.GARMIN_BASE, token, pauseMs: this.env.GARMIN_BASE ? 0 : 300 });
      try {
        await syncOnce(client, data, todayIn(TIMEZONE), HISTORY_DAYS);
      } catch (e) {
        data.meta = { ...(data.meta || {}), authError: e instanceof AuthError ? e.message : null, syncedAt: new Date().toISOString(),
          errors: e instanceof AuthError ? {} : { sync: e.message || String(e) } };
      }
      if (client.token) await this.ctx.storage.put("token", client.token);
      await this.ctx.storage.put("data", data);
      return data;
    })();
    try { return await this.running; } finally { this.running = null; }
  }

  async fetch(req) {
    const url = new URL(req.url);
    if (url.pathname === "/sync") { await this.sync(true); return new Response("ok"); }
    return new Response(JSON.stringify(await this.load()), { headers: { "content-type": "application/json" } });
  }
}
const store = (env) => env.STORE.get(env.STORE.idFromName("main"));

// ---------------------------------------------------------------- auth
async function sessionToken(env) {
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(env.APP_PASSWORD), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode("garmin-dashboard-session-v1"));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
function sameText(a, b) {
  a = String(a); b = String(b); let diff = a.length ^ b.length;
  for (let i = 0; i < Math.max(a.length, b.length); i++) diff |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0);
  return diff === 0;
}
async function authed(req, env) {
  const c = (req.headers.get("cookie") || "").split(/;\s*/).find((x) => x.startsWith(COOKIE + "="));
  return !!c && sameText(c.slice(COOKIE.length + 1), await sessionToken(env));
}

// ---------------------------------------------------------------- pages
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
function simplePage(title, body) {
  return new Response(`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(title)}</title><meta name="robots" content="noindex">
<style>:root{--bg:#EDF0EE;--s:#fff;--ink:#16242A;--m:#5E6E72;--l:#D3D9D7;--a:#0E6B66;--hr:#C4323C}
@media (prefers-color-scheme:dark){:root{--bg:#0F1A1D;--s:#172529;--ink:#E6EEEC;--m:#8FA3A6;--l:#2A3B40;--a:#3FB8AE;--hr:#F0626B}}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;display:grid;place-items:center;min-height:100vh;padding:16px;box-sizing:border-box}
.c{background:var(--s);border:1px solid var(--l);border-radius:14px;padding:22px;width:100%;max-width:380px;box-sizing:border-box}
h1{margin:0 0 6px;font-size:26px}p{color:var(--m);margin:0 0 14px}input{width:100%;box-sizing:border-box;padding:11px 12px;border:1px solid var(--l);border-radius:8px;background:var(--bg);color:var(--ink);font:inherit}
button{margin-top:12px;width:100%;padding:11px;border:0;border-radius:8px;background:var(--a);color:#fff;font:600 16px system-ui;cursor:pointer}.e{color:var(--hr)}</style></head>
<body><div class="c">${body}</div></body></html>`, { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
}
const loginPage = (err) => simplePage(PROGRAM.name, `<h1>${esc(PROGRAM.name)}</h1><p>Enter your password to see your Garmin data.</p>
<form method="post" action="/login"><input type="password" name="password" autocomplete="current-password" autofocus aria-label="Password">
${err ? '<p class="e" style="margin:8px 0 0">That password isn\'t right.</p>' : ""}<button>Unlock</button></form>`);

// ---------------------------------------------------------------- routes
export default {
  async fetch(req, env, ctx) {
    const url = new URL(req.url);
    if (!env.APP_PASSWORD) return simplePage("Setup", `<h1>Almost there</h1><p>Add a secret called <b>APP_PASSWORD</b> to this Worker in the Cloudflare dashboard (Settings → Variables and Secrets), then reload.</p>`);

    if (url.pathname === "/login" && req.method === "POST") {
      const form = await req.formData();
      if (!sameText(form.get("password") || "", env.APP_PASSWORD)) { await new Promise((r) => setTimeout(r, 800)); return loginPage(true); }
      return new Response(null, { status: 303, headers: { location: "/",
        "set-cookie": `${COOKIE}=${await sessionToken(env)}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=31536000` } });
    }
    if (url.pathname === "/logout") return new Response(null, { status: 303, headers: { location: "/", "set-cookie": `${COOKIE}=; Path=/; Max-Age=0; Secure; HttpOnly` } });
    if (!(await authed(req, env))) return url.pathname === "/" ? loginPage(false) : new Response("Not signed in", { status: 401 });

    if (url.pathname === "/refresh" && req.method === "POST") {
      await store(env).fetch("https://store/sync", { method: "POST" });
      return new Response(null, { status: 303, headers: { location: "/" } });
    }
    if (url.pathname === "/api/data") return store(env).fetch("https://store/data");
    if (url.pathname !== "/") return new Response("Not found", { status: 404 });

    let data = await (await store(env).fetch("https://store/data")).json();
    if (!data.meta?.syncedAt && env.GARMIN_PERSONAL_API_KEY) ctx.waitUntil(store(env).fetch("https://store/sync", { method: "POST" }));
    const payload = JSON.stringify({ program: PROGRAM, timezone: TIMEZONE, historyDays: HISTORY_DAYS, hasKey: !!env.GARMIN_PERSONAL_API_KEY, data })
      .replace(/</g, "\\u003c");
    return new Response(PAGE.replace("/*__DATA__*/null", payload), {
      headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store", "x-robots-tag": "noindex",
        "content-security-policy": "default-src 'none'; style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; script-src 'unsafe-inline'; img-src data:; form-action 'self'; base-uri 'none'; frame-ancestors 'none'" },
    });
  },

  async scheduled(_event, env, ctx) {
    ctx.waitUntil(store(env).fetch("https://store/sync", { method: "POST" }));
  },
};
