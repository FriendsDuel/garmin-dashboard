// Read-only client for Garmin's Personal API, plus the shaping of its responses into small records.
// The API key is exchanged for a 24-hour bearer token; the key itself is never logged or returned.

const TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token";
const TOKEN_MAX_AGE_MS = 20 * 3600 * 1000; // tokens last 24h; renew early
const RETRY = new Set([429, 502, 503, 504]);
const UA = "garmin-dashboard/2.0 (personal use)";

export class GarminError extends Error {}
export class AuthError extends GarminError {}
export class TooLarge extends GarminError {}   // Garmin answers HTTP 500, empty body, past ~256 KB
export class OutOfBudget extends GarminError {} // stop before Cloudflare's per-run request limit

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export class GarminClient {
  constructor({ key, base, token, budget = 40, pauseMs = 300 }) {
    this.key = String(key || "").trim().replace(/^["']|["']$/g, "");
    if (!this.key) throw new AuthError("No Garmin key is set.");
    this.base = base || "https://personal.connectapi.garmin.com";
    this.token = token || null; // {value, at}
    this.budget = budget;
    this.pauseMs = pauseMs;
    this.calls = 0;
  }

  spend() {
    if (this.calls >= this.budget) throw new OutOfBudget("request budget used up for this run");
    this.calls++;
  }

  async fetchToken() {
    this.spend();
    let res;
    try {
      res = await fetch(this.base + TOKEN_PATH, {
        method: "POST", body: "",
        headers: { Authorization: `ApiKey ${this.key}`, Accept: "*/*", "User-Agent": UA },
      });
    } catch (e) {
      throw new GarminError("Couldn't reach Garmin.");
    }
    if ([400, 401, 403, 404].includes(res.status))
      throw new AuthError(`Garmin rejected the key (HTTP ${res.status}). It may be mistyped, deleted or expired.`);
    if (!res.ok) throw new GarminError(`Token request failed (HTTP ${res.status}).`);
    let body = (await res.text()).trim(), tok = body;
    if (body.startsWith("{")) {
      try { const j = JSON.parse(body); tok = j.access_token || j.accessToken || j.token || ""; } catch { tok = ""; }
    }
    tok = String(tok).trim().replace(/^"|"$/g, "");
    if (!tok) throw new AuthError("Garmin returned an empty token. Check the key.");
    this.token = { value: tok, at: Date.now() };
    return tok;
  }

  async bearer(force = false) {
    if (force || !this.token || Date.now() - this.token.at > TOKEN_MAX_AGE_MS) await this.fetchToken();
    return this.token.value;
  }

  async get(path, params) {
    let url = this.base + path;
    if (params) url += "?" + new URLSearchParams(params).toString();
    let refreshed = false;
    for (let attempt = 0; attempt < 4; attempt++) {
      if (this.calls) await sleep(this.pauseMs);
      const tok = await this.bearer();
      this.spend();
      let res;
      try {
        res = await fetch(url, { headers: { Authorization: `Bearer ${tok}`, Accept: "application/json", "User-Agent": UA } });
      } catch {
        if (attempt < 3) { await sleep(2000 * (attempt + 1)); continue; }
        throw new GarminError("Couldn't reach Garmin.");
      }
      if (res.status === 401 && !refreshed) { refreshed = true; await this.bearer(true); continue; }
      if (RETRY.has(res.status) && attempt < 3) {
        const ra = Number(res.headers.get("Retry-After"));
        await sleep(Math.min(20000, (ra > 0 ? ra : 3 * (attempt + 1)) * 1000));
        continue;
      }
      if (res.status === 500) throw new TooLarge(path);
      if (res.status === 401 || res.status === 403) throw new AuthError(`Garmin refused access (HTTP ${res.status}).`);
      if (res.status === 404) return null;
      if (!res.ok) throw new GarminError(`${path} failed (HTTP ${res.status}).`);
      const text = await res.text();
      if (!text.trim()) return null;
      try { return JSON.parse(text); } catch { throw new GarminError(`${path} didn't return JSON.`); }
    }
    throw new GarminError(`${path} kept failing after several retries.`);
  }
}

// ---------- helpers ----------
export const iso = (d) => d.toISOString().slice(0, 10);
export const addDays = (s, n) => { const d = new Date(s + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() + n); return iso(d); };
const minDate = (a, b) => (a < b ? a : b);

function firstList(resp, ...keys) {
  if (resp == null) return [];
  if (Array.isArray(resp)) return resp;
  if (typeof resp === "object") {
    for (const k of keys) if (Array.isArray(resp[k])) return resp[k];
    for (const v of Object.values(resp)) if (Array.isArray(v) && (!v.length || typeof v[0] === "object")) return v;
  }
  return [];
}

// Fetch [a, b]; halve any range Garmin says is too large. A single broken day is skipped.
async function ranged(fetchRange, a, b) {
  try {
    return await fetchRange(a, b);
  } catch (e) {
    if (!(e instanceof TooLarge)) throw e;
    if (a >= b) return [];
    const span = Math.round((Date.parse(b) - Date.parse(a)) / 864e5);
    const mid = addDays(a, Math.floor(span / 2));
    return [...(await ranged(fetchRange, a, mid)), ...(await ranged(fetchRange, addDays(mid, 1), b))];
  }
}

// ---------- endpoints ----------
export async function activityPage(c, start, limit) {
  try {
    return firstList(await c.get("/activitylist-service/activities/search/activities", { start, limit }));
  } catch (e) {
    if (!(e instanceof TooLarge) || limit <= 1) { if (e instanceof TooLarge) return []; throw e; }
    const half = Math.floor(limit / 2);
    const first = await activityPage(c, start, half);
    if (first.length < half) return first;
    return first.concat(await activityPage(c, start + half, limit - half));
  }
}
export const dailyRange = (c, a, b) => ranged(async (x, y) =>
  firstList(await c.get("/usersummary-service/v2/dailysummaries", { startDate: x, endDate: y }), "data"), a, b);
export const sleepRange = (c, a, b) => ranged(async (x, y) =>
  firstList(await c.get("/sleep-service/sleep/dailySleepSummariesByDate", { startDate: x, endDate: y }),
    "dailySleepSummaries", "sleepSummaries", "data"), a, b);
export const hrvRange = (c, a, b) => ranged(async (x, y) =>
  firstList(await c.get(`/hrv-service/hrv/daily/${x}/${y}`), "hrvSummaries"), a, b);
export const weightRange = (c, a, b) => ranged(async (x, y) =>
  firstList(await c.get(`/weight-service/weight/range/${x}/${y}`, { includeAll: "true" }),
    "dailyWeightSummaries", "dateWeightList", "weightList"), a, b);

// ---------- shaping ----------
const num = (v) => { const f = typeof v === "number" ? v : parseFloat(v); return Number.isFinite(f) ? f : null; };
const dig = (o, path) => path.split(".").reduce((x, k) => (x && typeof x === "object" ? x[k] : undefined), o);
const r1 = (v) => (v == null ? null : Math.round(v * 10) / 10);
const DATE_KEYS = ["calendarDate", "summaryDate", "date", "startDate", "day"];
function dateOf(item) {
  for (const k of DATE_KEYS) { const v = item && item[k]; if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}/.test(v)) return v.slice(0, 10); }
  return null;
}

const CARDIO = ["cycl", "bik", "ride", "run", "walk", "hik", "swim", "row", "ellip", "stair", "hiit", "cardio", "ski", "paddl", "climb", "treadmill", "spin"];
const STRENGTH = ["strength", "weight", "lift", "crossfit"];
export function sportLabel(t) {
  t = String(t || "other").toLowerCase();
  if (STRENGTH.some((w) => t.includes(w))) return "Strength";
  if (["cycl", "bik", "ride", "spin"].some((w) => t.includes(w))) return "Cycling";
  if (["run", "treadmill"].some((w) => t.includes(w))) return "Running";
  if (["walk", "hik"].some((w) => t.includes(w))) return "Walking & hiking";
  if (t.includes("swim")) return "Swimming";
  const s = t.replace(/_/g, " "); return s.charAt(0).toUpperCase() + s.slice(1);
}
export function categoryOf(t) {
  t = String(t || "").toLowerCase();
  if (STRENGTH.some((w) => t.includes(w))) return "Strength";
  if (CARDIO.some((w) => t.includes(w))) return "Cardio";
  return "Other";
}

export function shapeActivity(a) {
  const start = a.startTimeLocal; if (!start) return null;
  const type = dig(a, "activityType.typeKey") || "other";
  return {
    id: String(a.activityId ?? `${start}|${a.activityName || ""}`),
    start: start.replace(" ", "T").slice(0, 16), date: start.slice(0, 10),
    name: a.activityName || sportLabel(type), sport: sportLabel(type), cat: categoryOf(type),
    km: r1((num(a.distance) || 0) / 1000), min: r1((num(a.duration) || 0) / 60),
    elev: num(a.elevationGain), hr: num(a.averageHR), maxhr: num(a.maxHR), kcal: num(a.calories),
    load: r1(num(a.activityTrainingLoad)), ate: num(a.aerobicTrainingEffect),
    z: [1, 2, 3, 4, 5].map((z) => r1((num(a[`hrTimeInZone_${z}`]) || 0) / 60)),
  };
}
export function shapeDaily(d) {
  const date = dateOf(d); if (!date) return null;
  const o = {
    date, steps: num(dig(d, "movement.steps.value")), rhr: num(dig(d, "heartRate.restingValue")),
    stress: num(dig(d, "stress.avgLevel")), bbMax: num(dig(d, "bodyBattery.maxValue")), bbMin: num(dig(d, "bodyBattery.minValue")),
    resp: num(dig(d, "respiration.avgValue")),
  };
  return Object.entries(o).some(([k, v]) => k !== "date" && v != null) ? o : null;
}
export function shapeSleep(s) {
  const date = dateOf(s), total = num(s.sleepTimeSeconds); if (!date || !total) return null;
  const h = (k) => r1((num(s[k]) || 0) / 3600);
  return { date, total: r1(total / 3600), deep: h("deepSleepSeconds"), light: h("lightSleepSeconds"), rem: h("remSleepSeconds"),
    awake: h("awakeSleepSeconds"), score: num(dig(s, "sleepScores.overall.value")) };
}
export function shapeHrv(h) {
  const date = dateOf(h), last = num(h.lastNightAvg); if (!date || last == null) return null;
  const b = h.baseline || {};
  return { date, last, wk: num(h.weeklyAvg), status: String(h.status || "").replace(/_/g, " ").toLowerCase(),
    lo: num(b.balancedLow), hi: num(b.balancedUpper) };
}
const toLb = (g) => (!g ? null : r1(g > 500 ? g / 453.59237 : (g * 1000) / 453.59237));
export function shapeWeights(w) {
  const out = [];
  let entries = w && typeof w.latestWeight === "object" && w.latestWeight ? [w.latestWeight] : [];
  if (!entries.length) entries = (Array.isArray(w.allWeightMetrics) ? w.allWeightMetrics : []).filter((m) => m && typeof m === "object");
  if (!entries.length) entries = [w];
  for (const e of entries) {
    const lb = toLb(num(e.weight));
    let date = dateOf(e) || dateOf(w);
    if (!date && num(e.date)) date = new Date(num(e.date)).toISOString().slice(0, 10);
    if (lb && date) out.push({ date, lb, fat: num(e.bodyFat), muscle: toLb(num(e.muscleMass)) });
  }
  return out;
}

// ---------- one sync run ----------
// Pulls the last week every time, then backfills older history chunk by chunk until the
// request budget for this run is spent. Progress is saved so the next run carries on.
export async function syncOnce(client, data, today, historyDays) {
  data.activities ||= {}; data.daily ||= {}; data.sleep ||= {}; data.hrv ||= {}; data.weight ||= {};
  data.meta ||= {};
  const m = data.meta, since = addDays(today, -(historyDays - 1)), recentFrom = addDays(today, -6);
  const put = (map, arr, shape) => { for (const x of arr) { const r = shape(x); if (r) map[r.date] = r; } };
  const putW = (arr) => { for (const x of arr) for (const r of shapeWeights(x)) data.weight[r.date] = r; };
  const putA = (arr) => { for (const x of arr) { const r = shapeActivity(x); if (r && r.date >= since) data.activities[r.id] = r; } };
  const errors = {};
  const section = async (name, fn) => {
    try { await fn(); } catch (e) {
      if (e instanceof AuthError || e instanceof OutOfBudget) throw e;
      errors[name] = e.message || String(e);
    }
  };

  // 1) recent week, every run
  await section("activities", async () => {
    for (let start = 0; ; start += 20) {
      const page = await activityPage(client, start, 20); putA(page);
      const oldest = (page[page.length - 1]?.startTimeLocal || "").slice(0, 10);
      if (page.length < 20 || (oldest && oldest < recentFrom) || start >= 100) break;
    }
  });
  await section("daily", async () => put(data.daily, await dailyRange(client, recentFrom, today), shapeDaily));
  await section("sleep", async () => put(data.sleep, await sleepRange(client, recentFrom, today), shapeSleep));
  await section("hrv", async () => put(data.hrv, await hrvRange(client, recentFrom, today), shapeHrv));
  await section("weight", async () => putW(await weightRange(client, recentFrom, today)));
  m.recentAt = new Date().toISOString();

  // 2) backfill older history, newest first, until done or out of budget
  try {
    if (!m.actDone) {
      m.actOffset ||= 0;
      while (!m.actDone) {
        const page = await activityPage(client, m.actOffset, 20); putA(page);
        const oldest = (page[page.length - 1]?.startTimeLocal || "").slice(0, 10);
        m.actOffset += 20;
        if (page.length < 20 || (oldest && oldest < since)) m.actDone = true;
      }
    }
    m.filledFrom ||= recentFrom; // days on or after this are already pulled
    while (m.filledFrom > since) {
      const b = addDays(m.filledFrom, -1), a = minDate(b, addDays(b, -29)) < since ? since : addDays(b, -29);
      put(data.daily, await dailyRange(client, a, b), shapeDaily);
      put(data.sleep, await sleepRange(client, a, b), shapeSleep);
      put(data.hrv, await hrvRange(client, a, b), shapeHrv);
      putW(await weightRange(client, a, b));
      m.filledFrom = a;
    }
  } catch (e) {
    if (!(e instanceof OutOfBudget)) {
      if (e instanceof AuthError) throw e;
      errors.history = e.message || String(e);
    }
  }

  // drop anything older than the history window
  for (const key of ["daily", "sleep", "hrv", "weight"]) for (const d of Object.keys(data[key])) if (d < since) delete data[key][d];
  for (const [id, a] of Object.entries(data.activities)) if (a.date < since) delete data.activities[id];

  m.syncedAt = new Date().toISOString();
  m.errors = errors;
  m.authError = null;
  m.historyComplete = !!m.actDone && m.filledFrom <= since;
  m.calls = client.calls;
  return data;
}
