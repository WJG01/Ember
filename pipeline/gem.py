"""
Ember - shared Gemini helper for pipeline stages 2 and 3.

Uses the same MODEL as content_sense.py so there is one place to change it
(or set the GEMINI_MODEL environment variable to override).
"""

import json
import os
import sys
import time

try:
    from google import genai
    from google.genai import types
except ImportError:
    sys.exit("pip install google-genai")

import content_sense

MODEL = os.environ.get("GEMINI_MODEL") or content_sense.MODEL
MAX_RETRIES = 4


def client():
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("Set GEMINI_API_KEY in the terminal that runs this (see README).")
    return genai.Client(api_key=key)


def generate_json(c, prompt, schema, temperature=0.4):
    """Text prompt in, schema-shaped dict out. Exits on errors that retrying cannot fix."""
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=schema,
        temperature=temperature,
    )
    for attempt in range(MAX_RETRIES):
        try:
            resp = c.models.generate_content(model=MODEL, contents=prompt, config=config)
            return json.loads(resp.text)
        except json.JSONDecodeError:
            print("      model returned invalid JSON, retrying")
            continue
        except Exception as e:
            msg = str(e)
            low = msg.lower()
            if "404" in msg and "model" in low:
                sys.exit(f"Model '{MODEL}' was not found for this key. "
                         "Run diagnose.py and set MODEL in content_sense.py.")
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "503" in msg or "UNAVAILABLE" in msg:
                wait = 20 * (attempt + 1)
                print(f"      rate limited, waiting {wait}s")
                time.sleep(wait)
                continue
            sys.exit(f"Gemini error: {msg[:300]}")
    sys.exit("Gemini kept failing after retries.")


def age_context(age):
    if age:
        return f"The child is about {age} years old."
    return "The child's age is unknown; assume roughly 8 to 13."
