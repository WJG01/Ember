#!/usr/bin/env python3
"""
Ember backend (FastAPI) - an integration module for the Family Link web app.

    uvicorn app.main:app --port 8080        (run from the project root)

Endpoints
  GET  /auth/start          send the child to Google's consent screen
  GET  /auth/callback       Google returns here; the token is stored in data/token.json
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

Proof-of-concept notes: the API has no login and the token is a local file.
Do not expose this to the internet as it stands.
"""

import json
import os
import re
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"            # runtime results; the pipeline scripts run with this as cwd
PIPELINE = BASE / "pipeline"
DEMO_DIR = BASE / "demo_data"
STATIC = BASE / "static"
DATA.mkdir(exist_ok=True)

SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]
CLIENT_SECRET = Path(os.environ.get("EMBER_CLIENT_SECRET", BASE / "client_secret.json"))
TOKEN_FILE = DATA / "token.json"
SIGNALS = DATA / "ember_signals.json"

REDIRECT_URI = os.environ.get("EMBER_REDIRECT_URI", "http://localhost:8080/auth/callback")
DEMO_FORCED = os.environ.get("EMBER_DEMO") == "1"
CHILD_NAME = os.environ.get("EMBER_CHILD_NAME")
_age = os.environ.get("EMBER_CHILD_AGE", "")
DEFAULT_AGE = int(_age) if _age.isdigit() else None

if REDIRECT_URI.startswith("http://"):
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")  # local development only
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

app = FastAPI(title="Ember for Family Link")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def data_dir():
    """Real results if they exist, otherwise the bundled demo set."""
    if DEMO_FORCED:
        return DEMO_DIR, True
    if read_json(DATA / "video_records.json", None):  # missing or empty -> demo
        return DATA, False
    return DEMO_DIR, True


class PipelineError(Exception):
    pass


# --------------------------------------------------------------------------
# Google sign-in (web flow) - the child taps Allow once
# --------------------------------------------------------------------------
_pending_verifiers = {}  # state -> PKCE code_verifier


def _flow(state=None):
    from google_auth_oauthlib.flow import Flow
    return Flow.from_client_secrets_file(
        str(CLIENT_SECRET), scopes=SCOPES, redirect_uri=REDIRECT_URI, state=state
    )


@app.get("/auth/start")
def auth_start():
    if not CLIENT_SECRET.exists():
        return RedirectResponse("/?auth_error=missing_client_secret")
    flow = _flow()
    url, state = flow.authorization_url(
        access_type="offline",            # refresh token, so weekly syncs keep working
        prompt="consent select_account",  # always show the account picker
    )
    _pending_verifiers[state] = flow.code_verifier
    return RedirectResponse(url)


@app.get("/auth/callback")
def auth_callback(request: Request):
    params = request.query_params
    if params.get("error"):
        return RedirectResponse("/?auth_error=" + urllib.parse.quote(params["error"]))
    state = params.get("state")
    if not state or state not in _pending_verifiers:
        return RedirectResponse("/?auth_error=expired_session")
    try:
        flow = _flow(state=state)
        flow.code_verifier = _pending_verifiers.pop(state)
        # Rebuild the URL from the configured redirect URI so it also works behind a proxy.
        flow.fetch_token(authorization_response=REDIRECT_URI + "?" + request.url.query)
        TOKEN_FILE.write_text(flow.credentials.to_json(), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        print("auth callback failed:", e)
        return RedirectResponse("/?auth_error=token_exchange_failed")
    return RedirectResponse("/?connected=1")


@app.post("/api/disconnect")
def disconnect():
    TOKEN_FILE.unlink(missing_ok=True)
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


def fetch_signals():
    """Read likes + subscriptions with the stored token and write data/ember_signals.json."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    if not TOKEN_FILE.exists():
        raise PipelineError("YouTube is not connected yet. Use Connect YouTube first.")
    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
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
            raise PipelineError("The YouTube connection expired. Use Connect YouTube again.")
        raise PipelineError(f"YouTube returned an error: {text[:200]}")

    # keep guardian-saved videos; replace the YouTube likes with the fresh read
    existing = read_json(SIGNALS, {}) or {}
    saved = [v for v in existing.get("likes", []) if v.get("source") == "guardian_save"]
    merged = {v["video_id"]: v for v in likes}
    for v in saved:
        merged.setdefault(v["video_id"], v)

    SIGNALS.write_text(json.dumps({
        "channel": {"channel_id": channel["id"], "title": channel["snippet"]["title"]},
        "likes": list(merged.values()),
        "subscriptions": subs,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    return len(merged)


_YT_ID = re.compile(
    r"(?:youtu\.be/|youtube\.com/(?:watch\?(?:[^#]*&)?v=|shorts/|embed/|live/))([A-Za-z0-9_-]{11})")


class VideoIn(BaseModel):
    url: str = Field(max_length=300)


@app.get("/api/videos")
def list_videos():
    sig = read_json(SIGNALS, {}) or {}
    return {"videos": sig.get("likes", []), "subscriptions": sig.get("subscriptions", [])}


@app.post("/api/videos")
def add_video(body: VideoIn):
    text = body.url.strip()
    m = _YT_ID.search(text)
    if m:
        vid = m.group(1)
    elif re.fullmatch(r"[A-Za-z0-9_-]{11}", text):
        vid = text
    else:
        raise HTTPException(400, "That does not look like a YouTube link. Paste the full video address.")
    url = f"https://www.youtube.com/watch?v={vid}"

    title, channel = url, None
    try:  # public title lookup, no API key needed
        q = urllib.parse.urlencode({"url": url, "format": "json"})
        with urllib.request.urlopen(f"https://www.youtube.com/oembed?{q}", timeout=5) as r:
            meta = json.loads(r.read().decode("utf-8"))
            title, channel = meta.get("title", url), meta.get("author_name")
    except Exception:  # noqa: BLE001 - offline or blocked: fall back to the URL as title
        pass

    sig = read_json(SIGNALS, None) or {"channel": {}, "likes": [], "subscriptions": []}
    if any(v["video_id"] == vid for v in sig["likes"]):
        return {"ok": True, "duplicate": True, "title": title}
    sig["likes"].append({
        "video_id": vid, "title": title, "channel": channel,
        "liked_at": datetime.now(timezone.utc).isoformat(), "url": url, "source": "guardian_save",
    })
    SIGNALS.write_text(json.dumps(sig, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "duplicate": False, "title": title}


# --------------------------------------------------------------------------
# Pipeline runner (background thread; stage scripts run as subprocesses in data/)
# --------------------------------------------------------------------------
STEPS = [
    ("Watching the videos", "content_sense.py"),
    ("Finding what draws them", "curiosity_graph.py"),
    ("Planning this week's quest", "quest_planner.py"),
]

_lock = threading.Lock()
_state = {"running": False, "labels": [], "step_index": -1, "progress": None,
          "log": [], "error": None, "finished_at": None}
_PROGRESS = re.compile(r"^\[(\d+)/(\d+)\]")


def _set(**kw):
    with _lock:
        _state.update(kw)


def _log(line):
    with _lock:
        _state["log"].append(line)
        del _state["log"][:-80]
        m = _PROGRESS.match(line)
        if m:
            _state["progress"] = {"done": int(m.group(1)), "total": int(m.group(2))}


def _run_script(script, age):
    cmd = [sys.executable, str(PIPELINE / script)] + (["--age", str(age)] if age else [])
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace", env=env, cwd=DATA)
    last = ""
    for line in p.stdout:
        line = line.rstrip()
        if line:
            last = line
            _log(line)
    if p.wait() != 0:
        raise PipelineError(f"{script} stopped: {last or 'no output'}")


def _pipeline(sync, age):
    try:
        labels = (["Reading liked videos"] if sync else []) + [label for label, _ in STEPS]
        _set(labels=labels, step_index=0, progress=None, log=[], error=None)
        if sync:
            n = fetch_signals()
            _log(f"read {n} videos from YouTube")
            _set(step_index=1)
        elif not SIGNALS.exists():
            raise PipelineError("No videos yet. Connect YouTube or add a video link first.")
        offset = 1 if sync else 0
        for i, (_label, script) in enumerate(STEPS):
            _set(step_index=offset + i, progress=None)
            _run_script(script, age)
        _set(step_index=len(labels))
    except PipelineError as e:
        _set(error=str(e))
    except Exception as e:  # noqa: BLE001
        _set(error=f"{type(e).__name__}: {e}")
    finally:
        _set(running=False, finished_at=datetime.now(timezone.utc).isoformat())


class RunIn(BaseModel):
    sync: bool = False
    age: int | None = Field(default=None, ge=3, le=17)


def _start(sync, age):
    with _lock:
        if _state["running"]:
            raise HTTPException(409, "An analysis is already running.")
        _state.update(running=True, error=None, log=[], progress=None, step_index=0)
    threading.Thread(target=_pipeline, args=(sync, age or DEFAULT_AGE), daemon=True).start()
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
    with _lock:
        s = dict(_state)
        s["log"] = list(_state["log"][-12:])
    s["connected"] = TOKEN_FILE.exists()
    s["has_client_secret"] = CLIENT_SECRET.exists()
    s["has_gemini_key"] = bool(os.environ.get("GEMINI_API_KEY"))
    s["has_signals"] = SIGNALS.exists()
    return s


# --------------------------------------------------------------------------
# Report for the dashboard
# --------------------------------------------------------------------------
@app.get("/api/report")
def report():
    d, demo = data_dir()
    records = read_json(d / "video_records.json", []) or []
    themes = read_json(d / "themes.json", None)
    quest = read_json(d / "quest.json", None)
    signals = read_json(d / "ember_signals.json", {}) or {}
    sources = {x.get("video_id"): x.get("source") for x in signals.get("likes", [])}

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
            "source": sources.get(vid),
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

    channel_title = (signals.get("channel") or {}).get("title")
    child = CHILD_NAME or ("Llamie" if demo else None) or channel_title or "your child"

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
        "subscriptions": [s.get("title") for s in signals.get("subscriptions", [])],
    }


@app.exception_handler(Exception)
async def unhandled(_request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})


# static files last, so the API routes above win
app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=os.environ.get("HOST", "127.0.0.1"),
                port=int(os.environ.get("PORT", "8080")), reload=False)
