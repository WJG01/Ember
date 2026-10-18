#!/usr/bin/env python3
"""
Ember - one-off import of the old local files into Datastore.

    python migrate_local.py                     # looks in the current folder
    python migrate_local.py --dir path/to/old --child default

Imports (whichever exist):
    ember_signals.json   -> Child (channel, subscriptions) + Video
    video_records.json   -> VideoAnalysis   (shared cache)
    cache/v2/*.json      -> VideoAnalysis
    themes.json          -> Themes
    quest.json           -> Quest

It does NOT import token.json. Re-connect YouTube through the web app instead,
so the token is created fresh and stored in Datastore.

Safe to run twice: every write is keyed, so a second run just overwrites.
"""

import argparse
import json
import os
import sys
from pathlib import Path

# # --- UNIVERSAL MOCK FOR CRYPTOGRAPHY ---
# import types

# class MockModule(types.ModuleType):
#     def __getattr__(self, name):
#         # Dynamically create any sub-attribute or submodule asked for
#         if name.startswith('__'):
#             raise AttributeError(name)
#         mock_sub = MockModule(name)
#         mock_sub.__path__ = []
#         return mock_sub

# # Setup the parent levels to catch deep imports
# dummy_crypto = MockModule("cryptography")
# dummy_crypto.__path__ = []
# dummy_crypto.exceptions = MockModule("exceptions")
# dummy_crypto.exceptions.InvalidSignature = Exception

# # Force Python's module engine to redirect all requests to our catch-all module
# sys.modules["cryptography"] = dummy_crypto
# sys.modules["cryptography.exceptions"] = dummy_crypto.exceptions

# # Intercept any deeper 'from cryptography.hazmat...' lookups dynamically
# class MockModuleFinder:
#     def find_spec(self, fullname, path, target=None):
#         if fullname.startswith("cryptography"):
#             from importlib.machinery import ModuleSpec
#             return ModuleSpec(fullname, None, is_package=True)
#         return None
#     def create_module(self, spec):
#         m = MockModule(spec.name)
#         m.__path__ = []
#         return m
#     def exec_module(self, module):
#         pass

# sys.meta_path.insert(0, MockModuleFinder())
# # -----------------------------------------------------

HERE = Path(__file__).resolve().parent
for _p in (HERE, HERE.parent / "pipeline", HERE / "pipeline"):
    sys.path.insert(0, str(_p))

import store


def read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=".")
    ap.add_argument("--child", default=os.environ.get("EMBER_CHILD_ID", "default"))
    ap.add_argument("--name", default=os.environ.get("EMBER_CHILD_NAME"))
    ap.add_argument("--age", type=int, default=None)
    args = ap.parse_args()
    d, child = Path(args.dir), args.child

    signals = read(d / "ember_signals.json")
    fields = {k: v for k, v in {"name": args.name, "age": args.age}.items() if v is not None}
    if signals:
        ch = signals.get("channel") or {}
        fields.update(channel_id=ch.get("channel_id"), channel_title=ch.get("title"),
                      subscriptions_json=json.dumps(signals.get("subscriptions", []), ensure_ascii=False))
    store.upsert_child(child, **fields)
    print(f"Child '{child}' ready")

    if signals:
        likes = signals.get("likes", [])
        store.put_videos(child, likes)
        print(f"  {len(likes)} videos")

    n = 0
    for rec in read(d / "video_records.json") or []:
        store.put_analysis(rec["video_id"], rec["analysis"])
        n += 1
    for f in sorted((d / "cache" / f"v{store.ANALYSIS_SCHEMA_VERSION}").glob("*.json")):
        a = read(f)
        if a:
            store.put_analysis(f.stem, a)
            n += 1
    print(f"  {n} analyses")

    for kind, name in (("Themes", "themes.json"), ("Quest", "quest.json")):
        doc = read(d / name)
        if doc:
            store.put_doc(kind, child, doc)
            print(f"  {kind} imported")

    print("Done. Now connect YouTube again through the web app.")


if __name__ == "__main__":
    main()
