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
       Download JSON, save in the project root as client_secret.json
4. pip install google-auth-oauthlib google-api-python-client

RUN
---
    python scripts/test_youtube_signals.py      (run from the project root)

A browser opens. Sign in AS THE TEST ACCOUNT, not your own.
Output is written to data/ember_signals.json
"""

import json
import os
import sys
from pathlib import Path

# Google Cloud & API Imports
from google.cloud import datastore
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# 1. Initialize Datastore Client targeted at the "ember" database
db = datastore.Client(database="ember")

SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]

def authenticate_production():
    """
    Retrieves OAuth credentials from Datastore, auto-refreshes them if expired,
    and returns a production-ready authenticated YouTube service client object.
    """
    # Fetch the token payload saved by the FastAPI web application
    token_key = db.key("UserCredential", "youtube_sync_token")
    token_entity = db.get(token_key)
    
    if not token_entity:
        print("Error: No YouTube credentials found in Datastore. Run the web login flow first.")
        return None

    # Reconstruct the Credentials object from the database fields
    creds = Credentials(
        token=token_entity.get("token"),
        refresh_token=token_entity.get("refresh_token"),
        token_uri=token_entity.get("token_uri"),
        client_id=token_entity.get("client_id"),
        client_secret=token_entity.get("client_secret"),
        scopes=token_entity.get("scopes")
    )

    # Automatically refresh the access token in the background using the long-term refresh token
    if creds and creds.expired and creds.refresh_token:
        print("YouTube access token expired. Refreshing token automatically...")
        creds.refresh(Request())
        
        # Save the updated token back to Datastore immediately
        token_entity["token"] = creds.token
        db.put(token_entity)

    return build("youtube", "v3", credentials=creds)


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
    # 2. Use the new non-interactive authentication system
    yt = authenticate_production()
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

    # ---- verdict logs (will be written to Cloud Logging) ----------------
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

    # 3. FIX: Replace local file open with Datastore entity creation
    signal_key = db.key("EmberSignal", "latest_pipeline_run")
    signal_entity = datastore.Entity(key=signal_key)
    
    # Store data directly as an entity payload instead of writing to disk
    signal_entity.update({
        "channel": ch,
        "likes": likes,
        "subscriptions": subs
    })
    db.put(signal_entity)
    
    print("\nPipeline execution complete. Results saved cleanly to Datastore entity 'latest_pipeline_run'.")


if __name__ == "__main__":
    main()
