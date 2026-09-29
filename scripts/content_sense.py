#!/usr/bin/env python3
"""
Ember pipeline - Stage 1: Content Sense

Reads the liked videos from ember_signals.json, sends each one to Gemini as a
YouTube URL, and extracts a structured record describing what the video
actually contains.

This is the stage that makes Ember different. We are NOT classifying titles.
Gemini watches the video.

The critical field is `underlying_draw`. `surface_topic` is what a naive
metadata reading would say ("Japanese food"). `underlying_draw` is what
actually holds the child's attention ("watching something made by hand with
precision"). The gap between those two is the product.

SETUP
-----
    pip install google-genai

    Get an API key from aistudio.google.com  ->  "Get API key"

    Windows:  set GEMINI_API_KEY=your-key-here
    mac/linux: export GEMINI_API_KEY=your-key-here

RUN
---
    python content_sense.py                      # reads ember_signals.json
    python content_sense.py --limit 5            # try 5 videos first
    python content_sense.py --input other.json

OUTPUT
------
    video_records.json      one record per video
    cache/<video_id>.json   per-video cache, safe to commit? NO - gitignore it

Videos are cached by id. A video's content is a property of the video, not of
the child who watched it, so this cache is shared and contains no personal
data. In production it becomes the `videoCache` Firestore collection.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

try:
    from google import genai
    from google.genai import types
except ImportError:
    sys.exit("pip install google-genai")

# Check the current model list in AI Studio's model picker if this errors.
MODEL = "gemini-3.8-flash"

CACHE_DIR = Path("cache")
OUTFILE = Path("video_records.json")

# Free tier is roughly 10-15 requests/minute. Pace ourselves.
SECONDS_BETWEEN_CALLS = 5
MAX_RETRIES = 4


# --------------------------------------------------------------------------
# The schema. Locked here deliberately - see the design doc, section 4.2.
# Changing this shape means re-running every video, so agree it as a team.
# --------------------------------------------------------------------------
RECORD_SCHEMA = {
    "type": "object",
    "properties": {
        "surface_topic": {
            "type": "string",
            "description": "What a naive reading of the title would say this is about. 2-5 words.",
        },
        "underlying_draw": {
            "type": "string",
            "description": "What actually holds a viewer's attention here, beneath the topic. One sentence.",
        },
        "concepts": {
            "type": "array",
            "items": {"type": "string"},
            "description": "3-6 specific concepts, techniques or ideas shown.",
        },
        "modality": {
            "type": "string",
            "enum": ["procedural", "narrative", "passive", "reactive"],
            "description": "procedural = shows how to do something. passive = entertainment only.",
        },
        "vocabulary_band": {
            "type": "string",
            "enum": ["age_6_8", "age_9_11", "age_12_14", "adult"],
        },
        "affect": {
            "type": "string",
            "description": "Emotional tone in 2-4 words, e.g. 'calm, methodical'.",
        },
        "latent_skill": {
            "type": "string",
            "description": "The real-world skill or capability this could grow into.",
        },
        "transferable": {
            "type": "boolean",
            "description": "Can this plausibly become an offline activity for a child? Loot-tier and rarity content is usually false.",
        },
        "evidence": {
            "type": "string",
            "description": "One concrete observation from the video that supports underlying_draw.",
        },
    },
    "required": [
        "surface_topic",
        "underlying_draw",
        "concepts",
        "modality",
        "vocabulary_band",
        "affect",
        "latent_skill",
        "transferable",
        "evidence",
    ],
}


PROMPT = """You are analysing a video that a child chose to watch, to understand what
genuinely interests them.

Watch the video. Then fill the schema.

The most important distinction:

- surface_topic is what someone would guess from the title alone. If it is a
  ramen video, the surface topic is Japanese food.
- underlying_draw is what actually holds attention. For that same ramen video
  it might be "watching something made by hand with visible precision" - which
  has nothing to do with food, and would equally explain a blacksmithing video
  or a machine working smoothly.

Do not let the surface topic leak into underlying_draw. Look past the subject
matter to the *pattern of appeal*.

Be concrete and specific. "Educational content" and "entertainment" are useless
answers. Ground `evidence` in something you actually observed in the video.

Set transferable to false when the interest can only really be satisfied by
watching - collectible rarity, loot tiers, speedrun records. These are real
interests but they do not convert into a weekend activity.
"""


def load_videos(path, limit):
    if not Path(path).exists():
        sys.exit(f"{path} not found. Run scripts/test_youtube_signals.py first.")
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    videos = data.get("likes", [])
    if not videos:
        sys.exit("No liked videos in that file.")
    return videos[:limit] if limit else videos


def analyse(client, video):
    """One video -> one structured record. Returns None on unrecoverable failure."""
    contents = types.Content(
        parts=[
            types.Part(text=PROMPT),
            types.Part(file_data=types.FileData(file_uri=video["url"])),
        ]
    )
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=RECORD_SCHEMA,
        temperature=0.4,
    )

    for attempt in range(MAX_RETRIES):
        try:
            resp = client.models.generate_content(
                model=MODEL, contents=contents, config=config
            )
            return json.loads(resp.text)
        except Exception as e:
            msg = str(e)
            # 429 = rate limit. Back off and retry.
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "503" in msg or "UNAVAILABLE" in msg:
                wait = 20 * (attempt + 1)
                print(f"      rate limited, waiting {wait}s")
                time.sleep(wait)
                continue
            # Private/unlisted/deleted videos cannot be processed. Skip them.
            if "403" in msg or "not found" in msg.lower() or "PERMISSION" in msg:
                print(f"      unavailable (private, unlisted or removed) - skipping")
                return None
            print(f"      error: {msg[:160]}")
            return None
    print("      gave up after retries")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="ember_signals.json")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("Set GEMINI_API_KEY. See SETUP in the docstring.")
    client = genai.Client(api_key=key)

    CACHE_DIR.mkdir(exist_ok=True)
    videos = load_videos(args.input, args.limit)
    print(f"\n{len(videos)} videos to process with {MODEL}\n")

    records, hits, done, skipped = [], 0, 0, 0

    for n, v in enumerate(videos, 1):
        vid = v["video_id"]
        cached = CACHE_DIR / f"{vid}.json"
        print(f"[{n}/{len(videos)}] {v['title'][:64]}")

        if cached.exists() and not args.no_cache:
            rec = json.loads(cached.read_text(encoding="utf-8"))
            hits += 1
            print("      cached")
        else:
            rec = analyse(client, v)
            if rec is None:
                skipped += 1
                continue
            cached.write_text(json.dumps(rec, indent=2), encoding="utf-8")
            done += 1
            print(f"      surface : {rec['surface_topic']}")
            print(f"      beneath : {rec['underlying_draw']}")
            print(f"      {rec['modality']} / transferable={rec['transferable']}")
            time.sleep(SECONDS_BETWEEN_CALLS)

        # Personal context (who watched it, when) stays separate from the
        # video analysis, which is shared and non-personal.
        records.append(
            {
                "video_id": vid,
                "url": v["url"],
                "title": v["title"],
                "channel": v.get("channel"),
                "liked_at": v.get("liked_at"),
                "analysis": rec,
            }
        )

    OUTFILE.write_text(json.dumps(records, indent=2), encoding="utf-8")

    print("\n" + "=" * 62)
    print(f"  analysed {done} · from cache {hits} · skipped {skipped}")
    print(f"  written to {OUTFILE}")
    print("=" * 62)

    # Quick sanity check on the thing that matters most.
    if records:
        print("\n  surface vs underlying - the gap IS the product:\n")
        for r in records[:8]:
            a = r["analysis"]
            print(f"   {a['surface_topic']:<28} -> {a['underlying_draw'][:70]}")
        t = sum(1 for r in records if r["analysis"]["transferable"])
        print(f"\n  {t}/{len(records)} transferable to an offline activity")
        print("\n  If surface and underlying read the same, the prompt needs work.")
        print("  That is the whole ballgame - check it before moving on.\n")


if __name__ == "__main__":
    main()
