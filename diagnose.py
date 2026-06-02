"""
Diagnostic script — run this BEFORE touching app.py.
Reveals: SDK version, API version being used, available models, and whether
a minimal generate_content call works at all.
"""

import os, sys
from dotenv import load_dotenv
load_dotenv()

API_KEY = os.environ.get("GOOGLE_API_KEY", "")
print(f"\n{'='*60}")
print("EV Taxi Validator — DIAGNOSTIC REPORT")
print(f"{'='*60}\n")

# ── 1. SDK version ─────────────────────────────────────────────
import google.genai as genai
import importlib.metadata
try:
    ver = importlib.metadata.version("google-genai")
    print(f"[1] google-genai SDK version : {ver}")
except Exception as e:
    print(f"[1] SDK version check failed : {e}")

# ── 2. API version the SDK uses ────────────────────────────────
try:
    # The SDK stores its default API version in the client's http config
    client = genai.Client(api_key=API_KEY)
    api_ver = getattr(client, "_api_version", None) \
        or getattr(getattr(client, "_http_options", None), "api_version", None) \
        or "unknown (check SDK internals)"
    print(f"[2] API version used by SDK  : {api_ver}")
except Exception as e:
    print(f"[2] Client creation failed   : {e}")
    sys.exit(1)

# ── 3. List ALL models the API returns for this key ────────────
print(f"\n[3] Models returned by client.models.list():")
try:
    models = list(client.models.list())
    if not models:
        print("     ⚠️  No models returned — key may lack permissions")
    for m in models:
        actions = getattr(m, "supported_actions", []) or []
        gc = "✅ generateContent" if "generateContent" in actions else "❌ no generateContent"
        print(f"     • {m.name:50s}  {gc}")
except Exception as e:
    print(f"     ERROR listing models: {e}")

# ── 4. Try a text-only call (no image) on common model names ──
print(f"\n[4] Probing models with a text-only ping:")
PROBE_MODELS = [
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-preview-05-20",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
    "models/gemini-1.5-flash",
    "models/gemini-1.5-pro",
]
for name in PROBE_MODELS:
    try:
        r = client.models.generate_content(
            model=name,
            contents=["Reply with just the word OK"],
            config={"max_output_tokens": 5, "temperature": 0},
        )
        txt = r.text if r.text else "(None)"
        print(f"     ✅ {name:45s} → '{txt}'")
    except Exception as e:
        short = str(e).splitlines()[0][:90]
        print(f"     ❌ {name:45s} → {short}")

print(f"\n{'='*60}\n")
