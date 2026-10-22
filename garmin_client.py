"""Read-only client for Garmin's Personal API, using only Python's standard library.

The Personal API key is exchanged for a 24-hour bearer token. The key itself is
never logged, printed or included in error messages.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from typing import Any, Callable, Iterable

BASE_URL = "https://personal.connectapi.garmin.com"
TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"
TOKEN_MAX_AGE = 20 * 3600          # tokens last 24h; renew a little early
RETRY_STATUSES = {429, 502, 503, 504}
USER_AGENT = "garmin-dashboard/1.0 (personal use)"

Progress = Callable[[str], None]


class GarminError(Exception):
    """Any problem talking to Garmin."""


class AuthError(GarminError):
    """The key was rejected: missing, mistyped, deleted or expired."""


class TooLarge(GarminError):
    """Garmin returns HTTP 500 with an empty body when a response would exceed ~256 KB."""


class GarminClient:
    def __init__(self, api_key: str, pause: float = 0.35, timeout: float = 40.0):
        key = (api_key or "").strip().strip('"').strip("'")
        if not key:
            raise AuthError("No Garmin Personal API key is set.")
        self._key = key
        self._token: str | None = None
        self._token_at = 0.0
        self.pause = pause
        self.timeout = timeout
        self.calls = 0

    # ---------- auth ----------
    def _fetch_token(self) -> str:
        req = urllib.request.Request(
            BASE_URL + TOKEN_PATH,
            data=b"",
            method="POST",
            headers={"Authorization": f"ApiKey {self._key}", "Accept": "*/*", "User-Agent": USER_AGENT},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", "replace").strip()
        except urllib.error.HTTPError as e:
            if e.code in (400, 401, 403, 404):
                raise AuthError(
                    f"Garmin rejected the Personal API key (HTTP {e.code}). "
                    "It may be mistyped, deleted or expired."
                ) from None
            raise GarminError(f"Token request failed (HTTP {e.code}).") from None
        except urllib.error.URLError as e:
            raise GarminError(f"Couldn't reach Garmin: {e.reason}") from None

        token = body
        if body.startswith("{"):
            try:
                data = json.loads(body)
                token = data.get("access_token") or data.get("accessToken") or data.get("token") or ""
            except ValueError:
                token = ""
        token = token.strip().strip('"')
        if not token:
            raise AuthError("Garmin returned an empty token. Check the key.")
        return token

    def token(self, force: bool = False) -> str:
        if force or not self._token or time.time() - self._token_at > TOKEN_MAX_AGE:
            self._token = self._fetch_token()
            self._token_at = time.time()
        return self._token

    # ---------- requests ----------
    def get(self, path: str, params: dict | None = None) -> Any:
        url = BASE_URL + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        refreshed = False
        for attempt in range(5):
            if self.calls:
                time.sleep(self.pause)
            self.calls += 1
            req = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"Bearer {self.token()}",
                    "Accept": "application/json",
                    "User-Agent": USER_AGENT,
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read()
                if not raw.strip():
                    return None
                return json.loads(raw)
            except urllib.error.HTTPError as e:
                if e.code == 401 and not refreshed:
                    refreshed = True
                    self.token(force=True)
                    continue
                if e.code in RETRY_STATUSES and attempt < 4:
                    retry_after = e.headers.get("Retry-After") if e.headers else None
                    wait = float(retry_after) if retry_after and retry_after.isdigit() else 3 * (attempt + 1)
                    time.sleep(min(wait, 30))
                    continue
                if e.code == 500:
                    raise TooLarge(path) from None
                if e.code in (401, 403):
                    raise AuthError(f"Garmin refused access (HTTP {e.code}).") from None
                if e.code == 404:
                    return None
                raise GarminError(f"{path} failed (HTTP {e.code}).") from None
            except urllib.error.URLError as e:
                if attempt < 4:
                    time.sleep(3 * (attempt + 1))
                    continue
                raise GarminError(f"Couldn't reach Garmin: {e.reason}") from None
            except ValueError:
                raise GarminError(f"{path} returned something that isn't JSON.") from None
        raise GarminError(f"{path} kept failing after several retries.")


# ---------- helpers ----------
def iso(d: date) -> str:
    return d.isoformat()


def date_chunks(start: date, end: date, days: int) -> Iterable[tuple[date, date]]:
    cur = start
    while cur <= end:
        stop = min(end, cur + timedelta(days=days - 1))
        yield cur, stop
        cur = stop + timedelta(days=1)


def first_list(resp: Any, *keys: str) -> list:
    """Return the item list from a response that may be a list or a dict wrapping one."""
    if resp is None:
        return []
    if isinstance(resp, list):
        return resp
    if isinstance(resp, dict):
        for k in keys:
            v = resp.get(k)
            if isinstance(v, list):
                return v
        for v in resp.values():
            if isinstance(v, list) and (not v or isinstance(v[0], dict)):
                return v
    return []


def ranged(fetch: Callable[[date, date], list], start: date, end: date, chunk_days: int) -> list:
    """Fetch [start, end] in chunks; halve any chunk that comes back too large."""
    out: list = []

    def run(a: date, b: date) -> None:
        try:
            out.extend(fetch(a, b))
        except TooLarge:
            if a >= b:
                return  # a single day is too big or broken; skip it rather than crash
            mid = a + (b - a) // 2
            run(a, mid)
            run(mid + timedelta(days=1), b)

    for a, b in date_chunks(start, end, chunk_days):
        run(a, b)
    return out


# ---------- endpoints ----------
def activities(client: GarminClient, since: date, progress: Progress | None = None) -> list[dict]:
    """All activities on or after `since`, newest first."""
    out: list[dict] = []
    start, page = 0, 20

    def get_page(s: int, n: int) -> list[dict]:
        try:
            return first_list(client.get(
                "/activitylist-service/activities/search/activities", {"start": s, "limit": n}
            ))
        except TooLarge:
            if n <= 1:
                return []
            half = n // 2
            first = get_page(s, half)
            if len(first) < half:
                return first
            return first + get_page(s + half, n - half)

    while True:
        items = get_page(start, page)
        out.extend(items)
        if progress:
            progress(f"Activities: {len(out)} so far")
        if len(items) < page:
            break
        oldest = (items[-1].get("startTimeLocal") or "")[:10]
        if oldest and oldest < iso(since):
            break
        start += page
    return [a for a in out if (a.get("startTimeLocal") or "")[:10] >= iso(since)]


def daily_summaries(client: GarminClient, start: date, end: date) -> list[dict]:
    def fetch(a: date, b: date) -> list:
        return first_list(client.get(
            "/usersummary-service/v2/dailysummaries", {"startDate": iso(a), "endDate": iso(b)}
        ), "data")
    return ranged(fetch, start, end, 60)


def sleep(client: GarminClient, start: date, end: date) -> list[dict]:
    def fetch(a: date, b: date) -> list:
        return first_list(client.get(
            "/sleep-service/sleep/dailySleepSummariesByDate", {"startDate": iso(a), "endDate": iso(b)}
        ), "dailySleepSummaries", "sleepSummaries", "data")
    return ranged(fetch, start, end, 31)


def hrv(client: GarminClient, start: date, end: date) -> list[dict]:
    def fetch(a: date, b: date) -> list:
        return first_list(client.get(f"/hrv-service/hrv/daily/{iso(a)}/{iso(b)}"), "hrvSummaries")
    return ranged(fetch, start, end, 366)


def weight(client: GarminClient, start: date, end: date) -> list[dict]:
    def fetch(a: date, b: date) -> list:
        return first_list(client.get(f"/weight-service/weight/range/{iso(a)}/{iso(b)}"), "dailyWeightSummaries")
    return ranged(fetch, start, end, 366)


def heart_rate_zones(client: GarminClient) -> Any:
    try:
        return client.get("/biometric-service/heartRateZones/v2")
    except GarminError:
        return None


def fitness_age(client: GarminClient, day: date) -> Any:
    try:
        return client.get(f"/fitnessage-service/fitnessage/v2/{iso(day)}")
    except GarminError:
        return None


def pull_all(client: GarminClient, start: date, end: date, progress: Progress | None = None) -> dict:
    """Everything the dashboard needs. Each section fails on its own without stopping the rest."""
    say = progress or (lambda _m: None)
    data: dict[str, Any] = {"pulled_at": datetime.now().isoformat(timespec="seconds"),
                            "start": iso(start), "end": iso(end), "errors": {}}

    def section(name: str, label: str, fn: Callable[[], Any]) -> None:
        say(label)
        try:
            data[name] = fn()
        except AuthError:
            raise
        except GarminError as e:
            data[name] = [] if name not in ("zones", "fitness_age") else None
            data["errors"][name] = str(e)

    section("activities", "Activities", lambda: activities(client, start, say))
    section("daily", "Daily summaries", lambda: daily_summaries(client, start, end))
    section("sleep", "Sleep", lambda: sleep(client, start, end))
    section("hrv", "HRV", lambda: hrv(client, start, end))
    section("weight", "Weigh-ins", lambda: weight(client, start, end))
    section("zones", "Heart rate zones", lambda: heart_rate_zones(client))
    section("fitness_age", "Fitness age", lambda: fitness_age(client, end))
    return data
