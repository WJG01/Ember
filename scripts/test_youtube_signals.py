#!/usr/bin/env python3
"""
Ember - Tier 1 signal test
Validates whether liked videos + subscriptions are readable via OAuth.

SETUP
-----
1. GCP console -> enable "YouTube Data API v3"
2. APIs & Services -> OAuth consent screen
       User type: External
       Publishing status: Testing
       Test users: add your ember.test.* account
3. Credentials -> Create OAuth client ID -> Desktop app
       Download JSON, save next to this file as client_secret.json
4. pip install google-auth-oauthlib google-api-python-client

RUN
---
    python test_youtube_signals.py

A browser opens. Sign in AS THE TEST ACCOUNT, not your own.
Output is written to ember_signals.json
"""

import json
import os
import sys

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]
CLIENT_SECRET = "client_secret.json"
OUTFILE = "ember_signals.json"


def authenticate():
    if not os.path.exists(CLIENT_SECRET):
        sys.exit(f"Missing {CLIENT_SECRET}. See SETUP in the docstring.")
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
    creds = flow.run_local_server(port=8080, open_browser=False)
    return build("youtube", "v3", credentials=creds)


def get_channel(yt):
    """The likes playlist id lives on the authenticated user's own channel."""
    resp = yt.channels().list(part="contentDetails,snippet", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        sys.exit(
            "No channel on this account.\n"
            "The likes playlist only exists once the account has a YouTube channel.\n"
            "Go to youtube.com on the test account, create a channel, re-like the "
            "videos, then run this again."
        )
    ch = items[0]
    return {
        "channel_id": ch["id"],
        "title": ch["snippet"]["title"],
        "related": ch["contentDetails"]["relatedPlaylists"],
    }


def page_through(request_fn, yt):
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

    items = page_through(req, yt)
    return [
        {
            "video_id": i["contentDetails"]["videoId"],
            "title": i["snippet"]["title"],
            "channel": i["snippet"].get("videoOwnerChannelTitle"),
            # when it was ADDED to the likes playlist == when it was liked
            "liked_at": i["snippet"].get("publishedAt"),
            "url": f"https://www.youtube.com/watch?v={i['contentDetails']['videoId']}",
        }
        for i in items
    ]


def get_subscriptions(yt):
    def req(token):
        return yt.subscriptions().list(
            part="snippet", mine=True, maxResults=50, pageToken=token
        )

    items = page_through(req, yt)
    return [
        {
            "channel_id": i["snippet"]["resourceId"]["channelId"],
            "title": i["snippet"]["title"],
            "subscribed_at": i["snippet"].get("publishedAt"),
        }
        for i in items
    ]


def main():
    yt = authenticate()

    ch = get_channel(yt)
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

    # ---- verdict -------------------------------------------------------
    print("\n" + "=" * 58)
    print(f"  liked videos returned : {len(likes)}")
    print(f"  subscriptions returned: {len(subs)}")
    print("=" * 58)

    if likes:
        has_ts = sum(1 for v in likes if v["liked_at"])
        print(f"\n  timestamps present on {has_ts}/{len(likes)} likes")
        print("  (if yes, you get recency for free - feed it to the graph)\n")
        for v in likes[:10]:
            print(f"   - {v['title'][:60]}")
            print(f"     {v['channel']}  {v['liked_at']}")

    if subs:
        print("\n  subscriptions:")
        for s in subs:
            print(f"   - {s['title']}")

    print("\nCompare against what you actually liked and subscribed to.")
    print("A mismatch matters more than the absolute number.\n")

    with open(OUTFILE, "w") as f:
        json.dump(
            {"channel": ch, "likes": likes, "subscriptions": subs}, f, indent=2
        )
    print(f"Written to {OUTFILE}")
    print("Hand the URLs in that file to whoever is running Gate 0.\n")


if __name__ == "__main__":
    main()
