"""
EV Taxi Image Validator Testing UI
Uploads images to the local FastAPI backend.
"""

import io

import requests
import streamlit as st
from PIL import Image

# ─── Config ───────────────────────────────────────────────────────────────────
API_URL = "http://127.0.0.1:8080/api/v1/validate-images"
THUMBS_PER_ROW = 4

# ─── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="EV Taxi Validator (Test UI)",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─── CSS ──────────────────────────────────────────────────────────────────────
st.markdown("""
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
</style>
""", unsafe_allow_html=True)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def thumbnail_grid(files: list) -> None:
    """Render uploaded images as a responsive thumbnail grid."""
    for row_start in range(0, len(files), THUMBS_PER_ROW):
        chunk = files[row_start : row_start + THUMBS_PER_ROW]
        cols = st.columns(THUMBS_PER_ROW)
        for col, f in zip(cols, chunk, strict=False):
            img = Image.open(io.BytesIO(f.getvalue()))
            col.image(img, use_container_width=True)
            col.markdown(
                f'<div class="thumb-label">{f.name}</div>',
                unsafe_allow_html=True,
            )


# ─── UI ───────────────────────────────────────────────────────────────────────

st.markdown('<div class="hero-title">⚡ EV Taxi API Tester</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="hero-sub">Upload test images to local FastAPI validation backend</div>',
    unsafe_allow_html=True,
)

# ── API URL input ──
st.markdown('<div class="glass">', unsafe_allow_html=True)
st.write("### 🔌 API Configuration")
api_endpoint = st.text_input("FastAPI Endpoint URL", value=API_URL)
st.markdown("</div>", unsafe_allow_html=True)

# ── Upload Section ──
st.markdown('<div class="glass">', unsafe_allow_html=True)
st.write("### 📁 Upload Vehicle Images")
uploaded_files = st.file_uploader(
    "Choose photos…",
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True,
)
st.markdown("</div>", unsafe_allow_html=True)

# ── Preview + Validate ──
if uploaded_files:
    n = len(uploaded_files)

    st.markdown('<div class="glass">', unsafe_allow_html=True)
    st.write(f"### 🖼️ Preview ({n} image{'s' if n > 1 else ''})")
    thumbnail_grid(uploaded_files)
    st.markdown("</div>", unsafe_allow_html=True)

    col_btn, _ = st.columns([1, 3])
    with col_btn:
        do_validate = st.button("🚀 Send to API")

    if do_validate:
        try:
            with st.spinner(f"⏳ Sending {n} image(s) to API..."):
                # Prepare multipart payload
                files_payload = []
                for f in uploaded_files:
                    # FastAPI expects 'images' as the form field name
                    files_payload.append(("images", (f.name, f.getvalue(), f.type)))

                # Make the POST request
                response = requests.post(api_endpoint, files=files_payload)

            if response.status_code == 200:
                data = response.json()

                st.markdown('<div class="glass">', unsafe_allow_html=True)
                st.write("### 📊 API Response")

                tab1, tab2, tab3 = st.tabs(["Overview", "Identity", "Detailed Results"])

                with tab1:
                    st.write("#### Submission Summary")
                    st.json(data.get("submission_summary", {}))

                with tab2:
                    st.write("#### Vehicle Identity Check")
                    st.json(data.get("identity", {}))

                with tab3:
                    st.write("#### Individual Image Results")
                    for res in data.get("results", []):
                        val = res.get("validation", {})
                        meta = res.get("metadata", {})

                        st.markdown(f"**{res.get('filename')} (Index {res.get('index')})**")

                        if val.get("valid"):
                            st.success(
                                f"✅ Valid | Plate: {val.get('plate')} | Color: {val.get('color')}"
                            )
                        else:
                            st.error(f"❌ Invalid | Reason: {val.get('reason')}")

                        if val.get("damage_detected"):
                            st.warning(f"⚠️ Damage Flagged: {val.get('damage_details')}")

                        with st.expander("Show EXIF Metadata"):
                            st.json(meta)
                        st.markdown("---")

                st.markdown("</div>", unsafe_allow_html=True)
            else:
                st.error(f"API Error {response.status_code}: {response.text}")

        except requests.exceptions.ConnectionError:
            st.error(f"Failed to connect to API at {api_endpoint}. Is the FastAPI server running?")
        except Exception as exc:
            st.error(f"⚠️ Unexpected error: {exc}")

else:
    st.markdown('<div class="glass">', unsafe_allow_html=True)
    st.info("ℹ️ Upload one or more vehicle photos above to begin testing the API.")
    st.markdown("</div>", unsafe_allow_html=True)
