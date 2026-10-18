#!/usr/bin/env python3
"""
Ember pipeline - Stage 1: Content Sense (v2, parent-report edition)

Reads the child's videos from Datastore (kind Video), sends each one to Gemini as a
YouTube URL, and extracts a structured record that serves TWO readers:

  1. The PARENT dashboard  - what the video actually contained, whether it is
     worth the child's time, anything to be aware of, and what to talk about.
     Goal: the parent never has to rewatch the video to know.
  2. The CURIOSITY GRAPH   - the original fields (underlying_draw, concepts,
     latent_skill ...) are kept unchanged, so curiosity_graph.py still works.

v2 is ADDITIVE: every v1 field is still there. New fields are marked below.

SETUP
-----
    pip install -r requirements.txt
    gcloud auth application-default login        (local only; Cloud Run uses its service account)
    The Gemini key comes from env GEMINI_API_KEY or Secret Manager (see store.py).

RUN
---
    python content_sense.py                       # all of the child's videos
    python content_sense.py --limit 5             # try 5 first
    python content_sense.py --age 11              # calibrate safety to the child's age
    python content_sense.py --child default       # which Child (default: $EMBER_CHILD_ID or "default")
    python content_sense.py --no-cache            # force re-analysis

OUTPUT
------
    Datastore kind VideoAnalysis, keyed by video_id. It is shared by every child, so a
    video analysed once is never sent to Gemini again.

If you change RECORD_SCHEMA, bump ANALYSIS_SCHEMA_VERSION in store.py. Analyses stored
with an older version are ignored and re-analysed instead of crashing the run.
"""

import argparse
import json
import os
import sys
import time
from collections import Counter

try:
    from google import genai
    from google.genai import types
except ImportError:
    sys.exit("pip install google-genai")

import store

# Run diagnose.py to see which model names your key can use.
MODEL = os.environ.get("GEMINI_MODEL") or "gemini-3.8-flash"

SCHEMA_VERSION = store.ANALYSIS_SCHEMA_VERSION   # bump it in store.py

SECONDS_BETWEEN_CALLS = 5
MAX_RETRIES = 4

# Fixed taxonomy so the dashboard can chart "time by domain". Free text cannot
# be aggregated; an enum can.
DOMAINS = [
    "science_nature",
    "art_craft",
    "cooking_food",
    "building_engineering",
    "technology_coding",
    "math_logic",
    "music_performance",
    "sports_fitness",
    "stories_language",
    "history_culture",
    "life_skills",
    "gaming",
    "humor_entertainment",
    "toys_unboxing_shopping",
    "other",
]

SAFETY_FLAGS = [
    "none",
    "violence_or_gore",
    "scary_or_disturbing",
    "strong_language",
    "mature_themes",
    "risky_challenge_or_imitable_danger",
    "heavy_advertising_or_buying_pressure",
    "gambling_like_mechanics",
    "misleading_or_false_claims",
    "other",
]


# --------------------------------------------------------------------------
# Schema. Fields marked (v1) are the original locked schema, unchanged.
# Fields marked (v2) are new, for the parent dashboard.
# --------------------------------------------------------------------------
RECORD_SCHEMA = {
    "type": "object",
    "properties": {
        # ---------------- PARENT REPORT (v2) ----------------
        "summary": {
            "type": "string",
            "description": "2-3 plain sentences telling a parent what actually happens in the video, concretely, so they do not need to watch it. Describe what is shown and said, not the title.",
        },
        "key_points": {
            "type": "array",
            "items": {"type": "string"},
            "description": "2-4 specific things the video shows, explains or demonstrates, in the order they appear.",
        },
        "domain": {
            "type": "string",
            "enum": DOMAINS,
            "description": "The single best-fit domain for the dashboard.",
        },
        "topic": {
            "type": "string",
            "description": "The specific topic in 1-4 words, e.g. 'closed-jar terrariums'.",
        },
        "educational_value": {
            "type": "string",
            "enum": ["high", "moderate", "low", "none"],
            "description": "high = a child likely comes away knowing or able to do something specific. moderate = real but partial or incidental learning. low = mostly entertainment with minor learning. none = pure entertainment.",
        },
        "educational_reasoning": {
            "type": "string",
            "description": "One sentence justifying educational_value with something observed. Be honest: low or none is a valid answer.",
        },
        "what_child_may_learn": {
            "type": "array",
            "items": {"type": "string"},
            "description": "0-3 concrete things a child could pick up. Empty if nothing real.",
        },
        "age_suitability": {
            "type": "string",
            "enum": ["all_ages", "age_8_plus", "age_13_plus", "age_16_plus", "adult"],
        },
        "safety_flags": {
            "type": "array",
            "items": {"type": "string", "enum": SAFETY_FLAGS},
            "description": "Everything a parent should be aware of. Use ['none'] if nothing.",
        },
        "safety_note": {
            "type": "string",
            "description": "If any flag is set, say what and roughly where (e.g. 'around 3:20'). Otherwise an empty string.",
        },
        "parent_flag": {
            "type": "string",
            "enum": ["ok", "note", "review"],
            "description": "ok = nothing to act on. note = worth knowing. review = parent should probably look at this video or talk to the child.",
        },
        "conversation_starter": {
            "type": "string",
            "description": "One open question a parent could ask the child about this video, in a natural voice.",
        },
        "follow_up_idea": {
            "type": "string",
            "description": "One simple offline activity inspired by the video that a family could do. Empty string if transferable is false.",
        },
        # ---------------- CURIOSITY GRAPH (v1, unchanged) ----------------
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
        "summary", "key_points", "domain", "topic", "educational_value",
        "educational_reasoning", "what_child_may_learn", "age_suitability",
        "safety_flags", "safety_note", "parent_flag", "conversation_starter",
        "follow_up_idea",
        "surface_topic", "underlying_draw", "concepts", "modality",
        "vocabulary_band", "affect", "latent_skill", "transferable", "evidence",
    ],
}


PROMPT = """You are helping a parent understand a video their child chose to watch.
Watch the whole video. Base every answer on what you actually saw and heard,
never on the title alone. Then fill the schema.

AGE CONTEXT: __AGE_CONTEXT__

PART 1 - the parent report. The parent will NOT watch the video, so your
answers must stand in for it.
- summary: say concretely what happens. "A creator builds a closed-jar
  terrarium: gravel and charcoal drainage, soil, moss, then misting" is good.
  "A relaxing DIY video" is useless.
- educational_value: be honest and calibrated. Most entertainment is low or
  none, and that is fine to say. Do not inflate. Reserve "high" for videos where
  a child would plausibly learn something specific and correct.
- safety_flags and parent_flag: flag real issues a parent would want to know,
  such as risky stunts a child might copy, scary imagery, strong language,
  heavy sales pressure, gambling-like mechanics, or claims that are false or
  misleading. Do not flag harmless content. When you flag, say roughly where in
  the video in safety_note.
- conversation_starter: an open question that invites the child to explain or
  opine. Not a quiz, not "did you like it?".
- follow_up_idea: one simple thing a family could do offline. Empty string if
  the interest cannot become an offline activity.

PART 2 - the underlying pattern of appeal (used to build the child's profile).
- surface_topic is what someone would guess from the title alone.
- underlying_draw is what actually holds attention, beneath the subject. A
  ramen video might really be about "watching something made by hand with visible
  precision". Do not let the surface topic leak into underlying_draw.
- Set transferable to false when the interest can only really be satisfied by
  watching, such as collectible rarity, loot tiers or speedrun records.

Be concrete and specific throughout. Avoid filler like "educational content" or
"entertainment". Ground evidence in something you observed.
"""


def build_prompt(child_age):
    if child_age:
        ctx = (f"The child is about {child_age} years old. Judge age_suitability, "
               "safety_flags and vocabulary against that age.")
    else:
        ctx = ("The child's age is unknown. Judge suitability for a general audience "
               "of roughly ages 8 to 13.")
    return PROMPT.replace("__AGE_CONTEXT__", ctx)


def load_videos(child_id, limit):
    videos = store.list_videos(child_id)
    if not videos:
        sys.exit(f"No videos stored for child '{child_id}'. Sync YouTube or add a video link first.")
    return videos[:limit] if limit else videos


def tidy(rec):
    """Small consistency guards so the dashboard never shows a contradiction."""
    flags = [f for f in rec.get("safety_flags", []) if f != "none"]
    rec["safety_flags"] = flags or ["none"]
    if flags and rec.get("parent_flag") == "ok":
        rec["parent_flag"] = "note"
    if not rec.get("transferable"):
        rec["follow_up_idea"] = ""
    return rec


def analyse(client, video, prompt):
    """One video -> one structured record. Returns None for a skippable video.
    Exits the program on errors that would affect every video (bad model name)."""
    contents = types.Content(
        parts=[
            types.Part(text=prompt),
            types.Part(file_data=types.FileData(file_uri=video["url"])),
        ]
    )
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=RECORD_SCHEMA,
        temperature=0.3,
    )

    for attempt in range(MAX_RETRIES):
        try:
            resp = client.models.generate_content(
                model=MODEL, contents=contents, config=config
            )
            return tidy(json.loads(resp.text))
        except Exception as e:
            msg = str(e)
            low = msg.lower()

            # A bad model name fails EVERY video. Stop instead of skipping all.
            if "404" in msg and "model" in low:
                sys.exit(f"\nModel '{MODEL}' was not found for this key.\n"
                         "Run diagnose.py and set MODEL to a name it lists.")

            # Rate limit / temporary outage: back off and retry.
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "503" in msg or "UNAVAILABLE" in msg:
                wait = 20 * (attempt + 1)
                print(f"      rate limited, waiting {wait}s")
                time.sleep(wait)
                continue

            # Private, unlisted or deleted videos cannot be processed.
            if "403" in msg or "permission" in low or "private" in low or "not found" in low:
                print("      unavailable (private, unlisted or removed) - skipping")
                return None

            if isinstance(e, json.JSONDecodeError):
                print("      model returned invalid JSON, retrying")
                continue

            print(f"      error: {msg[:160]}")
            return None
    print("      gave up after retries")
    return None


def print_report(records):
    n = len(records)
    print("\n" + "=" * 62)
    print("  PARENT VIEW")
    print("=" * 62)
    for r in records:
        a = r["analysis"]
        mark = {"ok": " ", "note": "!", "review": "!!"}[a["parent_flag"]]
        print(f"\n [{mark:>2}] {r['title'][:60]}")
        print(f"       {a['domain']} / {a['topic']} / edu={a['educational_value']} / {a['age_suitability']}")
        print(f"       {a['summary']}")
        if a["safety_flags"] != ["none"]:
            print(f"       FLAGS: {', '.join(a['safety_flags'])} - {a['safety_note']}")

    print("\n" + "=" * 62)
    print("  DASHBOARD NUMBERS")
    print("=" * 62)
    dom = Counter(r["analysis"]["domain"] for r in records)
    edu = Counter(r["analysis"]["educational_value"] for r in records)
    print("\n  by domain:")
    for k, v in dom.most_common():
        print(f"    {k:<26} {v}  ({v * 100 // n}%)")
    print("\n  educational value:")
    for k in ["high", "moderate", "low", "none"]:
        print(f"    {k:<26} {edu.get(k, 0)}")
    flagged = [r for r in records if r["analysis"]["parent_flag"] != "ok"]
    print(f"\n  needs parent attention: {len(flagged)}/{n}")
    t = sum(1 for r in records if r["analysis"]["transferable"])
    print(f"  transferable to offline: {t}/{n}")

    print("\n  CURIOSITY GRAPH CHECK - surface vs underlying:")
    print("  (only meaningful across UNRELATED videos; similar videos")
    print("   rightly share a draw)\n")
    for r in records[:8]:
        a = r["analysis"]
        print(f"   {a['surface_topic']:<28} -> {a['underlying_draw'][:70]}")
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--child", default=os.environ.get("EMBER_CHILD_ID", "default"))
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--age", type=int, default=None, help="child's age, calibrates safety")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    try:
        client = genai.Client(api_key=store.gemini_key())
    except RuntimeError as e:
        sys.exit(str(e))

    videos = load_videos(args.child, args.limit)
    prompt = build_prompt(args.age)
    cache = {} if args.no_cache else store.get_analyses([v["video_id"] for v in videos])
    print(f"\n{len(videos)} videos to process with {MODEL}\n")

    records, hits, done, skipped = [], 0, 0, 0

    for n, v in enumerate(videos, 1):
        vid = v["video_id"]
        print(f"[{n}/{len(videos)}] {v['title'][:64]}")

        if vid in cache:
            rec = cache[vid]
            hits += 1
            print("      cached")
        else:
            rec = analyse(client, v, prompt)
            if rec is None:
                skipped += 1
                continue
            store.put_analysis(vid, rec, model=MODEL, calibrated_age=args.age)
            done += 1
            print(f"      {rec['domain']} / edu={rec['educational_value']} / flag={rec['parent_flag']}")
            time.sleep(SECONDS_BETWEEN_CALLS)

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

    print("\n" + "=" * 62)
    print(f"  analysed {done} · from cache {hits} · skipped {skipped}")
    print("  saved to Datastore (VideoAnalysis)")
    print("=" * 62)

    if records:
        print_report(records)


if __name__ == "__main__":
    main()
