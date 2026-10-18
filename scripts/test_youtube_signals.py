#!/usr/bin/env python3
"""
Ember - Tier 1 signal test
Validates whether liked videos + subscriptions are readable via OAuth, using the
token the web app saved in Datastore (kind UserCredential).

SETUP
-----
1. Connect the child once through the web app (/auth/start). That stores the
   token in Datastore. The OAuth client id/secret come from Secret Manager.
2. pip install -r requirements.txt
3. Local runs: gcloud auth application-default login

RUN
---
    python scripts/test_youtube_signals.py [--child default]

Results are written to Datastore (Child + Video), not to a local file.
"""

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _p in (HERE, HERE.parent / "pipeline", HERE / "pipeline"):
    sys.path.insert(0, str(_p))

from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import store


def authenticate(child_id):
    """YouTube client from the stored token (auto-refreshed and re-saved by store.py)."""
    try:
        creds = store.google_credentials(child_id)
    except RefreshError as e:
        print(f"Stored YouTube grant no longer works ({e}). Connect again through the web app.")
        return None
    if not creds:
        print("Error: No YouTube credentials found in Datastore. Run the web login flow first.")
        return None
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def get_channel(yt):
    """The likes playlist id lives on the authenticated user's own channel."""
    resp = yt.channels().list(part="contentDetails,snippet", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        print(
            "No channel found on this account.\n"
            "The likes playlist only exists once the account has a YouTube channel."
        )
        return None
    ch = items[0]
    return {
        "channel_id": ch["id"],
        "title": ch["snippet"]["title"],
        "related": ch["contentDetails"]["relatedPlaylists"],
    }


def page_through(request_fn):
    """Collect all pages of a list endpoint."""
    out, token = [], None
    while True:
        resp = request_fn(token).execute()
        out.extend(resp.get("items", []))
        token = resp.get("nextPageToken")
        if not token:
            return out


def get_likes(yt, playlist_id):
    def req(token):
        return yt.playlistItems().list(
            part="snippet,contentDetails",
            playlistId=playlist_id,
            maxResults=50,
            pageToken=token,
        )

    return [
        {
            "video_id": i["contentDetails"]["videoId"],
            "title": i["snippet"]["title"],
            "channel": i["snippet"].get("videoOwnerChannelTitle"),
            "liked_at": i["snippet"].get("publishedAt"),
            "url": f"https://www.youtube.com/watch?v={i['contentDetails']['videoId']}",
            "source": "youtube_like",
        }
        for i in page_through(req)
        if i["snippet"].get("title") not in ("Deleted video", "Private video")
    ]


def get_subscriptions(yt):
    def req(token):
        return yt.subscriptions().list(
            part="snippet", mine=True, maxResults=50, pageToken=token
        )

    return [
        {
            "channel_id": i["snippet"]["resourceId"]["channelId"],
            "title": i["snippet"]["title"],
            "subscribed_at": i["snippet"].get("publishedAt"),
        }
        for i in page_through(req)
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--child", default=os.environ.get("EMBER_CHILD_ID", "default"))
    args = ap.parse_args()

    yt = authenticate(args.child)
    if not yt:
        sys.exit("Pipeline execution halted: Unauthenticated.")

    ch = get_channel(yt)
    if not ch:
        sys.exit("Pipeline execution halted: Missing channel structure.")

    print(f"\nAccount: {ch['title']}")
    print(f"Channel: {ch['channel_id']}")

    related = ch["related"]
    likes_id = related.get("likes")
    print(f"\nrelatedPlaylists: {json.dumps(related)}")
    print(f"  likes        -> {likes_id or 'NOT PRESENT'}")
    print(f"  watchHistory -> {related.get('watchHistory')}  (placeholder, always empty)")

    likes = []
    if likes_id:
        try:
            likes = get_likes(yt, likes_id)
        except HttpError as e:
            print(f"\n!! likes playlist unreadable: {e.status_code} {e.reason}")
            print("   THIS IS THE ANSWER WE NEEDED. Tier 1 likes path is blocked.")

    subs = get_subscriptions(yt)

    print("\n" + "=" * 58)
    print(f"  liked videos returned : {len(likes)}")
    print(f"  subscriptions returned: {len(subs)}")
    print("=" * 58)

    if likes:
        has_ts = sum(1 for v in likes if v["liked_at"])
        print(f"\n  timestamps present on {has_ts}/{len(likes)} likes")
        for v in likes[:10]:
            print(f"   - {v['title'][:60]}")
            print(f"     {v['channel']}  {v['liked_at']}")

    if subs:
        print("\n  subscriptions:")
        for s in subs:
            print(f"   - {s['title']}")

    # Save to Datastore: same effect as the app's sync (guardian-saved videos are kept).
    store.replace_youtube_likes(args.child, likes)
    store.upsert_child(
        args.child, connected=True, channel_id=ch["channel_id"], channel_title=ch["title"],
        subscriptions_json=json.dumps(subs, ensure_ascii=False), last_synced_at=store.iso_now(),
    )
    print(f"\nSaved {len(likes)} likes and {len(subs)} subscriptions to Datastore for child '{args.child}'.")


if __name__ == "__main__":
    main()
