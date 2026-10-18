#!/usr/bin/env python3
"""
Ember - diagnostic

Works out why content_sense.py is skipping every video.
(reads the first stored video from Datastore instead of data/ember_signals.json)
Prints the FULL error instead of swallowing it.

    python scripts/diagnose.py      (run from the project root)
"""

import json
import os
import sys
from pathlib import Path
from google import genai
from google.genai import types

HERE = Path(__file__).resolve().parent
for _p in (HERE, HERE.parent / "pipeline", HERE / "pipeline"):
    sys.path.insert(0, str(_p))
import store


# Check if we are running locally or on GCP
if os.environ.get("K_SERVICE"):  # This env var is automatically set by Cloud Run
    print("Running on Cloud Run. Authenticating via Vertex AI service account...")
    # Initialize using Vertex AI mode (Zero API keys required!)
    client = genai.Client(vertexai=True)
else:
    print("Running locally. Falling back to local environment key...")
    try:
        client = genai.Client(api_key=store.gemini_key())
    except RuntimeError as e:
        sys.exit(str(e))

# ---------------------------------------------------------------- 1. models
print("=" * 64)
print("MODELS AVAILABLE TO THIS KEY")
print("=" * 64)
usable = []
try:
    for m in client.models.list():
        actions = getattr(m, "supported_actions", None) or []
        if "generateContent" in actions or not actions:
            name = m.name.replace("models/", "")
            usable.append(name)
            print(f"  {name}")
except Exception as e:
    print(f"  could not list models: {e}")

if not usable:
    sys.exit("\nNo usable models. The API key is probably invalid.")

# Prefer a flash model
flash = [m for m in usable if "flash" in m and "lite" not in m and "image" not in m]
model = os.environ.get("GEMINI_MODEL") or "gemini-3.8-flash"
print(f"\n  --> will test with: {model}")

# ---------------------------------------------------------------- 2. text
print("\n" + "=" * 64)
print("TEST 1  plain text call")
print("=" * 64)
try:
    r = client.models.generate_content(model=model, contents="Say OK and nothing else.")
    print(f"  PASS  response: {r.text.strip()[:60]}")
except Exception as e:
    print(f"  FAIL  {type(e).__name__}: {e}")
    sys.exit("\nBasic calls are failing. Fix the key or model before going further.")

# ---------------------------------------------------------------- 3. video
print("\n" + "=" * 64)
print("TEST 2  YouTube video understanding")
print("=" * 64)

try:
    likes = store.list_videos(os.environ.get("EMBER_CHILD_ID", "default"))
except Exception as e:  # noqa: BLE001
    print(f"  could not read Datastore: {type(e).__name__}: {str(e)[:120]}")
    likes = []
url = likes[0]["url"] if likes else None
if url:
    print(f"  using the first stored video: {likes[0]['title'][:50]}")
else:
    url = "https://www.youtube.com/watch?v=aqz-KE-bpKQ"  # Big Buck Bunny, public
    print("  no stored videos found, using a known public video")

print(f"  {url}\n")

try:
    resp = client.models.generate_content(
        model=model,
        contents=types.Content(
            parts=[
                types.Part(text="In one sentence, what happens in this video?"),
                types.Part(file_data=types.FileData(file_uri=url)),
            ]
        ),
    )
    print(f"  PASS  {resp.text.strip()[:200]}")
    print("\n  Video understanding works. Update MODEL in pipeline/content_sense.py to:")
    print(f"      MODEL = \"{model}\"")
except Exception as e:
    print(f"  FAIL  {type(e).__name__}")
    print(f"  {e}\n")
    print("  Read the message above. Common causes:")
    print("   - model does not support video input  -> try another from the list")
    print("   - 429 / RESOURCE_EXHAUSTED            -> free tier limit, wait")
    print("   - 400 about file_uri                  -> SDK too old, pip install -U google-genai")
    print("   - PERMISSION / 403                    -> video is private or unlisted")

print()
