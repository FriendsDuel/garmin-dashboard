"""Your training program. Change these values and the dashboard follows."""

from datetime import date

PROGRAM = {
    "name": "10-week block",
    "start_date": date(2026, 9, 21),   # a Monday
    "weeks": 10,
    "start_weight_lb": 210.0,
    "goal_loss_lb": 10.0,
    "zone2_target_min": 150,           # minutes per week
    # Monday first. "Rest" days don't count toward the weekly session target.
    "weekly_plan": [
        "Upper body",
        "Lower body",
        "Cardio: Zone 2 + sprint",
        "Upper body",
        "Lower body",
        "Rest",
        "Rest",
    ],
}

# How far back to pull from Garmin by default (the sidebar lets you change it).
DEFAULT_HISTORY = "12 months"
HISTORY_OPTIONS = {"12 months": 365, "2 years": 730, "5 years": 1825}

# How often the app re-pulls from Garmin on its own (seconds).
CACHE_SECONDS = 60 * 60

# Your time zone, so "today" and "this week" match your watch.
TIMEZONE = "America/Toronto"
