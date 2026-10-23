"""Turn raw Garmin responses into tidy pandas tables. Missing fields and empty days are normal."""

from __future__ import annotations

from typing import Any

import pandas as pd

GRAMS_PER_LB = 453.59237
DATE_KEYS = ("calendarDate", "summaryDate", "date", "startDate", "day")


def dig(d: Any, path: str) -> Any:
    for part in path.split("."):
        if not isinstance(d, dict):
            return None
        d = d.get(part)
    return d


def num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f


def date_of(item: dict) -> pd.Timestamp | None:
    for k in DATE_KEYS:
        v = item.get(k)
        if isinstance(v, str) and len(v) >= 10:
            try:
                return pd.Timestamp(v[:10])
            except ValueError:
                continue
    return None


# ---------- sports ----------
CARDIO_WORDS = ("cycl", "bik", "ride", "run", "walk", "hik", "swim", "row", "ellip", "stair", "hiit",
                "cardio", "ski", "paddl", "climb", "treadmill", "spin")
STRENGTH_WORDS = ("strength", "weight", "lift", "crossfit")


def sport_label(type_key: str) -> str:
    t = (type_key or "other").lower()
    if any(w in t for w in STRENGTH_WORDS):
        return "Strength"
    if any(w in t for w in ("cycl", "bik", "ride", "spin")):
        return "Cycling"
    if any(w in t for w in ("run", "treadmill")):
        return "Running"
    if any(w in t for w in ("walk", "hik")):
        return "Walking & hiking"
    if "swim" in t:
        return "Swimming"
    return t.replace("_", " ").capitalize()


def category(type_key: str) -> str:
    t = (type_key or "").lower()
    if any(w in t for w in STRENGTH_WORDS):
        return "Strength"
    if any(w in t for w in CARDIO_WORDS):
        return "Cardio"
    return "Other"


# ---------- tables ----------
def activities_df(raw: list[dict]) -> pd.DataFrame:
    rows = []
    for a in raw or []:
        start = a.get("startTimeLocal")
        if not start:
            continue
        type_key = dig(a, "activityType.typeKey") or "other"
        row = {
            "start": pd.Timestamp(start),
            "date": pd.Timestamp(start[:10]),
            "name": a.get("activityName") or sport_label(type_key),
            "type_key": type_key,
            "sport": sport_label(type_key),
            "category": category(type_key),
            "distance_km": (num(a.get("distance")) or 0) / 1000,
            "duration_min": (num(a.get("duration")) or 0) / 60,
            "elevation_m": num(a.get("elevationGain")),
            "avg_hr": num(a.get("averageHR")),
            "max_hr": num(a.get("maxHR")),
            "calories": num(a.get("calories")),
            "load": num(a.get("activityTrainingLoad")),
            "aerobic_te": num(a.get("aerobicTrainingEffect")),
        }
        for z in range(1, 6):
            row[f"z{z}_min"] = (num(a.get(f"hrTimeInZone_{z}")) or 0) / 60
        rows.append(row)
    cols = ["start", "date", "name", "type_key", "sport", "category", "distance_km", "duration_min",
            "elevation_m", "avg_hr", "max_hr", "calories", "load", "aerobic_te"] + [f"z{z}_min" for z in range(1, 6)]
    df = pd.DataFrame(rows, columns=cols)
    return df.drop_duplicates(subset=["start", "name"]).sort_values("start").reset_index(drop=True)


def daily_df(raw: list[dict]) -> pd.DataFrame:
    rows = []
    for d in raw or []:
        day = date_of(d)
        if day is None:
            continue
        rows.append({
            "date": day,
            "steps": num(dig(d, "movement.steps.value")),
            "rhr": num(dig(d, "heartRate.restingValue")),
            "stress": num(dig(d, "stress.avgLevel")),
            "bb_max": num(dig(d, "bodyBattery.maxValue")),
            "bb_min": num(dig(d, "bodyBattery.minValue")),
            "im_moderate": num(dig(d, "intensityMinutes.moderate")),
            "im_vigorous": num(dig(d, "intensityMinutes.vigorous")),
            "respiration": num(dig(d, "respiration.avgValue")),
        })
    df = pd.DataFrame(rows, columns=["date", "steps", "rhr", "stress", "bb_max", "bb_min",
                                     "im_moderate", "im_vigorous", "respiration"])
    df = df.dropna(how="all", subset=df.columns[1:])
    return df.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)


def sleep_df(raw: list[dict]) -> pd.DataFrame:
    rows = []
    for s in raw or []:
        day = date_of(s)
        total = num(s.get("sleepTimeSeconds"))
        if day is None or not total:
            continue
        h = lambda k: (num(s.get(k)) or 0) / 3600  # noqa: E731
        rows.append({
            "date": day, "total_h": total / 3600,
            "deep_h": h("deepSleepSeconds"), "light_h": h("lightSleepSeconds"),
            "rem_h": h("remSleepSeconds"), "awake_h": h("awakeSleepSeconds"),
            "score": num(dig(s, "sleepScores.overall.value")),
        })
    df = pd.DataFrame(rows, columns=["date", "total_h", "deep_h", "light_h", "rem_h", "awake_h", "score"])
    return df.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)


def hrv_df(raw: list[dict]) -> pd.DataFrame:
    rows = []
    for h in raw or []:
        day = date_of(h)
        last = num(h.get("lastNightAvg"))
        if day is None or last is None:
            continue
        base = h.get("baseline") or {}
        rows.append({
            "date": day, "last_night": last, "weekly_avg": num(h.get("weeklyAvg")),
            "status": (h.get("status") or "").replace("_", " ").capitalize(),
            "base_low": num(base.get("balancedLow")), "base_high": num(base.get("balancedUpper")),
        })
    df = pd.DataFrame(rows, columns=["date", "last_night", "weekly_avg", "status", "base_low", "base_high"])
    return df.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)


def _grams_to_lb(v: float | None) -> float | None:
    if not v:
        return None
    # Garmin sends grams; guard against a kg value just in case.
    return v / GRAMS_PER_LB if v > 500 else v * 1000 / GRAMS_PER_LB


def weight_df(raw: list[dict]) -> pd.DataFrame:
    rows = []
    for w in raw or []:
        # A daily summary holds latestWeight plus allWeightMetrics; a flat list holds weight directly.
        entries = [w.get("latestWeight")] if isinstance(w.get("latestWeight"), dict) else []
        if not entries:
            entries = [m for m in (w.get("allWeightMetrics") or []) if isinstance(m, dict)] or [w]
        for e in entries:
            lb = _grams_to_lb(num(e.get("weight")))
            day = date_of(e) or date_of(w)
            if day is None and num(e.get("date")):
                day = pd.Timestamp(int(num(e["date"])), unit="ms").normalize()
            if lb and day is not None:
                rows.append({"date": day, "weight_lb": lb})
    df = pd.DataFrame(rows, columns=["date", "weight_lb"])
    return df.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)


def build(raw: dict) -> dict[str, pd.DataFrame]:
    return {
        "activities": activities_df(raw.get("activities")),
        "daily": daily_df(raw.get("daily")),
        "sleep": sleep_df(raw.get("sleep")),
        "hrv": hrv_df(raw.get("hrv")),
        "weight": weight_df(raw.get("weight")),
    }
