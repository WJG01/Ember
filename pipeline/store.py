"""
Ember - storage layer (Cloud Datastore, database "ember") and secrets.

Every stage and the web app go through this module, so the kinds, keys and
index exclusions are defined in exactly one place.

Kinds
-----
Child           key: child_id                 name, age, connection state, channel, subscriptions
  Video         key: Child / video_id         one liked or guardian-saved video (personal)
UserCredential  key: child_id                 YouTube OAuth tokens (no client secret stored here)
VideoAnalysis   key: video_id                 Gemini analysis, SHARED across children
Themes          key: child_id                 whole themes document as one JSON string
Quest           key: child_id                 whole quest document as one JSON string
Run             key: run_id                   pipeline status / step / progress / error
OAuthState      key: state                    PKCE verifier for the sign-in round trip, short expiry

Rules baked in here
-------------------
* Indexed strings are limited to 1,500 bytes, so every long or never-queried
  property is listed in exclude_from_indexes. That also saves index writes.
* Entities are capped at 1 MiB, so Themes/Quest/VideoAnalysis are one JSON
  string each, not nested entities.
* No query here needs a composite index: only ancestor queries and key lookups.

Authentication: on Cloud Run the service account is used automatically.
Locally run:  gcloud auth application-default login
"""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from google.cloud import datastore

DATABASE = os.environ.get("EMBER_DATASTORE_DB", "ember")

# Bump when RECORD_SCHEMA in content_sense.py changes. Cached analyses with a
# different version are treated as missing and re-analysed.
ANALYSIS_SCHEMA_VERSION = 2

# Secret Manager ids. Change them here or with environment variables.
SECRET_GEMINI = os.environ.get("EMBER_SECRET_GEMINI", "gemini-api-key")
SECRET_OAUTH_CLIENT = os.environ.get("EMBER_SECRET_OAUTH_CLIENT", "ember-oauth-client")

OAUTH_STATE_TTL = timedelta(minutes=10)
RUN_STALE_AFTER = timedelta(minutes=15)  # a "running" run with no heartbeat this long is dead

CHILD_NOINDEX = ("subscriptions_json",)
VIDEO_NOINDEX = ("title", "channel", "url", "liked_at", "added_at")
CRED_NOINDEX = ("token", "refresh_token")
ANALYSIS_NOINDEX = ("payload",)
DOC_NOINDEX = ("payload",)
RUN_NOINDEX = ("labels_json", "log_json", "error")

_client = None


def db():
    global _client
    if _client is None:
        _client = datastore.Client(database=DATABASE)
    return _client


def now():
    return datetime.now(timezone.utc)


def iso_now():
    return now().isoformat()


def _new(key, props, no_index=()):
    e = datastore.Entity(key=key, exclude_from_indexes=tuple(no_index))
    e.update(props)
    return e


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


# --------------------------------------------------------------------------
# Secrets: environment variable first (Cloud Run --set-secrets, local dev),
# then Secret Manager.
# --------------------------------------------------------------------------
@lru_cache(maxsize=None)
def get_secret(env_name, secret_id, version="latest"):
    val = os.environ.get(env_name)
    if val:
        return val
    try:
        from google.cloud import secretmanager
        name = f"projects/{db().project}/secrets/{secret_id}/versions/{version}"
        resp = secretmanager.SecretManagerServiceClient().access_secret_version(
            request={"name": name})
        return resp.payload.data.decode("utf-8")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            f"Could not read secret '{secret_id}' (or env {env_name}). Check the secret "
            f"name and that the service account has roles/secretmanager.secretAccessor. "
            f"Underlying error: {type(e).__name__}: {str(e)[:160]}") from e


def gemini_key():
    return get_secret("GEMINI_API_KEY", SECRET_GEMINI)


def oauth_client_config():
    """The OAuth client JSON downloaded from the GCP console (a 'web' or 'installed' dict)."""
    return json.loads(get_secret("EMBER_CLIENT_SECRET_JSON", SECRET_OAUTH_CLIENT))


# --------------------------------------------------------------------------
# Child
# --------------------------------------------------------------------------
def child_key(child_id):
    return db().key("Child", child_id)


def get_child(child_id):
    e = db().get(child_key(child_id))
    return dict(e) if e else None


def upsert_child(child_id, **fields):
    """Read-merge-write in a transaction. Returns the merged properties."""
    key = child_key(child_id)
    with db().transaction():
        e = db().get(key)
        props = dict(e) if e else {"created_at": iso_now()}
        props.update(fields)
        props["updated_at"] = iso_now()
        db().put(_new(key, props, CHILD_NOINDEX))
    return props


def child_subscriptions(child):
    try:
        return json.loads((child or {}).get("subscriptions_json") or "[]")
    except json.JSONDecodeError:
        return []


# --------------------------------------------------------------------------
# YouTube OAuth credentials (one per child). The OAuth client id/secret live
# in Secret Manager and are NOT copied into Datastore.
# --------------------------------------------------------------------------
def save_credentials(child_id, creds):
    key = db().key("UserCredential", child_id)
    old = db().get(key) or {}
    refresh = creds.refresh_token or old.get("refresh_token")  # Google only sends it on first consent
    db().put(_new(key, {
        "token": creds.token,
        "refresh_token": refresh,
        "scopes": list(creds.scopes or []),
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
        "updated_at": iso_now(),
    }, CRED_NOINDEX))


def load_credentials(child_id):
    e = db().get(db().key("UserCredential", child_id))
    return dict(e) if e else None


def delete_credentials(child_id):
    db().delete(db().key("UserCredential", child_id))


def google_credentials(child_id):
    """Ready-to-use google.oauth2 Credentials, refreshed (and re-saved) if expired.
    Returns None when the child has not connected. May raise
    google.auth.exceptions.RefreshError if the grant was revoked."""
    row = load_credentials(child_id)
    if not row:
        return None
    from google.auth.transport.requests import Request as GoogleRequest
    from google.oauth2.credentials import Credentials

    cfg = oauth_client_config()
    c = cfg.get("web") or cfg.get("installed")
    expiry = None
    if row.get("expiry"):
        expiry = datetime.fromisoformat(row["expiry"]).replace(tzinfo=None)  # google-auth wants naive UTC
    creds = Credentials(
        token=row.get("token"), refresh_token=row.get("refresh_token"),
        token_uri=c["token_uri"], client_id=c["client_id"], client_secret=c["client_secret"],
        scopes=row.get("scopes"), expiry=expiry)
    if creds.refresh_token and not creds.valid:
        creds.refresh(GoogleRequest())
        save_credentials(child_id, creds)
    return creds


# --------------------------------------------------------------------------
# OAuthState (replaces the in-memory _pending_verifiers)
# --------------------------------------------------------------------------
def put_oauth_state(state, child_id, code_verifier):
    db().put(_new(db().key("OAuthState", state), {
        "child_id": child_id,
        "code_verifier": code_verifier,
        "expires_at": now() + OAUTH_STATE_TTL,   # also usable as a Datastore TTL field
    }))


def pop_oauth_state(state):
    """Single use. Returns the stored dict, or None if missing or expired."""
    key = db().key("OAuthState", state)
    with db().transaction():
        e = db().get(key)
        if not e:
            return None
        db().delete(key)
    if e.get("expires_at") and e["expires_at"] < now():
        return None
    return dict(e)


# --------------------------------------------------------------------------
# Video (personal: who liked what, and when)
# --------------------------------------------------------------------------
def video_key(child_id, video_id):
    return db().key("Child", child_id, "Video", video_id)


def get_video(child_id, video_id):
    e = db().get(video_key(child_id, video_id))
    return dict(e) if e else None


def put_videos(child_id, videos):
    ents = [_new(video_key(child_id, v["video_id"]), {
        "title": v.get("title") or "",
        "channel": v.get("channel"),
        "liked_at": v.get("liked_at"),
        "url": v["url"],
        "source": v.get("source") or "youtube_like",
        "added_at": iso_now(),
    }, VIDEO_NOINDEX) for v in videos]
    for chunk in _chunks(ents, 400):
        db().put_multi(chunk)


def list_videos(child_id):
    """All of a child's videos, newest like first."""
    q = db().query(kind="Video", ancestor=child_key(child_id))
    out = []
    for e in q.fetch():
        d = dict(e)
        d["video_id"] = e.key.name
        out.append(d)
    out.sort(key=lambda v: v.get("liked_at") or "", reverse=True)
    return out


def has_videos(child_id):
    q = db().query(kind="Video", ancestor=child_key(child_id))
    q.keys_only()
    return bool(list(q.fetch(limit=1)))


def replace_youtube_likes(child_id, likes):
    """Fresh YouTube read wins; guardian-saved videos are kept; likes that
    disappeared from YouTube are removed."""
    fresh = {v["video_id"] for v in likes}
    stale = [video_key(child_id, v["video_id"]) for v in list_videos(child_id)
             if v.get("source") == "youtube_like" and v["video_id"] not in fresh]
    for chunk in _chunks(stale, 400):
        db().delete_multi(chunk)
    put_videos(child_id, [{**v, "source": "youtube_like"} for v in likes])


# --------------------------------------------------------------------------
# VideoAnalysis (shared by every child: analyse a video once, ever)
# --------------------------------------------------------------------------
def get_analyses(video_ids):
    """{video_id: analysis dict} for ids already analysed with the current schema."""
    out = {}
    ids = list(dict.fromkeys(video_ids))
    for chunk in _chunks(ids, 500):
        for e in db().get_multi([db().key("VideoAnalysis", i) for i in chunk]):
            if e.get("schema_version") == ANALYSIS_SCHEMA_VERSION:
                out[e.key.name] = json.loads(e["payload"])
    return out


def put_analysis(video_id, analysis, model=None, calibrated_age=None):
    db().put(_new(db().key("VideoAnalysis", video_id), {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "model": model,
        "calibrated_age": calibrated_age,
        "domain": analysis.get("domain"),
        "analysed_at": iso_now(),
        "payload": json.dumps(analysis, ensure_ascii=False),
    }, ANALYSIS_NOINDEX))


def child_records(child_id):
    """Video + analysis joined, in the same shape video_records.json used to have."""
    videos = list_videos(child_id)
    analyses = get_analyses([v["video_id"] for v in videos])
    return [{
        "video_id": v["video_id"], "url": v.get("url"), "title": v.get("title") or "",
        "channel": v.get("channel"), "liked_at": v.get("liked_at"), "source": v.get("source"),
        "analysis": analyses[v["video_id"]],
    } for v in videos if v["video_id"] in analyses]


# --------------------------------------------------------------------------
# Themes / Quest: one entity each, whole document as a JSON string
# --------------------------------------------------------------------------
def put_doc(kind, child_id, doc):
    assert kind in ("Themes", "Quest")
    db().put(_new(db().key(kind, child_id), {
        "generated_at": doc.get("generated_at"),
        "payload": json.dumps(doc, ensure_ascii=False),
    }, DOC_NOINDEX))


def get_doc(kind, child_id):
    e = db().get(db().key(kind, child_id))
    return json.loads(e["payload"]) if e else None


# --------------------------------------------------------------------------
# Run (replaces the in-memory _state)
# --------------------------------------------------------------------------
class RunBusy(Exception):
    pass


def _run_entity(run_id, s):
    prog = s.get("progress") or {}
    return _new(db().key("Run", run_id), {
        "child_id": s["child_id"],
        "status": s["status"],                   # running | done | error
        "step_index": s["step_index"],
        "progress_done": prog.get("done"),
        "progress_total": prog.get("total"),
        "labels_json": json.dumps(s["labels"]),
        "log_json": json.dumps(s["log"][-80:], ensure_ascii=False),
        "error": s.get("error"),
        "age": s.get("age"),
        "sync": bool(s.get("sync")),
        "started_at": s["started_at"],
        "finished_at": s.get("finished_at"),
        "heartbeat": now(),
    }, RUN_NOINDEX)


def run_is_stale(run):
    hb = run.get("heartbeat")
    return run.get("status") == "running" and (not hb or now() - hb > RUN_STALE_AFTER)


def start_run(child_id, labels, age, sync):
    """Atomically claim the child's run slot. Raises RunBusy if one is live."""
    run_id = uuid.uuid4().hex
    state = {"child_id": child_id, "status": "running", "labels": labels, "step_index": 0,
             "progress": None, "log": [], "error": None, "age": age, "sync": sync,
             "started_at": iso_now(), "finished_at": None}
    ck = child_key(child_id)
    with db().transaction():
        child = db().get(ck)
        props = dict(child) if child else {"created_at": iso_now()}
        active = props.get("latest_run_id")
        if active:
            r = db().get(db().key("Run", active))
            if r and r.get("status") == "running" and not run_is_stale(r):
                raise RunBusy()
        props["latest_run_id"] = run_id
        props["updated_at"] = iso_now()
        db().put(_new(ck, props, CHILD_NOINDEX))
        db().put(_run_entity(run_id, state))
    return run_id, state


def save_run(run_id, state):
    db().put(_run_entity(run_id, state))


def get_run(run_id):
    e = db().get(db().key("Run", run_id))
    if not e:
        return None
    d = dict(e)
    d["labels"] = json.loads(d.pop("labels_json", None) or "[]")
    d["log"] = json.loads(d.pop("log_json", None) or "[]")
    d["progress"] = ({"done": d["progress_done"], "total": d["progress_total"]}
                     if d.get("progress_total") else None)
    return d
