#!/usr/bin/env python3
"""
Ember backend (FastAPI) - an integration module for the Family Link web app.

    uvicorn app.main:app --port 8080        (run from the project root)

All state lives in Datastore (database "ember"); see store.py for the kinds.
Secrets (OAuth client JSON, Gemini key) come from env vars or Secret Manager.

Endpoints
  GET  /auth/start          send the child to Google's consent screen
  GET  /auth/callback       Google returns here; the token is stored in Datastore
  POST /api/sync            read the child's likes from YouTube, then run the pipeline
  POST /api/run             run the pipeline  (body: {"sync": bool, "age": int|null})
  GET  /api/videos          the videos Ember knows about (likes + saved links)
  POST /api/videos          guardian saves a video link
  GET  /api/status          pipeline progress + connection state
  GET  /api/report          everything the dashboard needs, in one JSON
  POST /api/disconnect      forget the YouTube token
  /                         the Family Link style web app (static/)

If no real analysis exists yet, the app shows demo_data/ and says so.
Set EMBER_DEMO=1 to always show the demo data.

One child for now (EMBER_CHILD_ID, default "default"). Proof-of-concept: the API
has no login, so do not expose it to the internet as it stands.

Cloud Run: the pipeline runs in a background thread after the HTTP response, so
deploy with --no-cpu-throttling (instance-based billing) or it will crawl.
"""

import json
import os
import re
import subprocess
import sys
import time
import threading
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from google.auth.exceptions import RefreshError
from pydantic import BaseModel, Field
from google_auth_oauthlib.flow import Flow

BASE_DIR = Path(__file__).resolve().parent
PIPELINE = BASE_DIR / "pipeline" if (BASE_DIR / "pipeline").exists() else BASE_DIR
DEMO_DIR = BASE_DIR / "demo_data"
STATIC = BASE_DIR / "static"

for _p in (BASE_DIR, PIPELINE):
    sys.path.insert(0, str(_p))
import store  # noqa: E402

SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]

app = FastAPI()

CHILD_ID = os.environ.get("EMBER_CHILD_ID", "default")

# Must match an Authorized redirect URI on the OAuth client (type: Web application).
BASE_REDIRECT_URI = os.environ.get("EMBER_REDIRECT_URI") or "http://localhost:8080/auth/callback"

DEMO_FORCED = os.environ.get("EMBER_DEMO") == "1"
CHILD_NAME = os.environ.get("EMBER_CHILD_NAME")
_age = os.environ.get("EMBER_CHILD_AGE", "")
DEFAULT_AGE = int(_age) if _age.isdigit() else None

# Allow plain http ONLY for local development.
if BASE_REDIRECT_URI.startswith("http://localhost"):
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

DOMAIN_LABELS = {
    "science_nature": "Science and nature",
    "art_craft": "Art and craft",
    "cooking_food": "Cooking and food",
    "building_engineering": "Building and engineering",
    "technology_coding": "Technology and coding",
    "math_logic": "Maths and logic",
    "music_performance": "Music and performance",
    "sports_fitness": "Sport and fitness",
    "stories_language": "Stories and language",
    "history_culture": "History and culture",
    "life_skills": "Life skills",
    "gaming": "Gaming",
    "humor_entertainment": "Humour and entertainment",
    "toys_unboxing_shopping": "Toys, unboxing and shopping",
    "other": "Other",
}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


class PipelineError(Exception):
    pass


_avail = {}


def _available(fn_name):
    """Can store.<fn_name>() succeed? Cached; failures are retried after 30 s."""
    ok, ts = _avail.get(fn_name, (None, 0.0))
    if ok is None or (not ok and time.monotonic() - ts > 30):
        try:
            getattr(store, fn_name)()
            ok = True
        except Exception:  # noqa: BLE001
            ok = False
        _avail[fn_name] = (ok, time.monotonic())
    return ok


# --------------------------------------------------------------------------
# Google sign-in (web flow) - the child taps Allow once
# --------------------------------------------------------------------------
def _flow(state=None):
    return Flow.from_client_config(
        store.oauth_client_config(), scopes=SCOPES, redirect_uri=BASE_REDIRECT_URI, state=state)


@app.get("/")
def read_root():
    return FileResponse(STATIC / "index.html")


@app.get("/auth/start")
def auth_start():
    try:
        flow = _flow()
    except Exception:  # noqa: BLE001 - secret missing or unreadable
        return RedirectResponse("/?auth_error=missing_client_secret")
    url, state = flow.authorization_url(
        access_type="offline",            # required to get a refresh token
        prompt="consent select_account",  # makes Google return the refresh token every time
    )
    store.put_oauth_state(state, CHILD_ID, flow.code_verifier)
    return RedirectResponse(url)


@app.get("/auth/callback")
def auth_callback(request: Request, state: str, code: str | None = None, error: str | None = None):
    if error:
        return RedirectResponse(f"/?auth_error={urllib.parse.quote(error)}")
    pending = store.pop_oauth_state(state)   # single use; None if missing or expired
    if not pending:
        raise HTTPException(status_code=400, detail="Invalid or expired session state. Try Connect YouTube again.")

    flow = _flow(state=state)
    flow.code_verifier = pending["code_verifier"]
    # Behind Cloud Run request.url can say http://, which oauthlib rejects. Rebuild it from the
    # configured redirect URI plus the query string Google sent.
    flow.fetch_token(authorization_response=f"{BASE_REDIRECT_URI}?{request.url.query}")

    child_id = pending["child_id"]
    store.save_credentials(child_id, flow.credentials)
    store.upsert_child(child_id, connected=True)
    return RedirectResponse("/?auth=success")


@app.post("/api/disconnect")
def disconnect():
    store.delete_credentials(CHILD_ID)
    store.upsert_child(CHILD_ID, connected=False)
    return {"ok": True}


# --------------------------------------------------------------------------
# YouTube signals (likes) and guardian saves (video links)
# --------------------------------------------------------------------------
def _page(request_fn):
    out, token = [], None
    while True:
        resp = request_fn(token).execute()
        out.extend(resp.get("items", []))
        token = resp.get("nextPageToken")
        if not token:
            return out


def fetch_signals(child_id):
    """Read likes + subscriptions with the stored token and save them to Datastore."""
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    try:
        creds = store.google_credentials(child_id)
    except RefreshError:
        store.upsert_child(child_id, connected=False)
        raise PipelineError("The YouTube connection expired. Use Connect YouTube again.")
    if not creds:
        raise PipelineError("YouTube is not connected yet. Use Connect YouTube first.")
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)

    try:
        ch = yt.channels().list(part="contentDetails,snippet", mine=True).execute()
        items = ch.get("items", [])
        if not items:
            raise PipelineError(
                "This Google account has no YouTube channel, so there is no likes list to read. "
                "Sign in to youtube.com as the child, create a channel, like a few videos, then sync again."
            )
        channel = items[0]
        likes_id = channel["contentDetails"]["relatedPlaylists"].get("likes")
        if not likes_id:
            raise PipelineError("No likes playlist was returned for this account.")

        def likes_req(token):
            return yt.playlistItems().list(part="snippet,contentDetails", playlistId=likes_id,
                                           maxResults=50, pageToken=token)

        likes = []
        for i in _page(likes_req):
            title = i["snippet"].get("title", "")
            if title in ("Deleted video", "Private video"):
                continue
            vid = i["contentDetails"]["videoId"]
            likes.append({
                "video_id": vid,
                "title": title,
                "channel": i["snippet"].get("videoOwnerChannelTitle"),
                "liked_at": i["snippet"].get("publishedAt"),
                "url": f"https://www.youtube.com/watch?v={vid}",
                "source": "youtube_like",
            })

        try:
            def subs_req(token):
                return yt.subscriptions().list(part="snippet", mine=True, maxResults=50, pageToken=token)
            subs = [{"channel_id": i["snippet"]["resourceId"]["channelId"],
                     "title": i["snippet"]["title"],
                     "subscribed_at": i["snippet"].get("publishedAt")} for i in _page(subs_req)]
        except HttpError:
            subs = []
    except HttpError as e:
        text = str(e)
        if "unsupportedSupervisedAccount" in text:
            raise PipelineError(
                "YouTube does not allow apps to read supervised (Family Link) accounts. "
                "Use a standard Google account for the child, or add video links by hand."
            )
        if "invalid_grant" in text or e.resp.status == 401:
            store.upsert_child(child_id, connected=False)
            raise PipelineError("The YouTube connection expired. Use Connect YouTube again.")
        raise PipelineError(f"YouTube returned an error: {text[:200]}")

    # Fresh YouTube read replaces old likes; guardian-saved links are kept.
    store.replace_youtube_likes(child_id, likes)
    store.upsert_child(
        child_id, connected=True, channel_id=channel["id"], channel_title=channel["snippet"]["title"],
        subscriptions_json=json.dumps(subs, ensure_ascii=False), last_synced_at=store.iso_now())
    return len(store.list_videos(child_id))


_YT_ID = re.compile(
    r"(?:youtu\.be/|youtube\.com/(?:watch\?(?:[^#]*&)?v=|shorts/|embed/|live/))([A-Za-z0-9_-]{11})")


class VideoIn(BaseModel):
    url: str = Field(max_length=300)


@app.get("/api/videos")
def list_videos():
    child = store.get_child(CHILD_ID)
    videos = [{k: v for k, v in x.items() if k != "added_at"} for x in store.list_videos(CHILD_ID)]
    return {"videos": videos, "subscriptions": store.child_subscriptions(child)}


@app.post("/api/videos")
def add_video(body: VideoIn):
    text = body.url.strip()
    m = _YT_ID.search(text)
    if m:
        vid = m.group(1)
    elif re.fullmatch(r"[A-Za-z0-9_-]{11}", text):
        vid = text
    else:
        raise HTTPException(
            400, "That does not look like a YouTube link. Paste the full video address.")
    url = f"https://www.youtube.com/watch?v={vid}"

    title, channel = url, None
    try:  # public title lookup, no API key needed
        q = urllib.parse.urlencode({"url": url, "format": "json"})
        with urllib.request.urlopen(f"https://www.youtube.com/oembed?{q}", timeout=5) as r:
            meta = json.loads(r.read().decode("utf-8"))
            title, channel = meta.get("title", url), meta.get("author_name")
    except Exception:  # noqa: BLE001 - offline or blocked: fall back to the URL as title
        pass

    if store.get_video(CHILD_ID, vid):
        return {"ok": True, "duplicate": True, "title": title}
    store.upsert_child(CHILD_ID)  # make sure the Child exists
    store.put_videos(CHILD_ID, [{
        "video_id": vid, "title": title, "channel": channel,
        "liked_at": datetime.now(timezone.utc).isoformat(), "url": url, "source": "guardian_save",
    }])
    return {"ok": True, "duplicate": False, "title": title}


# --------------------------------------------------------------------------
# Pipeline runner (background thread; stage scripts run as subprocesses)
# Status is persisted in the Run entity, so it survives restarts and works
# across Cloud Run instances.
# --------------------------------------------------------------------------
STEPS = [
    ("Watching the videos", "content_sense.py"),
    ("Finding what draws them", "curiosity_graph.py"),
    ("Planning this week's quest", "quest_planner.py"),
]
_PROGRESS = re.compile(r"^\[(\d+)/(\d+)\]")


class Tracker:
    """Holds one run's state in memory and flushes it to Datastore (throttled)."""

    def __init__(self, run_id, state):
        self.run_id, self.s, self._t = run_id, state, time.monotonic()

    def flush(self, force=False):
        if not force and time.monotonic() - self._t < 2:
            return
        try:
            store.save_run(self.run_id, self.s)
        except Exception as e:  # noqa: BLE001 - never let a status write kill the pipeline
            print(f"could not save run status: {e}", file=sys.stderr)
        self._t = time.monotonic()

    def set(self, **kw):
        self.s.update(kw)
        self.flush(force=True)

    def log(self, line):
        self.s["log"].append(line)
        del self.s["log"][:-80]
        m = _PROGRESS.match(line)
        if m:
            self.s["progress"] = {"done": int(m.group(1)), "total": int(m.group(2))}
        self.flush()


def _run_script(t, script, child_id, age):
    cmd = [sys.executable, str(PIPELINE / script), "--child", child_id] + \
        (["--age", str(age)] if age else [])
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    try:  # read the Gemini key once here and hand it to the stage
        env["GEMINI_API_KEY"] = store.gemini_key()
    except RuntimeError as e:
        raise PipelineError(str(e))
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="replace", env=env, cwd=BASE_DIR)
    last = ""
    for line in p.stdout:
        line = line.rstrip()
        if line:
            last = line
            t.log(line)
    if p.wait() != 0:
        raise PipelineError(f"{script} stopped: {last or 'no output'}")


def _pipeline(t, child_id, sync, age):
    labels = t.s["labels"]
    status, error = "done", None
    try:
        offset = 0
        if sync:
            t.set(step_index=0, progress=None)
            n = fetch_signals(child_id)
            t.log(f"read {n} videos from YouTube")
            offset = 1
        elif not store.has_videos(child_id):
            raise PipelineError("No videos yet. Connect YouTube or add a video link first.")
        for i, (_label, script) in enumerate(STEPS):
            t.set(step_index=offset + i, progress=None)
            _run_script(t, script, child_id, age)
    except PipelineError as e:
        status, error = "error", str(e)
    except Exception as e:  # noqa: BLE001
        status, error = "error", f"{type(e).__name__}: {e}"
    extra = {"step_index": len(labels)} if status == "done" else {}
    t.set(status=status, error=error, finished_at=store.iso_now(), **extra)


class RunIn(BaseModel):
    sync: bool = False
    age: int | None = Field(default=None, ge=3, le=17)


def _start(sync, age):
    child = store.get_child(CHILD_ID) or {}
    if age:
        store.upsert_child(CHILD_ID, age=age)
    age = age or child.get("age") or DEFAULT_AGE
    labels = (["Reading liked videos"] if sync else []) + [label for label, _ in STEPS]
    try:
        run_id, state = store.start_run(CHILD_ID, labels, age, sync)
    except store.RunBusy:
        raise HTTPException(409, "An analysis is already running.")
    t = Tracker(run_id, state)
    threading.Thread(target=_pipeline, args=(t, CHILD_ID, sync, age), daemon=True).start()
    return {"started": True}


@app.post("/api/run")
def run(body: RunIn):
    return _start(body.sync, body.age)


@app.post("/api/sync")
def sync(body: RunIn | None = None):
    """Read the child's likes from YouTube, then run the whole pipeline."""
    return _start(True, body.age if body else None)


@app.get("/api/status")
def status():
    child = store.get_child(CHILD_ID) or {}
    run = store.get_run(child["latest_run_id"]) if child.get("latest_run_id") else None

    s = {"running": False, "labels": [], "step_index": -1, "progress": None,
         "log": [], "error": None, "finished_at": None}
    if run:
        stale = store.run_is_stale(run)
        s.update(
            running=run["status"] == "running" and not stale,
            labels=run["labels"], step_index=run.get("step_index", -1), progress=run["progress"],
            log=run["log"][-12:], finished_at=run.get("finished_at"),
            error=("The analysis stopped unexpectedly (the server may have restarted). Run it again."
                   if stale else run.get("error")),
        )
    s["connected"] = bool(child.get("connected"))
    s["has_client_secret"] = _available("oauth_client_config")
    s["has_gemini_key"] = _available("gemini_key")
    s["has_signals"] = store.has_videos(CHILD_ID)
    return s


# --------------------------------------------------------------------------
# Report for the dashboard
# --------------------------------------------------------------------------
def _report_inputs():
    """Real data from Datastore if the child has analysed videos, otherwise the demo set."""
    if not DEMO_FORCED:
        records = store.child_records(CHILD_ID)
        if records:
            child = store.get_child(CHILD_ID) or {}
            return {
                "demo": False, "records": records,
                "themes": store.get_doc("Themes", CHILD_ID), "quest": store.get_doc("Quest", CHILD_ID),
                "name": child.get("name"), "channel_title": child.get("channel_title"),
                "subscriptions": [s.get("title") for s in store.child_subscriptions(child)],
            }
    records = read_json(DEMO_DIR / "video_records.json", []) or []
    signals = read_json(DEMO_DIR / "ember_signals.json", {}) or {}
    sources = {x.get("video_id"): x.get("source") for x in signals.get("likes", [])}
    for r in records:
        r["source"] = sources.get(r["video_id"])
    return {
        "demo": True, "records": records,
        "themes": read_json(DEMO_DIR / "themes.json", None),
        "quest": read_json(DEMO_DIR / "quest.json", None),
        "name": None, "channel_title": (signals.get("channel") or {}).get("title"),
        "subscriptions": [s.get("title") for s in signals.get("subscriptions", [])],
    }


@app.get("/api/report")
def report():
    inp = _report_inputs()
    demo, records, themes, quest = inp["demo"], inp["records"], inp["themes"], inp["quest"]

    videos = []
    for r in records:
        a = r.get("analysis", {}) or {}
        vid = r["video_id"]
        videos.append({
            "video_id": vid,
            "title": r.get("title", ""),
            "channel": r.get("channel"),
            "liked_at": r.get("liked_at"),
            "url": r.get("url") or "",
            "thumbnail": "" if vid.startswith("demo_") else f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
            "domain": a.get("domain", "other"),
            "domain_label": DOMAIN_LABELS.get(a.get("domain", "other"), "Other"),
            "topic": a.get("topic", ""),
            "summary": a.get("summary", ""),
            "key_points": a.get("key_points", []),
            "educational_value": a.get("educational_value", "none"),
            "educational_reasoning": a.get("educational_reasoning", ""),
            "what_child_may_learn": a.get("what_child_may_learn", []),
            "age_suitability": a.get("age_suitability", ""),
            "safety_flags": a.get("safety_flags", ["none"]),
            "safety_note": a.get("safety_note", ""),
            "parent_flag": a.get("parent_flag", "ok"),
            "conversation_starter": a.get("conversation_starter", ""),
            "follow_up_idea": a.get("follow_up_idea", ""),
            "surface_topic": a.get("surface_topic", ""),
            "underlying_draw": a.get("underlying_draw", ""),
            "transferable": bool(a.get("transferable")),
            "source": r.get("source"),
        })
    videos.sort(key=lambda v: v["liked_at"] or "", reverse=True)

    n = len(videos)
    dom = Counter(v["domain"] for v in videos)
    domains = [{"domain": k, "label": DOMAIN_LABELS.get(k, k), "count": c,
                "pct": round(c * 100 / n) if n else 0} for k, c in dom.most_common()]
    edu = Counter(v["educational_value"] for v in videos)
    order = {"review": 0, "note": 1}
    attention = sorted([v for v in videos if v["parent_flag"] in order],
                       key=lambda v: order[v["parent_flag"]])

    child = CHILD_NAME or inp["name"] or ("Llamie" if demo else None) or inp["channel_title"] or "your child"

    return {
        "demo": demo,
        "child": child,
        "generated_at": (themes or {}).get("generated_at") or (quest or {}).get("generated_at"),
        "totals": {
            "videos": n,
            "worthwhile": edu.get("high", 0) + edu.get("moderate", 0),
            "attention": len(attention),
            "transferable": sum(1 for v in videos if v["transferable"]),
        },
        "domains": domains,
        "education": {k: edu.get(k, 0) for k in ("high", "moderate", "low", "none")},
        "videos": videos,
        "attention": [v["video_id"] for v in attention],
        "themes": (themes or {}).get("themes", []),
        "parent_summary": (themes or {}).get("parent_summary", ""),
        "unassigned_video_ids": (themes or {}).get("unassigned_video_ids", []),
        "quest": (quest or {}).get("quest"),
        "subscriptions": inp["subscriptions"],
    }


@app.exception_handler(Exception)
async def unhandled(_request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})


# Serve the static HTML/JS folder
if STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"),
                port=int(os.environ.get("PORT", "8080")), reload=False)
