#!/usr/bin/env python3
"""
Ember pipeline - Stage 3: Quest Planner

Reads the Themes entity and the child's analysed videos from Datastore and
proposes ONE weekend activity that grows the child's strongest transferable
interest, with a split of who does what. Writes the Quest entity keyed by
child_id, which the dashboard renders as a printable Quest Card.

    python quest_planner.py
    python quest_planner.py --age 11
    python quest_planner.py --child default
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import gem
import store

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Short, inviting, under 8 words."},
        "theme_name": {"type": "string", "description": "The theme this grows, copied exactly from the input."},
        "why_this": {
            "type": "string",
            "description": "2 sentences to the parent tying the activity to specific videos the child liked.",
        },
        "duration_minutes": {"type": "integer"},
        "cost": {"type": "string", "enum": ["free", "low", "medium"]},
        "materials": {"type": "array", "items": {"type": "string"}, "description": "Common household or cheap items."},
        "steps": {"type": "array", "items": {"type": "string"}, "description": "3-6 short, concrete steps."},
        "child_role": {"type": "string", "description": "What the child leads. Tie it to what draws them."},
        "parent_role": {"type": "string", "description": "How the parent supports without taking over."},
        "conversation_prompt": {"type": "string", "description": "One open question to ask while doing it."},
        "success_looks_like": {"type": "string"},
        "safety_note": {"type": "string", "description": "Empty string if nothing needs saying."},
        "based_on_video_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "title", "theme_name", "why_this", "duration_minutes", "cost", "materials",
        "steps", "child_role", "parent_role", "conversation_prompt",
        "success_looks_like", "safety_note", "based_on_video_ids",
    ],
}

PROMPT = """You are planning one weekend activity for a family, based on what a child
has been watching.

__AGE__

Rules:
- Choose the ONE theme with the best mix of: high transferability, solid
  confidence, and a rising or steady trajectory. Skip themes whose
  transferability is low.
- The activity must end offscreen: hands-on, no screen needed to do it.
- 45 to 120 minutes, doable at home or nearby with common or cheap materials.
  Do not name specific shops, venues or prices you cannot verify.
- Ownership split: the child leads the part that matches what draws them (see the
  theme's insight). The parent supports, asks questions and keeps it safe.
- Do not base it on any video with a safety flag.
- why_this must reference specific videos the child liked by what happens in them.
- Be concrete. "Explore nature" is useless; "Build a closed jar garden with
  drainage layers, soil and moss" is useful.

THEMES (JSON):
__THEMES__

VIDEOS THE THEMES REFER TO (JSON):
__VIDEOS__
"""


def compact_videos(records):
    out = []
    for r in records:
        a = r.get("analysis", {})
        out.append({
            "id": r["video_id"],
            "title": r["title"],
            "summary": a.get("summary"),
            "follow_up_idea": a.get("follow_up_idea"),
            "safety_flags": a.get("safety_flags"),
            "transferable": a.get("transferable"),
        })
    return out


def finalise(quest, valid_ids, theme_names):
    quest["based_on_video_ids"] = [i for i in quest.get("based_on_video_ids", []) if i in valid_ids]
    if quest.get("theme_name") not in theme_names and theme_names:
        quest["theme_name"] = theme_names[0]
    try:
        quest["duration_minutes"] = int(quest.get("duration_minutes") or 60)
    except (TypeError, ValueError):
        quest["duration_minutes"] = 60
    return quest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--child", default=os.environ.get("EMBER_CHILD_ID", "default"))
    ap.add_argument("--age", type=int, default=None)
    args = ap.parse_args()

    themes = store.get_doc("Themes", args.child)
    if not themes:
        sys.exit("No themes found. Run curiosity_graph.py first.")
    records = store.child_records(args.child)
    if not records:
        sys.exit("No analysed videos found. Run content_sense.py first.")
    if not themes.get("themes"):
        sys.exit("The Themes entity has no themes.")

    theme_payload = [
        {k: t[k] for k in ("name", "insight", "confidence", "trajectory",
                           "transferability", "growth_direction", "video_ids")}
        for t in themes["themes"]
    ]
    prompt = (PROMPT.replace("__AGE__", gem.age_context(args.age))
                    .replace("__THEMES__", json.dumps(theme_payload, indent=1, ensure_ascii=False))
                    .replace("__VIDEOS__", json.dumps(compact_videos(records), indent=1, ensure_ascii=False)))

    print(f"\nPlanning this week's quest with {gem.MODEL}\n")
    quest = gem.generate_json(gem.client(), prompt, SCHEMA, temperature=0.6)
    quest = finalise(quest, {r["video_id"] for r in records}, [t["name"] for t in themes["themes"]])

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": gem.MODEL,
        "child_age": args.age,
        "quest": quest,
    }
    store.put_doc("Quest", args.child, result)

    print(f"  {quest['title']}  ({quest['duration_minutes']} min, cost: {quest['cost']})")
    print(f"  grows: {quest['theme_name']}")
    print(f"  {quest['why_this']}")
    print("\n  saved to Datastore (Quest)\n")


if __name__ == "__main__":
    main()
