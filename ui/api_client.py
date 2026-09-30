"""
Thin client the Streamlit pages use to talk to the API. The UI never opens the database or
calls a language model itself; everything goes through the API.

    API_URL       base URL of the API (default http://127.0.0.1:8000)
    APP_API_KEY   sent as X-API-Key when set
"""

import html
import os
import sys
from pathlib import Path

import httpx
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))
from llm import load_env  # noqa: E402

load_env()
API_URL = os.getenv("API_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = httpx.Timeout(10.0, read=180.0)


class APIError(RuntimeError):
    """The API returned an error or could not be reached; the message is safe to show."""


def _headers():
    key = os.getenv("APP_API_KEY")
    return {"X-API-Key": key} if key else {}


def _handle(response):
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        if isinstance(detail, list):  # FastAPI validation errors
            detail = "; ".join(f"{'.'.join(map(str, d.get('loc', [])))}: {d.get('msg')}" for d in detail)
        raise APIError(f"{detail} (HTTP {response.status_code})")
    return response.json()


def get(path, **params):
    params = {k: v for k, v in params.items() if v is not None}
    try:
        return _handle(httpx.get(f"{API_URL}{path}", params=params, headers=_headers(), timeout=TIMEOUT))
    except httpx.HTTPError as exc:
        raise APIError(f"Cannot reach the API at {API_URL}: {exc}. Is it running (python run_app.py)?") from exc


def post(path, body):
    try:
        return _handle(httpx.post(f"{API_URL}{path}", json=body, headers=_headers(), timeout=TIMEOUT))
    except httpx.HTTPError as exc:
        raise APIError(f"Cannot reach the API at {API_URL}: {exc}. Is it running (python run_app.py)?") from exc


@st.cache_data(ttl=10, show_spinner=False)
def cached_get(path, **params):
    return get(path, **params)


# -----------------------------------------------------------------------------
#  Shared page furniture
# -----------------------------------------------------------------------------
ASSETS = Path(__file__).resolve().parent / "assets"
CSS = """
<style>
  .block-container {padding-top: 2.2rem; max-width: 1400px;}
  h1 {font-weight: 750; letter-spacing: -0.02em;}
  h2, h3 {font-weight: 650; letter-spacing: -0.01em;}
  div[data-testid="stMetric"] {background: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 0.8rem;
      padding: 0.9rem 1rem 0.6rem 1rem; box-shadow: 0 1px 2px rgba(16, 24, 40, 0.05);}
  div[data-testid="stMetricLabel"] p {font-size: 0.82rem; color: #6B7280; font-weight: 600;
      text-transform: uppercase; letter-spacing: 0.04em;}
  div[data-testid="stMetricValue"] {font-weight: 700;}
  div[data-testid="stVerticalBlockBorderWrapper"] {background: #FFFFFF;}
  .hero {background: linear-gradient(120deg, #4F46E5 0%, #7C3AED 100%); color: #FFFFFF;
      border-radius: 1rem; padding: 1.4rem 1.6rem; margin-bottom: 1.2rem;}
  .hero h1 {color: #FFFFFF; margin: 0 0 0.3rem 0; padding: 0;}
  .hero p {color: #E0E7FF; margin: 0; font-size: 1.02rem;}
  .pill {display: inline-block; padding: 0.15rem 0.6rem; border-radius: 999px; font-size: 0.8rem;
      font-weight: 600; margin-right: 0.35rem;}
</style>
"""


def setup(title):
    st.set_page_config(page_title=f"{title} · ITSM Insights", page_icon=str(ASSETS / "icon.svg"),
                       layout="wide")
    st.logo(str(ASSETS / "logo.svg"), icon_image=str(ASSETS / "icon.svg"), size="large")
    st.html(CSS)


def hero(title, subtitle):
    """Page header band used at the top of every page."""
    st.html(f"<div class='hero'><h1>{html.escape(title)}</h1><p>{html.escape(subtitle)}</p></div>")


PRIORITY_COLORS = {1: "#DC2626", 2: "#EA580C", 3: "#CA8A04", 4: "#16A34A"}
STATUS_COLORS = {"New": "#2563EB", "In Progress": "#7C3AED", "On Hold": "#CA8A04",
                 "Resolved": "#16A34A", "Closed": "#4B5563", "Cancelled": "#9CA3AF"}


def pill(text, color):
    """A coloured label. text is escaped (it can come from the database); color is ours."""
    return (f"<span class='pill' style='background:{color}1A;color:{color};"
            f"border:1px solid {color}55'>{html.escape(str(text))}</span>")


def sidebar():
    """Dataset and model pickers, shared by every page through session_state."""
    st.sidebar.markdown("### Settings")
    # Streamlit drops widget state when a page does not render the widget; re-assigning the
    # values keeps the choices when moving between pages.
    for key in [k for k in st.session_state.keys() if k in ("dataset", "provider") or k.startswith("model_")]:
        st.session_state[key] = st.session_state[key]
    try:
        health = cached_get("/health")
    except APIError as exc:
        st.sidebar.error(str(exc))
        st.stop()
    datasets = [name for name, d in health["datasets"].items() if d["exists"] and d["catalog"]]
    if not datasets:
        st.error("No dataset is ready. Run: python db/seed.py && python semantics/build_catalog.py")
        st.stop()
    st.session_state.setdefault("dataset", datasets[0])
    if st.session_state["dataset"] not in datasets:
        st.session_state["dataset"] = datasets[0]
    st.sidebar.selectbox("Dataset", datasets, key="dataset",
                         help="default = 500 incidents; large = built with /build-large")

    providers = health["providers"]
    ready = [p for p in providers if p["configured"]]
    labels = {p["name"]: f"{p['label']}" + ("" if p["configured"] else " (no key)") for p in providers}
    default = next((p["name"] for p in providers if p["is_default"] and p["configured"]),
                   ready[0]["name"] if ready else providers[0]["name"])
    st.session_state.setdefault("provider", default)
    st.sidebar.selectbox("Model provider", [p["name"] for p in providers], key="provider",
                         format_func=lambda n: labels[n])
    chosen = next(p for p in providers if p["name"] == st.session_state["provider"])
    st.session_state.setdefault(f"model_{chosen['name']}", chosen["default_model"])
    st.sidebar.text_input("Model", key=f"model_{chosen['name']}")
    if not chosen["configured"]:
        st.sidebar.warning(f"No API key for {chosen['label']}. Add it to .env and restart the API.")
    info = health["datasets"][st.session_state["dataset"]]
    st.sidebar.caption(f"Database **{info['file']}** · {info['size_mb']} MB · last changed "
                       f"{info['modified'].replace('T', ' ')[:16]} UTC")
    if st.sidebar.button("Refresh from database", help="Pages cache API answers for 10 seconds; "
                                                      "this reloads everything now."):
        st.cache_data.clear()
        st.rerun()
    st.sidebar.caption(f"API: {API_URL} · data as of {health.get('as_of', '2026-09-28')}")
    return health


def current_model():
    provider = st.session_state.get("provider")
    return provider, st.session_state.get(f"model_{provider}")
