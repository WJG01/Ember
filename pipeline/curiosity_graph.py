#!/usr/bin/env python3
"""
Ember pipeline - Stage 2: Curiosity Graph

Joins the child's videos (kind Video) with their analyses (kind VideoAnalysis) and
groups them into 3-6 named themes: what DRAWS the child, which is not the same as
what the videos are about. Writes the Themes entity keyed by child_id.

    python curiosity_graph.py
    python curiosity_graph.py --age 11
    python curiosity_graph.py --child default
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

import gem
import store

SCHEMA = {
    "type": "object",
    "properties": {
        "parent_summary": {
            "type": "string",
            "description": "2-3 plain sentences for a parent: what this child's viewing says about them, and an honest note on how much of it is educational.",
        },
        "themes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Plain parent language, under six words, no colons, no jargon. Good: 'Taking ordinary things apart'.",
                    },
                    "insight": {
                        "type": "string",
                        "description": "1-2 sentences to a parent: what draws the child here, specifically.",
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Why these videos belong together even if their subjects differ.",
                    },
                    "video_ids": {"type": "array", "items": {"type": "string"}},
                    "evidence": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "2-3 short, concrete observations taken from the videos.",
                    },
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                    "trajectory": {
                        "type": "string",
                        "enum": ["rising", "steady", "fading", "unclear"],
                        "description": "From the liked_at dates. 'unclear' when there is too little spread or too few videos.",
                    },
                    "transferability": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                        "description": "How easily this interest becomes an offline activity.",
                    },
                    "growth_direction": {
                        "type": "string",
                        "description": "One sentence: a skill or hobby this interest could grow into.",
                    },
                },
                "required": [
                    "name", "insight", "reasoning", "video_ids", "evidence",
                    "confidence", "trajectory", "transferability", "growth_direction",
                ],
            },
        },
    },
    "required": ["parent_summary", "themes"],
}

PROMPT = """You are building a curiosity profile of a child for their parent.

__AGE__

Below are the videos the child liked. Each has already been analysed. Group them
into 3 to 6 themes (fewer if there are fewer than about 8 videos, never fewer
than 1).

What a theme is:
- A theme is a pattern of APPEAL, not a subject. Videos about completely
  different topics can share a theme if the same thing draws the child in (for
  example, watching something made by hand with visible precision can link a
  ramen video, a terrarium build and a machine working smoothly).
- Group on underlying_draw and the evidence fields, not on surface_topic or domain.
- Each video belongs to at most one theme. Leave a video out if it truly fits none.
- Keep themes with low transferability (collectible rarity, loot tiers, records).
  They are real interests. Mark them transferability=low rather than dropping them.

How to write it:
- name: plain parent language, under six words, no colons, no jargon.
  Good: "Taking ordinary things apart". Bad: "Subverting the Mundane: Re-Engineering
  Everyday Staples".
- insight, reasoning, evidence: be specific to these videos. Never invent details
  that are not in the data below.
- confidence: high only when 4 or more videos agree clearly; low when it rests on
  one or two.
- trajectory: use liked_at. If every like is within a day or two, say "unclear".
- parent_summary: speak to the parent directly. Be honest about the educational
  mix, do not flatter.

VIDEOS (JSON):
__VIDEOS__
"""


def compact(records):
    out = []
    for r in records:
        a = r.get("analysis", {})
        out.append({
            "id": r["video_id"],
            "title": r["title"],
            "liked_at": r.get("liked_at"),
            "domain": a.get("domain"),
            "surface_topic": a.get("surface_topic"),
            "underlying_draw": a.get("underlying_draw"),
            "concepts": a.get("concepts"),
            "modality": a.get("modality"),
            "affect": a.get("affect"),
            "latent_skill": a.get("latent_skill"),
            "transferable": a.get("transferable"),
            "evidence": a.get("evidence"),
            "educational_value": a.get("educational_value"),
        })
    return out


def clean_name(name):
    name = re.sub(r"[:—–]", " ", name or "")
    name = re.sub(r"\s+", " ", name).strip().rstrip(".")
    return name or "Untitled theme"


def finalise(raw, ordered_ids):
    """Drop unknown ids, enforce one-theme-per-video, tidy names, stable ids."""
    valid = set(ordered_ids)
    seen = set()
    themes = []
    for t in raw.get("themes", []):
        ids = [i for i in t.get("video_ids", []) if i in valid and i not in seen]
        if not ids:
            continue
        seen.update(ids)
        t["video_ids"] = ids
        t["video_count"] = len(ids)
        t["name"] = clean_name(t.get("name"))
        themes.append(t)
    themes.sort(key=lambda t: -t["video_count"])
    for n, t in enumerate(themes, 1):
        t["id"] = f"t{n}"
    return {
        "parent_summary": raw.get("parent_summary", "").strip(),
        "themes": themes,
        "unassigned_video_ids": [i for i in ordered_ids if i not in seen],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--child", default=os.environ.get("EMBER_CHILD_ID", "default"))
    ap.add_argument("--age", type=int, default=None)
    args = ap.parse_args()

    records = store.child_records(args.child)
    if not records:
        sys.exit("No analysed videos found. Run content_sense.py first.")

    videos = compact(records)
    prompt = (PROMPT.replace("__AGE__", gem.age_context(args.age))
                    .replace("__VIDEOS__", json.dumps(videos, indent=1, ensure_ascii=False)))

    print(f"\nBuilding themes from {len(videos)} videos with {gem.MODEL}\n")
    raw = gem.generate_json(gem.client(), prompt, SCHEMA, temperature=0.4)
    result = finalise(raw, [v["id"] for v in videos])
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    result["model"] = gem.MODEL
    result["child_age"] = args.age

    store.put_doc("Themes", args.child, result)

    print(f"  {result['parent_summary']}\n")
    for t in result["themes"]:
        print(f"  {t['name']}  ({t['video_count']} videos, {t['confidence']} confidence, "
              f"transferability {t['transferability']})")
        print(f"      {t['insight']}")
    if result["unassigned_video_ids"]:
        print(f"\n  {len(result['unassigned_video_ids'])} video(s) fit no theme")
    print("\n  saved to Datastore (Themes)\n")


if __name__ == "__main__":
    main()
