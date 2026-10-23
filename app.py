"""Garmin training dashboard for Nate's 10-week block. Run with:  streamlit run app.py"""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import altair as alt
import pandas as pd
import streamlit as st

import demo
import garmin_client as gc
import transform
from settings import CACHE_SECONDS, DEFAULT_HISTORY, HISTORY_OPTIONS, PROGRAM, TIMEZONE

st.set_page_config(page_title="10-Week Block · Garmin", page_icon="⌚", layout="wide",
                   initial_sidebar_state="collapsed")

# ---------------------------------------------------------------- look
DARK = (getattr(st.context, "theme", None) or {}).get("type") == "dark"
C = {
    "accent": "#3FB8AE" if DARK else "#0E6B66",
    "accent_soft": "#1D3B3B" if DARK else "#D5E9E6",
    "hr": "#F0626B" if DARK else "#C4323C",
    "amber": "#F2B233" if DARK else "#A86F00",
    "pr": "#B596F0" if DARK else "#6A3FB5",
    "muted": "#8FA3A6" if DARK else "#5E6E72",
    "line": "#2A3B40" if DARK else "#D3D9D7",
    "surface": "#172529" if DARK else "#FFFFFF",
    "ink": "#E6EEEC" if DARK else "#16242A",
}
CAT_COLORS = {"Strength": C["accent"], "Cardio": C["amber"], "Other": C["muted"]}
COND = "'Barlow Condensed', 'Arial Narrow', sans-serif"

st.markdown(f"""
<style>
.block-container {{ padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1180px; }}
h1, h2, h3 {{ font-family: {COND} !important; letter-spacing: -.01em; }}
h1 {{ font-size: clamp(2.4rem, 6vw, 3.6rem) !important; line-height: .95 !important; padding-bottom: .1rem !important; }}
h2 {{ font-size: 1.7rem !important; padding-top: 1.2rem !important; }}
h3 {{ font-size: 1.25rem !important; }}
.sub {{ color: {C['muted']}; margin: .2rem 0 1rem; }}
.tile {{ background: {C['surface']}; border: 1px solid {C['line']}; border-radius: 14px; padding: 14px 16px; height: 100%; }}
.tile .lab {{ color: {C['muted']}; font-size: .85rem; }}
.tile .val {{ font-family: {COND}; font-weight: 700; font-size: 2.3rem; line-height: 1.05; color: {C['ink']}; }}
.tile .val.good {{ color: {C['accent']}; }}
.tile .val.warn {{ color: {C['amber']}; }}
.tile .val.bad {{ color: {C['hr']}; }}
.tile .note {{ color: {C['muted']}; font-size: .85rem; margin-top: 2px; }}
.meter {{ height: 6px; border-radius: 3px; background: {C['line']}; margin-top: 8px; overflow: hidden; }}
.meter i {{ display: block; height: 100%; background: {C['accent']}; }}
.banner {{ background: {C['accent_soft']}; border-radius: 12px; padding: 12px 16px; margin: .4rem 0 1rem; color: {C['ink']}; }}
.rec {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; }}
.small {{ color: {C['muted']}; font-size: .85rem; }}
@media (max-width: 640px) {{ .tile .val {{ font-size: 1.9rem; }} .tile {{ padding: 12px 13px; }} }}
</style>""", unsafe_allow_html=True)


def tile(label: str, value: str, note: str = "", tone: str = "", meter: float | None = None) -> str:
    m = f'<div class="meter"><i style="width:{max(0, min(100, meter)):.0f}%"></i></div>' if meter is not None else ""
    return (f'<div class="tile"><div class="lab">{label}</div><div class="val {tone}">{value}</div>'
            f'<div class="note">{note}</div>{m}</div>')


def show_tiles(tiles: list[str]) -> None:
    for col, t in zip(st.columns(len(tiles)), tiles):
        col.markdown(t, unsafe_allow_html=True)


def chart(c: alt.Chart, height: int = 240) -> None:
    st.altair_chart(c.properties(height=height).configure_view(strokeWidth=0)
                    .configure_axis(labelFontSize=12, titleFontSize=12, grid=True, gridOpacity=.35)
                    .configure_legend(orient="top", title=None, labelFontSize=12),
                    width="stretch", theme="streamlit")


def fmt_min(m: float) -> str:
    m = int(round(m or 0))
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m} min"


# ---------------------------------------------------------------- key & data
def read_key() -> str:
    try:
        v = st.secrets.get("GARMIN_PERSONAL_API_KEY", "")
        if v:
            return str(v)
    except Exception:  # no secrets file locally
        pass
    if os.environ.get("GARMIN_PERSONAL_API_KEY"):
        return os.environ["GARMIN_PERSONAL_API_KEY"]
    env = Path(__file__).with_name(".env.local")
    if env.exists():
        for line in env.read_text().splitlines():
            if line.strip().startswith("GARMIN_PERSONAL_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


@st.cache_resource(show_spinner=False)
def get_client(fingerprint: str, _key: str) -> gc.GarminClient:
    return gc.GarminClient(_key)


@st.cache_data(ttl=CACHE_SECONDS, show_spinner=False, max_entries=4)
def pull(fingerprint: str, start_iso: str, end_iso: str, _client: gc.GarminClient) -> dict:
    return gc.pull_all(_client, date.fromisoformat(start_iso), date.fromisoformat(end_iso))


def password_gate() -> None:
    """If APP_PASSWORD is set in Secrets, nothing loads until it's entered."""
    try:
        expected = str(st.secrets.get("APP_PASSWORD", ""))
    except Exception:
        expected = ""
    if not expected or st.session_state.get("unlocked"):
        return
    st.markdown(f"# {PROGRAM['name']}")
    with st.form("unlock"):
        pw = st.text_input("Password", type="password", autocomplete="current-password")
        ok = st.form_submit_button("Unlock", type="primary")
    if ok:
        if hmac.compare_digest(pw.encode(), expected.encode()):
            st.session_state["unlocked"] = True
            st.rerun()
        st.error("That password isn't right.")
    st.stop()


password_gate()

TODAY = datetime.now(ZoneInfo(TIMEZONE)).date()

with st.sidebar:
    st.markdown("### Data")
    history = st.selectbox("History to pull", list(HISTORY_OPTIONS), index=list(HISTORY_OPTIONS).index(DEFAULT_HISTORY),
                           help="Longer history takes a little longer to load the first time.")
    if st.button("Refresh from Garmin now", width="stretch"):
        pull.clear()
        st.rerun()

pull_start = TODAY - timedelta(days=HISTORY_OPTIONS[history] - 1)
key = read_key()
is_demo = not key
if is_demo:
    raw = demo.sample(pull_start, TODAY)
else:
    fp = hashlib.sha256(key.encode()).hexdigest()[:16]
    try:
        with st.spinner(f"Pulling {history.lower()} from Garmin… the first load takes a minute or two."):
            raw = pull(fp, pull_start.isoformat(), TODAY.isoformat(), get_client(fp, key))
    except gc.AuthError as e:
        st.error(f"**Garmin didn't accept your key.** {e}  \nCreate a new key on the "
                 "[Personal API Key page](https://connect.garmin.com/app/settings/personalApiToken), "
                 "then paste it into this app's **Settings → Secrets** as `GARMIN_PERSONAL_API_KEY`.")
        st.stop()
    except gc.GarminError as e:
        st.error(f"Couldn't load data from Garmin: {e} Try **Refresh from Garmin now** in a minute.")
        st.stop()

D = transform.build(raw)
A, DAILY, SLEEP, HRV, WEIGHT = D["activities"], D["daily"], D["sleep"], D["hrv"], D["weight"]


def week_start(s: pd.Series) -> pd.Series:
    return s - pd.to_timedelta(s.dt.weekday, unit="D")


if not A.empty:
    A["week"] = week_start(A["date"])

# ---------------------------------------------------------------- header
P = PROGRAM
b_start = P["start_date"]
b_end = b_start + timedelta(days=7 * P["weeks"] - 1)
day_in = (TODAY - b_start).days
week_no = day_in // 7 + 1
planned = sum(1 for p in P["weekly_plan"] if not p.lower().startswith("rest")) or 1

st.markdown(f"# {P['name']}")
st.markdown(f'<p class="sub">Lose {P["goal_loss_lb"]:g} lb over {P["weeks"]} weeks · '
            f'{b_start:%b %-d} to {b_end:%b %-d} · live from Garmin</p>', unsafe_allow_html=True)
if is_demo:
    st.markdown('<div class="banner"><b>Sample data.</b> This is made-up data so you can see the layout. '
                'Add your Garmin key in this app\'s <b>Settings → Secrets</b> and your own numbers replace it.</div>',
                unsafe_allow_html=True)
for name, err in (raw.get("errors") or {}).items():
    st.warning(f"Couldn't load {name}: {err}")

# 7-day trailing weight average over each weigh-in
if not WEIGHT.empty:
    W = WEIGHT.copy()
    W["avg7"] = [W.loc[(W["date"] <= d) & (W["date"] > d - pd.Timedelta(days=7)), "weight_lb"].mean() for d in W["date"]]
else:
    W = WEIGHT.assign(avg7=pd.Series(dtype=float))
W_block = W[W["date"] >= pd.Timestamp(b_start)]


def goal_pace(d: date) -> float:
    frac = min(max((d - b_start).days / (b_end - b_start).days, 0), 1)
    return P["start_weight_lb"] - P["goal_loss_lb"] * frac


this_monday = pd.Timestamp(TODAY - timedelta(days=TODAY.weekday()))
A_week = A[A["week"] == this_monday] if not A.empty else A
z2_week = A_week["z2_min"].sum() if not A_week.empty else 0
sessions_week = len(A_week)

if day_in < 0:
    t1 = tile("Block", "Not started", f"starts {b_start:%a %b %-d}")
elif day_in >= 7 * P["weeks"]:
    t1 = tile("Block", "Complete", f"ended {b_end:%b %-d}", "good")
else:
    t1 = tile("Block", f"Week {week_no}", f"of {P['weeks']} · {(b_end - TODAY).days} days to go",
              meter=100 * (day_in + 1) / (7 * P["weeks"]))

if not W_block.empty:
    latest = W_block.iloc[-1]
    lost = P["start_weight_lb"] - latest["avg7"]
    pace_lost = P["start_weight_lb"] - goal_pace(min(TODAY, b_end))
    tone = "good" if lost >= pace_lost - 0.3 else "warn"
    t2 = tile("Weight · 7-day average", f"{'−' if lost >= 0 else '+'}{abs(lost):.1f} lb",
              f"{latest['avg7']:.1f} lb now · pace says −{pace_lost:.1f}", tone,
              meter=100 * lost / P["goal_loss_lb"])
else:
    t2 = tile("Weight · 7-day average", "—", "No weigh-ins in Garmin Connect yet")

t3 = tile("Zone 2 this week", f"{z2_week:.0f} min", f"target {P['zone2_target_min']} min",
          "good" if z2_week >= P["zone2_target_min"] else "", meter=100 * z2_week / P["zone2_target_min"])
t4 = tile("Workouts this week", f"{sessions_week} / {planned}", f"{fmt_min(A_week['duration_min'].sum() if not A_week.empty else 0)} trained",
          "good" if sessions_week >= planned else "", meter=100 * sessions_week / planned)
show_tiles([t1, t2, t3, t4])

# ---------------------------------------------------------------- weight vs goal
st.markdown("## Weight against the goal")
if W_block.empty:
    st.markdown('<p class="small">Garmin only has weigh-ins from a Garmin scale or ones you log in Garmin Connect. '
                'None are in this period, so weight lives in your block dashboard for now.</p>', unsafe_allow_html=True)
else:
    pace = pd.DataFrame({"date": [pd.Timestamp(b_start), pd.Timestamp(b_end)],
                         "weight_lb": [P["start_weight_lb"], P["start_weight_lb"] - P["goal_loss_lb"]]})
    x = alt.X("date:T", title=None, scale=alt.Scale(domain=[pd.Timestamp(b_start).isoformat(), pd.Timestamp(b_end).isoformat()]),
              axis=alt.Axis(format="%b %d", tickCount=10))
    lo = min(W_block["weight_lb"].min(), P["start_weight_lb"] - P["goal_loss_lb"]) - 1.5
    hi = max(W_block["weight_lb"].max(), P["start_weight_lb"]) + 1.5
    y = alt.Y("weight_lb:Q", title="lb", scale=alt.Scale(domain=[lo, hi], zero=False))
    goal_line = alt.Chart(pace).mark_line(strokeDash=[7, 6], color=C["muted"], strokeWidth=2).encode(x=x, y=y)
    dots = alt.Chart(W_block).mark_circle(size=40, color=C["muted"], opacity=.5).encode(
        x=x, y=y, tooltip=[alt.Tooltip("date:T", format="%a %b %d", title="Date"),
                           alt.Tooltip("weight_lb:Q", format=".1f", title="Weigh-in (lb)")])
    avg = alt.Chart(W_block).mark_line(color=C["accent"], strokeWidth=3, point=alt.OverlayMarkDef(size=0)).encode(
        x=x, y=alt.Y("avg7:Q", scale=alt.Scale(domain=[lo, hi], zero=False)),
        tooltip=[alt.Tooltip("date:T", format="%a %b %d", title="Date"),
                 alt.Tooltip("avg7:Q", format=".1f", title="7-day avg (lb)")])
    chart(goal_line + dots + avg, 260)
    st.markdown('<p class="small">Teal line: 7-day average. Dots: single weigh-ins. Dashed line: the pace that reaches '
                f'−{P["goal_loss_lb"]:g} lb by {b_end:%b %-d}. Day-to-day swings of 1–3 lb are water, salt and sleep.</p>',
                unsafe_allow_html=True)

# ---------------------------------------------------------------- this week vs recent weeks
st.markdown("## This week against recent weeks")
if A.empty:
    st.info("No activities in this period yet.")
else:
    weeks = [this_monday - pd.Timedelta(weeks=k) for k in range(7, -1, -1)]
    recent = A[A["week"].isin(weeks)]
    grid = pd.MultiIndex.from_product([weeks, ["Strength", "Cardio", "Other"]], names=["week", "category"])
    by_cat = (recent.groupby(["week", "category"])
              .agg(minutes=("duration_min", "sum"), sessions=("name", "count"), km=("distance_km", "sum"))
              .reindex(grid, fill_value=0).reset_index())
    by_cat["label"] = by_cat["week"].dt.strftime("%b %d")
    by_cat.loc[by_cat["week"] == this_monday, "label"] = "This week"
    order = [("This week" if w == this_monday else w.strftime("%b %d")) for w in weeks]
    used = [c for c in ["Strength", "Cardio", "Other"] if by_cat.loc[by_cat["category"] == c, "minutes"].sum() > 0]
    by_cat = by_cat[by_cat["category"].isin(used)]

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### Time trained per week")
        bars = alt.Chart(by_cat).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
            x=alt.X("label:N", sort=order, title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("hours:Q", title="hours", stack="zero"),
            color=alt.Color("category:N", scale=alt.Scale(domain=used, range=[CAT_COLORS[c] for c in used])),
            opacity=alt.condition(alt.datum.label == "This week", alt.value(1), alt.value(.7)),
            tooltip=[alt.Tooltip("label:N", title="Week"), alt.Tooltip("category:N", title="Type"),
                     alt.Tooltip("hours:Q", format=".1f", title="Hours"), alt.Tooltip("sessions:Q", title="Sessions")],
        ).transform_calculate(hours="datum.minutes / 60")
        chart(bars)
    with c2:
        st.markdown("### Zone 2 minutes per week")
        z2 = recent.groupby("week")["z2_min"].sum().reindex(weeks, fill_value=0).reset_index()
        z2.columns = ["week", "z2"]
        z2["label"] = order
        z2_bars = alt.Chart(z2).mark_bar(color=C["accent"], cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
            x=alt.X("label:N", sort=order, title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("z2:Q", title="minutes"),
            opacity=alt.condition(alt.datum.label == "This week", alt.value(1), alt.value(.7)),
            tooltip=[alt.Tooltip("label:N", title="Week"), alt.Tooltip("z2:Q", format=".0f", title="Zone 2 min")])
        target = alt.Chart(pd.DataFrame({"t": [P["zone2_target_min"]]})).mark_rule(
            strokeDash=[6, 5], color=C["muted"], strokeWidth=1.5).encode(y="t:Q")
        chart(z2_bars + target)

    st.markdown("### By sport")
    prev4 = A[(A["week"] >= this_monday - pd.Timedelta(weeks=4)) & (A["week"] < this_monday)]
    sports = sorted(set(A_week["sport"]) | set(prev4["sport"]))
    rows = []
    for sp in sports:
        cur, prev = A_week[A_week["sport"] == sp], prev4[prev4["sport"] == sp]
        has_km = (cur["distance_km"].sum() + prev["distance_km"].sum()) > 0
        rows.append({
            "Sport": sp,
            "Sessions": len(cur), "Avg sessions (prev 4 wks)": round(len(prev) / 4, 1),
            "Time": fmt_min(cur["duration_min"].sum()), "Avg time (prev 4 wks)": fmt_min(prev["duration_min"].sum() / 4),
            "Distance": f"{cur['distance_km'].sum():.1f} km" if has_km else "—",
            "Avg distance (prev 4 wks)": f"{prev['distance_km'].sum() / 4:.1f} km" if has_km else "—",
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.markdown('<p class="small">Nothing logged in the last five weeks.</p>', unsafe_allow_html=True)

# ---------------------------------------------------------------- trends
st.markdown("## Trends")
span = st.radio("Window", ["Block", "3 months", "6 months", "12 months"], horizontal=True, label_visibility="collapsed")
span_start = {"Block": pd.Timestamp(b_start), "3 months": pd.Timestamp(TODAY - timedelta(days=91)),
              "6 months": pd.Timestamp(TODAY - timedelta(days=182)),
              "12 months": pd.Timestamp(TODAY - timedelta(days=364))}[span]
xdom = alt.Scale(domain=[span_start.isoformat(), pd.Timestamp(TODAY).isoformat()])
xT = alt.X("date:T", title=None, scale=xdom, axis=alt.Axis(format="%b %d"))


def window(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["date"] >= span_start] if not df.empty else df


def empty_note(what: str) -> None:
    st.markdown(f'<p class="small">No {what} in this window. Older watches skip some of these, '
                'and nights without the watch leave gaps.</p>', unsafe_allow_html=True)


c1, c2 = st.columns(2)
with c1:
    st.markdown("### Training load per week")
    Aw = window(A)
    if Aw.empty or Aw["load"].fillna(0).sum() == 0:
        empty_note("training load")
    else:
        tl = Aw.groupby("week").agg(load=("load", "sum"), sessions=("name", "count")).reset_index().rename(columns={"week": "date"})
        all_weeks = pd.date_range(tl["date"].min(), this_monday, freq="7D")
        tl = tl.set_index("date").reindex(all_weeks, fill_value=0).rename_axis("date").reset_index()
        tl["label"] = tl["date"].dt.strftime("%b %d")
        step = max(1, len(tl) // 8)
        ticks = tl["label"].tolist()[::-1][::step]
        chart(alt.Chart(tl).mark_bar(color=C["accent"], cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
            x=alt.X("label:N", sort=tl["label"].tolist(), title=None, axis=alt.Axis(labelAngle=0, values=ticks)),
            y=alt.Y("load:Q", title="load"),
            opacity=alt.condition(alt.datum.date >= this_monday.timestamp() * 1000, alt.value(1), alt.value(.75)),
            tooltip=[alt.Tooltip("date:T", format="Week of %b %d", title="Week"),
                     alt.Tooltip("load:Q", format=".0f", title="Training load"),
                     alt.Tooltip("sessions:Q", title="Sessions")]))
        st.markdown('<p class="small">Steady building is good. A jump of more than about a third in one week is where injuries start.</p>', unsafe_allow_html=True)
with c2:
    st.markdown("### Resting heart rate")
    Dw = window(DAILY).dropna(subset=["rhr"]) if not DAILY.empty else DAILY
    if Dw.empty:
        empty_note("resting heart rate")
    else:
        Dw = Dw.assign(avg7=Dw["rhr"].rolling(7, min_periods=3).mean())
        yr = alt.Scale(zero=False, padding=6)
        pts = alt.Chart(Dw).mark_circle(size=22, color=C["hr"], opacity=.35).encode(
            x=xT, y=alt.Y("rhr:Q", title="bpm", scale=yr),
            tooltip=[alt.Tooltip("date:T", format="%a %b %d", title="Date"), alt.Tooltip("rhr:Q", title="Resting HR")])
        ln = alt.Chart(Dw).mark_line(color=C["hr"], strokeWidth=2.5).encode(
            x=xT, y=alt.Y("avg7:Q", scale=yr),
            tooltip=[alt.Tooltip("date:T", format="%a %b %d", title="Date"), alt.Tooltip("avg7:Q", format=".1f", title="7-day avg")])
        chart(pts + ln)
        st.markdown('<p class="small">Drifting down over weeks means your fitness is improving. A sudden rise of 5+ bpm often means poor recovery or illness.</p>', unsafe_allow_html=True)

c1, c2 = st.columns(2)
with c1:
    st.markdown("### HRV")
    Hw = window(HRV)
    if Hw.empty:
        empty_note("HRV readings")
    else:
        layers = []
        if Hw["base_low"].notna().any():
            layers.append(alt.Chart(Hw.dropna(subset=["base_low", "base_high"])).mark_area(color=C["accent"], opacity=.12).encode(
                x=xT, y=alt.Y("base_low:Q", title="ms", scale=alt.Scale(zero=False)), y2="base_high:Q"))
        layers.append(alt.Chart(Hw).mark_circle(size=22, color=C["accent"], opacity=.4).encode(
            x=xT, y=alt.Y("last_night:Q", title="ms", scale=alt.Scale(zero=False)),
            tooltip=[alt.Tooltip("date:T", format="%a %b %d", title="Date"), alt.Tooltip("last_night:Q", title="Last night (ms)"),
                     alt.Tooltip("weekly_avg:Q", title="7-day avg (ms)"), alt.Tooltip("status:N", title="Status")]))
        layers.append(alt.Chart(Hw.dropna(subset=["weekly_avg"])).mark_line(color=C["accent"], strokeWidth=2.5).encode(
            x=xT, y=alt.Y("weekly_avg:Q", scale=alt.Scale(zero=False))))
        chart(alt.layer(*layers))
        st.markdown('<p class="small">Line: 7-day average. Shaded band: your balanced range from Garmin. Staying inside it means recovery is keeping up with training.</p>', unsafe_allow_html=True)
with c2:
    st.markdown("### Sleep")
    Sw = window(SLEEP)
    if Sw.empty:
        empty_note("sleep data")
    else:
        stages = Sw.melt(id_vars=["date", "total_h", "score"], value_vars=["deep_h", "rem_h", "light_h"],
                         var_name="stage", value_name="hours")
        stages["stage"] = stages["stage"].map({"deep_h": "Deep", "rem_h": "REM", "light_h": "Light"})
        st_dom = ["Deep", "REM", "Light"]
        chart(alt.Chart(stages).mark_bar().encode(
            x=xT, y=alt.Y("hours:Q", title="hours", stack="zero"),
            color=alt.Color("stage:N", sort=st_dom, scale=alt.Scale(domain=st_dom, range=[C["pr"], C["accent"], C["line"] if not DARK else "#4A5E63"])),
            order=alt.Order("stage_order:Q"),
            tooltip=[alt.Tooltip("date:T", format="%a %b %d", title="Night of"), alt.Tooltip("total_h:Q", format=".1f", title="Total (h)"),
                     alt.Tooltip("stage:N", title="Stage"), alt.Tooltip("hours:Q", format=".1f", title="Stage (h)"),
                     alt.Tooltip("score:Q", title="Sleep score")],
        ).transform_calculate(stage_order="indexof(['Deep','REM','Light'], datum.stage)"))
        avg_h, avg_s = Sw["total_h"].mean(), Sw["score"].mean()
        st.markdown(f'<p class="small">Average {avg_h:.1f} h a night' + (f', sleep score {avg_s:.0f}' if pd.notna(avg_s) else '') +
                    '. Short sleep raises hunger the next day, which makes the weight goal harder.</p>', unsafe_allow_html=True)

# ---------------------------------------------------------------- records
st.markdown("## Records and biggest days")
if A.empty:
    st.info("Records show up once activities load.")
else:
    st.caption(f"Across everything pulled since {pd.Timestamp(pull_start):%b %-d, %Y}.")
    recs = []

    def best(df: pd.DataFrame, col: str, label: str, fmt) -> None:
        d = df.dropna(subset=[col])
        d = d[d[col] > 0]
        if d.empty:
            return
        r = d.loc[d[col].idxmax()]
        recs.append(tile(label, fmt(r[col]), f"{r['name']} · {r['date']:%b %-d, %Y}"))

    rides = A[A["sport"] == "Cycling"]
    best(rides, "distance_km", "Longest ride", lambda v: f"{v:.1f} km")
    best(A[A["sport"] == "Running"], "distance_km", "Longest run", lambda v: f"{v:.1f} km")
    best(A, "duration_min", "Longest session", fmt_min)
    best(A, "load", "Biggest training load", lambda v: f"{v:.0f}")
    best(A, "calories", "Most calories", lambda v: f"{v:,.0f}")
    best(A, "elevation_m", "Most climbing", lambda v: f"{v:,.0f} m")
    best(A, "z2_min", "Most Zone 2 in one go", fmt_min)
    st.markdown(f'<div class="rec">{"".join(recs)}</div>', unsafe_allow_html=True)

    st.markdown("### Biggest weeks")
    wk = (A.groupby("week").agg(minutes=("duration_min", "sum"), sessions=("name", "count"),
                                load=("load", "sum"), z2=("z2_min", "sum"), km=("distance_km", "sum"))
          .sort_values("minutes", ascending=False).head(5).reset_index())
    st.dataframe(pd.DataFrame({
        "Week of": wk["week"].dt.strftime("%b %d, %Y"), "Time": wk["minutes"].map(fmt_min),
        "Sessions": wk["sessions"], "Training load": wk["load"].round(0).astype(int),
        "Zone 2": wk["z2"].map(fmt_min), "Distance": wk["km"].map(lambda v: f"{v:.1f} km"),
    }), hide_index=True, width="stretch")

    st.markdown("### Recent activities")
    last = A.sort_values("start", ascending=False).head(12)
    st.dataframe(pd.DataFrame({
        "Date": last["start"].dt.strftime("%a %b %d"), "Activity": last["name"], "Sport": last["sport"],
        "Time": last["duration_min"].map(fmt_min),
        "Distance": last["distance_km"].map(lambda v: f"{v:.1f} km" if v > 0 else "—"),
        "Avg HR": last["avg_hr"].map(lambda v: f"{v:.0f}" if pd.notna(v) else "—"),
        "Zone 2": last["z2_min"].map(fmt_min),
        "Load": last["load"].map(lambda v: f"{v:.0f}" if pd.notna(v) else "—"),
    }), hide_index=True, width="stretch")

# ---------------------------------------------------------------- footer
pulled = raw.get("pulled_at", "")
with st.sidebar:
    st.markdown(f'<p class="small">{"Sample data" if is_demo else "Last pulled"}: {pulled.replace("T", " ")}<br>'
                f'{len(A)} activities · {len(DAILY)} days · {len(SLEEP)} nights · {len(HRV)} HRV readings · {len(WEIGHT)} weigh-ins</p>',
                unsafe_allow_html=True)
st.markdown(f'<p class="small" style="margin-top:2rem">Read-only data from Garmin\'s Personal API. '
            f'Refreshes on its own every {CACHE_SECONDS // 60} minutes; open the sidebar to refresh now.</p>',
            unsafe_allow_html=True)
