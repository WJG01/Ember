# Ember for Family Link

A parent dashboard for what a child likes on a standard YouTube account, added to a
Family Link style mobile web app as a new **Space** tab. FastAPI backend, plain HTML/JS
front end, Gemini for the analysis.

```
app/main.py            FastAPI: /auth/*, /api/sync, /api/run, /api/videos, /api/status, /api/report
pipeline/              stage 1 content_sense.py, stage 2 curiosity_graph.py,
                       stage 3 quest_planner.py, gem.py (shared Gemini helper)
static/                index.html, style.css, app.js (Family Link UI, Space tab, Ember dashboard)
demo_data/             sample data, shown until a real analysis exists
data/                  runtime output: ember_signals.json, video_records.json,
                       themes.json, quest.json, token.json, cache/  (git-ignored)
scripts/               test_youtube_signals.py, diagnose.py (run from the project root)
```

## The app
- **Screen time** is the Family Link home screen. **Controls** and **Location** are static
  buttons that do nothing. The profile chip opens a static Family Link drawer.
- **Space** is the new tab. It lists integrations; **Ember** opens the dashboard.
- Width is a 412 px mobile column (full screen on a phone, centred on desktop).

## Run it (PowerShell, from this folder)
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:GEMINI_API_KEY = "your-key"
$env:EMBER_CHILD_NAME = "Llamie"     # optional
$env:EMBER_CHILD_AGE = "11"          # optional, calibrates safety judgements
uvicorn app.main:app --port 8080
```
Open http://localhost:8080. Until you run an analysis the dashboard shows `demo_data/`.
`$env:EMBER_DEMO = "1"` forces the demo data (use it if the wifi or API fails on stage).

## Connect YouTube
1. Google Cloud: enable **YouTube Data API v3**; create an OAuth client; authorised
   redirect URI `http://localhost:8080/auth/callback`. Download it as `client_secret.json`
   into this folder.
2. Consent screen in Testing mode: add the child's account under Test users.
3. In the app: Space > Ember > **Connect YouTube**, sign in as the child, tap Allow.
4. **Sync and analyse**. Results are saved in `data/`.

Notes
- YouTube does not let apps read **supervised (Family Link) accounts**; the child needs a
  standard Google account with a YouTube channel. Otherwise use **Add a video link**.
- Testing-mode tokens expire after 7 days: reconnect the day before a demo.
- If gemini-3.8-flash is rejected, run python scripts/diagnose.py, then set GEMINI_MODEL on the service.
  in `pipeline/content_sense.py`.
- The dashboard says "liked videos", not "watched": the API has no watch history.
- **Print this card** prints only the quest card.

## API
| Route | Purpose |
|---|---|
| GET /auth/start, /auth/callback | Google sign-in; token saved to `data/token.json` |
| POST /api/sync | read likes from YouTube, then run all three stages |
| POST /api/run | run the stages on what is already saved (`{"sync": false, "age": 11}`) |
| GET/POST /api/videos | list saved videos / add a video link |
| GET /api/status | progress, connection state, last error |
| GET /api/report | everything the dashboard renders |
| POST /api/disconnect | forget the YouTube token |

## Before this goes beyond a demo
The API has no login and the token is a local file; do not put it on the public internet.
For Cloud Run: sign parents in (Family Link / Identity Platform), move `data/` to Firestore
and `token.json` to Secret Manager. The pipeline scripts need no change.
