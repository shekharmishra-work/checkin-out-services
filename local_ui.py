"""
EV Taxi Image Validator
Multi-image upload → Gemini vision → JSON validation results
"""

import io
import json
import os
import re
import threading
import time

import google.generativeai as genai
import streamlit as st
from dotenv import load_dotenv
from google.api_core import exceptions as api_exceptions
from PIL import Image

load_dotenv()

# ─── Config ───────────────────────────────────────────────────────────────────
MODEL_NAME = "gemini-2.5-flash"  # confirmed working — see diagnose.py
MAX_IMAGES_WARNING = 10  # soft limit — shows warning, still processes
MAX_IMAGE_PX = 1024  # longest side in pixels after resize
JPEG_QUALITY = 85
MAX_RETRIES = 3
THUMBS_PER_ROW = 4

# Semaphore: max 5 concurrent Gemini calls app-wide across all sessions
_api_semaphore = threading.Semaphore(5)

# ─── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="EV Taxi Validator",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─── CSS ──────────────────────────────────────────────────────────────────────
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700;800&display=swap');

html, body, [class*="css"], .stApp {
    font-family: 'Outfit', sans-serif;
}
.stApp {
    background:
        radial-gradient(circle at 8%  15%, rgba(16,185,129,.10) 0%, transparent 38%),
        radial-gradient(circle at 92% 85%, rgba(99,102,241,.10) 0%, transparent 38%),
        radial-gradient(circle at 50% 50%, rgba(59,130,246,.04) 0%, transparent 60%),
        #080d18;
}
.hero-title {
    background: linear-gradient(135deg, #10b981 0%, #3b82f6 55%, #6366f1 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    font-weight: 800;
    font-size: 3rem;
    letter-spacing: -1px;
    margin-bottom: .2rem;
    text-align: center;
}
.hero-sub {
    color: #6b7280;
    font-size: 1.1rem;
    font-weight: 300;
    text-align: center;
    margin-bottom: 2.5rem;
}
.badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: rgba(16,185,129,.10);
    border: 1px solid rgba(16,185,129,.25);
    color: #34d399;
    font-size: .75rem;
    font-weight: 600;
    padding: 4px 14px;
    border-radius: 999px;
    margin-bottom: 2rem;
}
.glass {
    background: rgba(15,23,42,.55);
    backdrop-filter: blur(18px);
    -webkit-backdrop-filter: blur(18px);
    border: 1px solid rgba(255,255,255,.06);
    border-radius: 20px;
    padding: 2rem 2.5rem;
    margin-bottom: 1.5rem;
    box-shadow: 0 24px 48px rgba(0,0,0,.35);
}
.thumb-label {
    font-size: .72rem;
    color: #6b7280;
    text-align: center;
    margin-top: 4px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.summary-box {
    background: rgba(59,130,246,.08);
    border: 1px solid rgba(59,130,246,.2);
    border-radius: 12px;
    padding: .9rem 1.4rem;
    color: #93c5fd;
    font-weight: 600;
    font-size: 1.05rem;
    margin-top: 1.2rem;
    text-align: center;
}
/* Buttons */
div.stButton > button {
    background: linear-gradient(135deg, #10b981, #059669) !important;
    color: #fff !important;
    border: none !important;
    padding: .7rem 2.2rem !important;
    font-weight: 700 !important;
    font-size: 1rem !important;
    border-radius: 12px !important;
    box-shadow: 0 4px 18px rgba(16,185,129,.35) !important;
    transition: all .25s ease !important;
}
div.stButton > button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 28px rgba(16,185,129,.55) !important;
}
div.stButton > button:active { transform: translateY(0) !important; }
</style>
""",
    unsafe_allow_html=True,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def get_api_key() -> str | None:
    """Read API key from st.secrets['GOOGLE_API_KEY'] or os.environ['GOOGLE_API_KEY']."""
    try:
        if "GOOGLE_API_KEY" in st.secrets:
            return st.secrets["GOOGLE_API_KEY"]
    except Exception:
        pass
    return os.environ.get("GOOGLE_API_KEY")


def preprocess_image(uploaded_file) -> Image.Image:
    """
    1. Open uploaded file as PIL Image
    2. Convert to RGB (strips transparency from PNG/RGBA)
    3. Resize so longest side ≤ MAX_IMAGE_PX (preserves aspect ratio)
    4. Re-encode as JPEG at JPEG_QUALITY → reload from buffer
    Returns a fresh PIL Image suitable for passing to Gemini.
    """
    img = Image.open(io.BytesIO(uploaded_file.getvalue()))

    # Convert to RGB
    if img.mode != "RGB":
        img = img.convert("RGB")

    # Resize
    w, h = img.size
    if max(w, h) > MAX_IMAGE_PX:
        scale = MAX_IMAGE_PX / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    # Re-encode as JPEG to normalise format and reduce payload size
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    buf.seek(0)
    return Image.open(buf)


def build_prompt(n: int) -> str:
    return f"""You are a quality-control system for an EV taxi service.
{n} vehicle image(s) have been provided (Image 1 through Image {n}).

For EACH image, apply these two checks in order:

1. VEHICLE CHECK — Is this clearly a photo of a car or vehicle?
   • If NO  → mark invalid, reason: "Not a vehicle"

2. CLARITY CHECK (run only when vehicle check passes) — Is the image clear,
   well-lit, and unobstructed enough to positively identify the vehicle?
   Look for: motion blur, darkness/underexposure, physical obstruction,
   extreme low resolution, or image corruption.
   • If NO  → mark invalid with ONE concise sentence describing the issue
   • If YES → mark valid, reason: null

Return ONLY a raw JSON array. No markdown fences, no backticks, no extra text:
[
  {{"index": 1, "valid": true, "reason": null}},
  {{"index": 2, "valid": false, "reason": "Image is too dark to identify the vehicle"}},
  {{"index": 3, "valid": false, "reason": "Not a vehicle"}}
]

Evaluate exactly {n} image(s) and return exactly {n} entries in the array."""


def call_gemini_with_retry(contents: list, retries: int = MAX_RETRIES):
    """
    Acquire semaphore → call Gemini → release.
    Retries on ResourceExhausted (429) and ServiceUnavailable (5xx)
    with exponential back-off. Raises after all retries exhausted.
    """
    last_exc: Exception | None = None

    for attempt in range(retries):
        _api_semaphore.acquire()
        try:
            model = genai.GenerativeModel(MODEL_NAME)
            return model.generate_content(contents)

        except api_exceptions.ResourceExhausted as exc:
            last_exc = exc
            wait = 2**attempt
            time.sleep(wait)

        except api_exceptions.ServiceUnavailable as exc:
            last_exc = exc
            wait = 2**attempt
            time.sleep(wait)

        finally:
            _api_semaphore.release()

    raise RuntimeError(f"Gemini API unavailable after {retries} attempts. Last error: {last_exc}")


def parse_response(text: str) -> list[dict]:
    """Strip accidental markdown fences then parse JSON."""
    cleaned = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
    return json.loads(cleaned)


def thumbnail_grid(files: list) -> None:
    """Render uploaded images as a responsive thumbnail grid."""
    for row_start in range(0, len(files), THUMBS_PER_ROW):
        chunk = files[row_start : row_start + THUMBS_PER_ROW]
        cols = st.columns(THUMBS_PER_ROW)
        for col, f in zip(cols, chunk, strict=False):
            img = Image.open(io.BytesIO(f.getvalue()))
            col.image(img, use_column_width=True)
            col.markdown(
                f'<div class="thumb-label">{f.name}</div>',
                unsafe_allow_html=True,
            )


# ─── UI ───────────────────────────────────────────────────────────────────────

st.markdown('<div class="hero-title">⚡ EV Taxi Validator</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="hero-sub">Multi-image AI validation for rideshare and taxi fleets</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div style="text-align:center">'
    '<span class="badge">🟢 Powered by Gemini 2.5 Flash</span>'
    "</div>",
    unsafe_allow_html=True,
)

# ── Upload Section ──────────────────────────────────────────────────────────
st.markdown('<div class="glass">', unsafe_allow_html=True)
st.write("### 📁 Upload Vehicle Images")
st.write(
    "Upload one or more photos of your EV taxi. The AI will check each image for "
    "vehicle presence, clarity, lighting, and obstruction in a single pass."
)

uploaded_files = st.file_uploader(
    "Choose photos…",
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True,
    help="Accepted formats: JPG, JPEG, PNG",
)
st.markdown("</div>", unsafe_allow_html=True)

# ── Preview + Validate ─────────────────────────────────────────────────────
if uploaded_files:
    n = len(uploaded_files)

    if n > MAX_IMAGES_WARNING:
        st.warning(
            f"⚠️ {n} images uploaded — processing may take a moment. "
            f"For best speed, keep batches under {MAX_IMAGES_WARNING}."
        )

    # Thumbnail grid
    st.markdown('<div class="glass">', unsafe_allow_html=True)
    st.write(f"### 🖼️ Preview ({n} image{'s' if n > 1 else ''})")
    thumbnail_grid(uploaded_files)
    st.markdown("</div>", unsafe_allow_html=True)

    # Validate button
    col_btn, _ = st.columns([1, 3])
    with col_btn:
        do_validate = st.button("🔍 Validate Images", key="validate_btn")

    if do_validate:
        api_key = get_api_key()

        if not api_key:
            st.error(
                "🔑 **API Key Missing** — add `GEMINI_API_KEY=your_key` to your "
                "`.env` file or `st.secrets`."
            )
            st.stop()

        genai.configure(api_key=api_key)

        raw_response_text = ""
        try:
            with st.spinner(f"⏳ Validating {n} image{'s' if n > 1 else ''} with Gemini…"):
                # 1. Preprocess all images
                processed: list[Image.Image] = [preprocess_image(f) for f in uploaded_files]

                # 2. Build single API call: [img1, img2, ..., imgN, prompt]
                prompt = build_prompt(n)
                contents = processed + [prompt]

                # 3. Call Gemini with retry + semaphore
                response = call_gemini_with_retry(contents)
                raw_response_text = response.text or ""

            # 4. Parse JSON results
            results = parse_response(raw_response_text)

            # 5. Display per-image results
            st.markdown('<div class="glass">', unsafe_allow_html=True)
            st.write("### ✅ Validation Results")

            passed = 0
            for entry in results:
                idx = entry.get("index", "?")
                valid = entry.get("valid", False)
                reason = entry.get("reason") or ""
                fname = uploaded_files[idx - 1].name if isinstance(idx, int) and idx <= n else ""
                label = f"Image {idx}" + (f" — *{fname}*" if fname else "")

                if valid:
                    st.success(f"✅ {label}: Valid")
                    passed += 1
                else:
                    st.error(f"❌ {label}: {reason}")

            # 6. Summary
            st.markdown(
                f'<div class="summary-box">📊 {passed} of {n} '
                f"image{'s' if n > 1 else ''} passed validation</div>",
                unsafe_allow_html=True,
            )
            st.markdown("</div>", unsafe_allow_html=True)

        except json.JSONDecodeError:
            st.error("⚠️ Could not parse the validation response. See raw output below.")
            with st.expander("🔍 Raw Gemini response (debug)"):
                st.code(raw_response_text, language="text")

        except RuntimeError as exc:
            st.error(f"🚫 Validation service is busy, please try again in a moment.\n\n`{exc}`")

        except Exception as exc:
            st.error(f"⚠️ Unexpected error: {exc}")

else:
    st.markdown('<div class="glass">', unsafe_allow_html=True)
    st.info("ℹ️ Upload one or more vehicle photos above to begin validation.")
    st.markdown("</div>", unsafe_allow_html=True)
