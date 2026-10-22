"""Made-up sample data in Garmin's response shape, shown only until your key is added."""

from __future__ import annotations

import math
import random
from datetime import date, datetime, timedelta

from settings import PROGRAM


def sample(start: date, end: date) -> dict:
    rnd = random.Random(7)
    acts, daily, sleep, hrv, weight = [], [], [], [], []
    block_start = PROGRAM["start_date"]
    d = start
    while d <= end:
        i = (d - start).days
        dow = d.weekday()
        plan = PROGRAM["weekly_plan"][dow]
        fit = i / max(1, (end - start).days)
        if not plan.lower().startswith("rest") and rnd.random() < 0.88:
            t = datetime(d.year, d.month, d.day, 7, rnd.randint(0, 20))
            if "cardio" in plan.lower():
                dur = rnd.randint(50, 70) * 60
                z2 = dur * rnd.uniform(0.55, 0.75)
                acts.append(_act(t, "indoor_cycling", "Zone 2 + sprint ride", dur, rnd.uniform(24, 32) * 1000,
                                 rnd.randint(125, 138) - 6 * fit, rnd.randint(158, 172), rnd.randint(520, 700),
                                 rnd.randint(85, 140), rnd.uniform(3.0, 3.8),
                                 [dur * 0.08, z2, dur - z2 - dur * 0.18, dur * 0.07, dur * 0.03]))
            else:
                dur = rnd.randint(55, 80) * 60
                acts.append(_act(t, "strength_training", plan, dur, 0, rnd.randint(102, 118), rnd.randint(145, 160),
                                 rnd.randint(330, 480), rnd.randint(40, 75), rnd.uniform(2.0, 2.8),
                                 [dur * 0.45, dur * 0.35, dur * 0.15, dur * 0.05, 0]))
        if dow == 5 and rnd.random() < 0.6:
            t = datetime(d.year, d.month, d.day, 9, 30)
            dur = rnd.randint(70, 110) * 60
            acts.append(_act(t, "road_biking", "Saturday ride", dur, rnd.uniform(35, 60) * 1000,
                             rnd.randint(128, 140), rnd.randint(160, 175), rnd.randint(700, 1100),
                             rnd.randint(110, 190), rnd.uniform(3.2, 4.2),
                             [dur * 0.1, dur * 0.6, dur * 0.22, dur * 0.06, dur * 0.02], elev=rnd.uniform(200, 650)))
        ds = d.isoformat()
        rhr = 58 - 4 * fit + rnd.gauss(0, 1.4)
        daily.append({"calendarDate": ds, "movement": {"steps": {"value": rnd.randint(6000, 14000)}},
                      "heartRate": {"restingValue": round(rhr)}, "stress": {"avgLevel": rnd.randint(22, 40)},
                      "bodyBattery": {"maxValue": rnd.randint(70, 98), "minValue": rnd.randint(10, 30)},
                      "intensityMinutes": {"moderate": rnd.randint(10, 60), "vigorous": rnd.randint(0, 40)},
                      "respiration": {"avgValue": round(rnd.uniform(13, 15.5), 1)}})
        if rnd.random() < 0.93:
            total = rnd.uniform(6.2, 8.1) * 3600
            deep, rem, awake = total * rnd.uniform(.14, .22), total * rnd.uniform(.18, .25), rnd.uniform(600, 2400)
            sleep.append({"calendarDate": ds, "sleepTimeSeconds": total, "deepSleepSeconds": deep,
                          "remSleepSeconds": rem, "lightSleepSeconds": total - deep - rem, "awakeSleepSeconds": awake,
                          "sleepScores": {"overall": {"value": rnd.randint(62, 92)}}})
        h = 48 + 8 * fit + rnd.gauss(0, 4)
        hrv.append({"calendarDate": ds, "lastNightAvg": round(h), "weeklyAvg": round(48 + 8 * fit),
                    "status": "BALANCED", "baseline": {"balancedLow": 44, "balancedUpper": 60}})
        if d >= block_start and rnd.random() < 0.7:
            days_in = (d - block_start).days
            lb = PROGRAM["start_weight_lb"] - 0.85 * days_in / 7 + 1.1 * math.sin(i) + rnd.gauss(0, .5)
            weight.append({"summaryDate": ds, "latestWeight": {"weight": lb * 453.59237}})
        d += timedelta(days=1)
    acts.sort(key=lambda a: a["startTimeLocal"], reverse=True)
    return {"pulled_at": datetime.now().isoformat(timespec="seconds"), "start": start.isoformat(),
            "end": end.isoformat(), "errors": {}, "activities": acts, "daily": daily, "sleep": sleep,
            "hrv": hrv, "weight": weight, "zones": None, "fitness_age": None}


def _act(t, key, name, dur, dist, avg, mx, cal, load, te, zones, elev=None):
    a = {"startTimeLocal": t.strftime("%Y-%m-%d %H:%M:%S"), "activityType": {"typeKey": key},
         "activityName": name, "duration": dur, "distance": dist, "elevationGain": elev,
         "averageHR": avg, "maxHR": mx, "calories": cal, "activityTrainingLoad": load,
         "aerobicTrainingEffect": round(te, 1)}
    for z, s in enumerate(zones, 1):
        a[f"hrTimeInZone_{z}"] = max(0, s)
    return a
