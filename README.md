# Garmin training dashboard

A private Streamlit dashboard for my 10-week block, pulling live, read-only data from
Garmin's official Personal API: activities, Zone 2, training load, resting heart rate,
HRV, sleep and weigh-ins.

## Files

| File | What it does |
| --- | --- |
| `app.py` | The dashboard |
| `settings.py` | The program: start date, starting weight, goal, Zone 2 target, weekly plan |
| `garmin_client.py` | Talks to Garmin (standard library only). Swaps the key for a 24-hour token, pages through results, splits requests that come back too large, retries on rate limits |
| `transform.py` | Turns Garmin's responses into tables |
| `demo.py` | Made-up sample data, shown only until a key is added |

## The key

The key never goes in this repo. On Streamlit Community Cloud it lives in the app's
**Settings → Secrets** as:

```toml
GARMIN_PERSONAL_API_KEY = "paste-key-here"
APP_PASSWORD = "a-password-only-you-know"
```

`APP_PASSWORD` locks the dashboard: nothing is pulled from Garmin or shown until it's
entered. Use it whenever the app is public on Streamlit.

Keys expire (one year at most). When it does, create a new one on the
[Personal API Key page](https://connect.garmin.com/app/settings/personalApiToken)
and replace it in Secrets.

## Running it on a computer instead

```
pip install -r requirements.txt
streamlit run app.py
```

with the key in `.streamlit/secrets.toml` or `.env.local` (both are git-ignored).
