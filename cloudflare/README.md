# Garmin dashboard on Cloudflare

A fast replacement for the Streamlit app. A Cloudflare Worker pulls your Garmin data
every hour and saves it, so the page opens instantly with everything already loaded.

| File | What it does |
| --- | --- |
| `src/settings.js` | The program: start date, starting weight, goal, Zone 2 target, weekly plan |
| `src/garmin.js` | Talks to Garmin's Personal API (read-only) and shapes the data |
| `src/worker.js` | Hourly pull, password check, serves the page |
| `src/page.html` | The dashboard |
| `wrangler.jsonc` | Cloudflare settings (hourly schedule, storage) |

## Secrets

Set these in Cloudflare (Worker → Settings → Variables and Secrets), never in this repo:

- `GARMIN_PERSONAL_API_KEY`: from the [Personal API Key page](https://connect.garmin.com/app/settings/personalApiToken)
- `APP_PASSWORD`: the password that unlocks the page

Keys expire after a year at most. When Garmin rejects it, the page says so; make a new key and replace the secret.

## How the pull works

Each hourly run pulls the last 7 days of activities, daily summaries, sleep, HRV and
weigh-ins. The first runs also backfill up to a year of history, a month at a time, until
it's complete. **Refresh from Garmin now** on the page runs a pull immediately.

## Changing the program

Edit `src/settings.js` and push. Cloudflare redeploys on its own.
