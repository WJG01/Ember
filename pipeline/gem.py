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
import store

MODEL = os.environ.get("GEMINI_MODEL") or content_sense.MODEL
MAX_RETRIES = 4


def client():
    try:
        return genai.Client(api_key=store.gemini_key())
    except RuntimeError as e:
        sys.exit(str(e))


def generate_json(c, prompt, schema, temperature=0.4): 
    """Text prompt in, schema-shaped dict out. Exits on errors that retrying cannot fix."""
    config = types.GenerateContentConfig(
        response_mime_type="application/json", 
        response_schema=schema, 
        temperature=temperature,
    )
    
    last = ""
    for attempt in range(MAX_RETRIES):
        try:
            resp = c.models.generate_content(model=MODEL, contents=prompt, config=config)
            return json.loads(resp.text)
        except json.JSONDecodeError as e:  # Added 'as e' here
            last = f"invalid JSON: {e}"
            print(" model returned invalid JSON, retrying")
            continue
        except Exception as e:
            msg = str(e)
            low = msg.lower()
            
            if "404" in msg and "model" in low:
                sys.exit(f"Model '{MODEL}' was not found for this key. Run diagnose.py and set MODEL in content_sense.py.")
                
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "503" in msg or "UNAVAILABLE" in msg:
                last = msg[:300]
                wait = 20 * (attempt + 1)
                print(f" rate limited, waiting {wait}s: {last[:120]}")
                time.sleep(wait)
                continue
                
            # If it's an unrecoverable Gemini error, exit immediately
            sys.exit(f"Gemini error: {msg[:300]}")
            
    # This line runs only if the for-loop finishes MAX_RETRIES without returning
    sys.exit(f"Gemini kept failing after retries. Last error: {last}")


def age_context(age):
    if age:
        return f"The child is about {age} years old."
    return "The child's age is unknown; assume roughly 8 to 13."
