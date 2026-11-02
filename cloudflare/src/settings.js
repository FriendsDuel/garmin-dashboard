// Your training program. Change these values, push, and the dashboard follows.
export const PROGRAM = {
  name: "10-week block",
  startDate: "2026-09-21", // a Monday
  weeks: 10,
  startWeightLb: 210.0,
  goalLossLb: 10.0,
  zone2TargetMin: 150, // minutes per week
  // Monday first. "Rest" days don't count toward the weekly session target.
  weeklyPlan: ["Upper body", "Lower body", "Cardio: Zone 2 + sprint", "Upper body", "Lower body", "Rest", "Rest"],
};

// How far back to keep history from Garmin.
export const HISTORY_DAYS = 365;

// Your time zone, so "today" and "this week" match your watch.
export const TIMEZONE = "America/Toronto";
