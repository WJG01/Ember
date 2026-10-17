# Ember: local setup

Parent dashboard for what a child watches on YouTube. FastAPI backend, plain HTML/JS frontend.

```
main.py              FastAPI: sign-in, sync, run pipeline, /api/report, serves static/
content_sense.py     stage 1: Gemini watches each video (parent report + curiosity fields)
curiosity_graph.py   stage 2: groups videos into themes
quest_planner.py     stage 3: one weekend activity (the printable card)
gem.py               shared Gemini helper for stages 2-3
static/              index.html, style.css, app.js
demo_data/           sample data, shown until you run a real analysis
test_youtube_signals.py, diagnose.py   your original test scripts
```

## Run it (Windows PowerShell)

```powershell
cd Ember\scripts            # the folder containing main.py
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
$env:GEMINI_API_KEY = "your-key"
python main.py
```

Open http://localhost:8080. The dashboard shows sample data first (a banner says so).
Mac/Linux: `export GEMINI_API_KEY=your-key`.

Python 3.10 works but is unsupported by Google's libraries; 3.11+ is better.

## Real data, two ways

**A. Paste links (no Google sign-in).** Click "Add a video link", paste 5-10 YouTube links,
then click "Analyse videos". Fastest and safest for the demo.

**B. Connect YouTube (the child taps Allow once).**
1. In Google Cloud, create an OAuth client of type **Web application**.
   Authorised redirect URI: `http://localhost:8080/auth/callback`
2. Download it as `client_secret.json` and put it next to `main.py`.
3. Add the child's account to Test users (Audience page).
4. Click "Connect YouTube", sign in **as the child** in a private window, tap Allow.
5. Click "Sync and analyse".

The child account must be a **standard** Google account with a YouTube channel.
Supervised (Family Link) accounts are blocked by YouTube's API (`unsupportedSupervisedAccount`).

## Demo day checklist

- Run the analysis the day before; results are saved in `video_records.json`, `themes.json`, `quest.json`.
- Testing-mode tokens expire after 7 days: reconnect the day before if using option B.
- `$env:EMBER_DEMO = "1"` forces the sample data if the wifi or API fails on stage.
- `$env:EMBER_CHILD_NAME = "Llamie"` and `$env:EMBER_CHILD_AGE = "11"` set the name shown and calibrate safety judgements.
- If `gemini-3.8-flash` is rejected, run `python diagnose.py` and change `MODEL` in `content_sense.py`.
- Use the "Print this card" button to show the offline end of the loop.

## Notes

- This is a proof of concept: the API has no login and tokens are stored in `token.json`. Do not put it on the public internet as it is.
- The dashboard says "liked videos", not "watched": the YouTube API does not expose watch history.
- Moving to Cloud Run later: replace the local JSON files with Firestore and the token file with Secret Manager. The pipeline scripts need no change.
