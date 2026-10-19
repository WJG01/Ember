# Ember

**A parent dashboard that tells you what your child actually watched, so you don't have to rewatch it.**

Ember reads the YouTube videos a child has liked, has Gemini watch each one, and turns the result into a
short parent-facing report: a plain-language summary, what holds the child's attention, what is worth a
look, how much real learning is in the mix, and one weekend activity to grow the child's interests.

> Proof of concept built for the AI Builder Cup (Google Cloud). It is a demo, not a production system.

## What the parent sees

The app opens in a mobile "Family Link"-style shell. The **Ember** tab has a connection card
(YouTube is connected / Disconnect / Add a video link / Reconnect YouTube / Sync and analyse) and six sections:

| Section | What it answers |
|---|---|
| Overview | One-paragraph summary, headline numbers, and videos worth a look |
| Weekend quest | One printable activity built from the child's own interests |
| Interests | A graph of the themes that draw the child in, with detail per theme |
| Behind the title | What a video's title says vs. what actually holds attention |
| Watch mix | Time by subject and how much of it is real learning |
| Videos | Every video, filterable, with a summary and questions to ask |

## How it works

```
YouTube liked videos (OAuth)  or  pasted links
            |
   content_sense.py   Gemini watches each video -> parent report + curiosity fields
            |
   curiosity_graph.py Gemini groups videos into themes
            |
   quest_planner.py   Gemini writes one weekend activity
            |
   FastAPI  /api/report  ->  static/ dashboard
```

## Google Cloud services

- **Gemini API** (`google-genai`): the three pipeline stages above. Video understanding for stage 1,
  structured JSON output (schema-constrained, with retry on invalid JSON) for all stages. The child's age
  calibrates the safety judgements.
- **Cloud Run**: hosts the FastAPI app and the static frontend as one container, deployed from source.
- **Secret Manager**: `GEMINI_API_KEY` and the OAuth client JSON are injected into Cloud Run as secrets,
  never stored in the repo.
- **YouTube Data API v3**: reads the child's liked videos after a one-time consent.

## Repo layout

```
main.py              FastAPI: sign-in, sync, run pipeline, /api/report, serves static/
content_sense.py     stage 1: Gemini watches each video
curiosity_graph.py   stage 2: themes
quest_planner.py     stage 3: weekend quest
gem.py               shared Gemini helper for stages 2-3
demo_data/           sample data shown until a real analysis runs
static/
  index.html         page shell
  app.js             startup only
  style.css          Family Link frame (top bar, bottom bar, drawer, dialog)
  css/ember-*.css    one stylesheet per Ember section
  js/core.js         shared helpers, state, section registry
  js/shell.js        routing, navigation, dialogs
  js/ember/*.js      one file per section (+ live.js connection card, page.js tabs)
```

Each section registers itself with `FL.registerSection(...)`; adding a section means adding one JS file,
one CSS file and two script/link tags in `index.html`.

## Run locally (Windows PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
$env:GEMINI_API_KEY = "your-key"
python main.py
```

Open http://localhost:8080. Sample data is shown first (a banner says so). Mac/Linux: `export GEMINI_API_KEY=...`.



## Connect YouTube
1. Google Cloud: enable **YouTube Data API v3**; create an OAuth client; authorised
   redirect URI `http://localhost:8080/auth/callback`. Download it as `client_secret.json`
   into this folder.
2. Consent screen in Testing mode: add the child's account under Test users.
3. In the app: Space > Ember > **Connect YouTube**, sign in as the child, tap Allow.
4. **Sync and analyse**. Results are saved in `data/`.


## Real data, two ways

**A. Paste links (no Google sign-in).** "Add a video link", paste 5-10 YouTube links, then "Analyse videos".

**B. Connect YouTube.** Create an OAuth client of type *Web application* in Google Cloud, add the child's
account as a test user, click "Connect YouTube", sign in as the child, tap Allow, then "Sync and analyse".
The child account must be a **standard** Google account with a YouTube channel: supervised (Family Link)
accounts are blocked by the YouTube API (`unsupportedSupervisedAccount`).


## Deploy to Cloud Run

```bash
gcloud run deploy ember-api --source . --region asia-southeast1 \
  --no-cpu-throttling --max-instances=1 --allow-unauthenticated \
  --set-env-vars EMBER_REDIRECT_URI=https://<your-service-url>/auth/callback \
  --set-secrets GEMINI_API_KEY=<secret>:latest,EMBER_CLIENT_SECRET_JSON=<secret>:latest
```

Add the same redirect URI to the OAuth client. Keep `--max-instances=1` and `--no-cpu-throttling`:
the analysis runs in a background thread and results are held on the instance, so a second instance or
a throttled CPU would lose or stall a run. Make sure the whole `static/` folder (including `css/` and
`js/`) is copied into the image.

## Environment variables

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | Gemini access (use Secret Manager on Cloud Run) |
| `GEMINI_MODEL` | Override the model set in `content_sense.py` |
| `EMBER_REDIRECT_URI` | OAuth callback URL |
| `EMBER_CHILD_NAME`, `EMBER_CHILD_AGE` | Name shown and age used to calibrate safety judgements |
| `EMBER_DEMO=1` | Force sample data (fallback if wifi or the API fails on stage) |


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


## Notes
- YouTube does not let apps read **supervised (Family Link) accounts**; the child needs a
  standard Google account with a YouTube channel. Otherwise use **Add a video link**.
- Testing-mode tokens expire after 7 days: reconnect the day before a demo.
- If gemini-3.8-flash is rejected, run python scripts/diagnose.py, then set GEMINI_MODEL on the service.
  in `pipeline/content_sense.py`.
- The dashboard says "liked videos", not "watched": the API has no watch history.
- **Print this card** prints only the quest card.


## Roadmap

- Persist reports and tokens per child in Firestore; sign parents in with Firebase Authentication.
- Weekly scheduled sync and a "what changed this week" view.
- Multiple children per parent.
