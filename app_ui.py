import os

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from auth import set_credentials


def apply_styles():
    st.markdown(
        """
        <style>
            [data-testid="stSidebar"] { display: none; }
            [data-testid="collapsedControl"] { display: none; }
            .block-container { padding-top: 1.5rem; max-width: 820px; }
            .app-header {
                background: linear-gradient(135deg, #1a1f36 0%, #2d3561 100%);
                border-radius: 14px;
                padding: 1.6rem 1.8rem;
                margin-bottom: 1.2rem;
                color: #ffffff;
            }
            .app-header h1 {
                margin: 0;
                font-size: 1.75rem;
                font-weight: 700;
                letter-spacing: -0.02em;
            }
            .app-header p {
                margin: 0.35rem 0 0 0;
                color: #c8d0f0;
                font-size: 0.95rem;
            }
            .step-label {
                display: inline-block;
                background: #eef1ff;
                color: #3d4f9f;
                font-size: 0.72rem;
                font-weight: 700;
                letter-spacing: 0.06em;
                text-transform: uppercase;
                padding: 0.2rem 0.55rem;
                border-radius: 999px;
                margin-bottom: 0.35rem;
            }
            .location-card {
                background: #f7f8fc;
                border: 1px solid #e2e6f3;
                border-radius: 12px;
                padding: 1rem 1.2rem;
                margin: 0.5rem 0 1rem 0;
            }
            .location-card .name {
                font-size: 1.15rem;
                font-weight: 600;
                color: #1a1f36;
                margin: 0;
            }
            .location-card .id {
                font-size: 0.85rem;
                color: #6b7280;
                margin: 0.25rem 0 0 0;
                font-family: monospace;
            }
            .format-box {
                background: #f9fafb;
                border: 1px solid #e5e7eb;
                border-radius: 10px;
                padding: 1rem 1.2rem;
                font-size: 0.9rem;
                color: #374151;
            }
            .format-box code {
                background: #eef1ff;
                color: #3d4f9f;
                padding: 0.1rem 0.35rem;
                border-radius: 4px;
            }
            .format-box pre {
                background: #1a1f36;
                color: #e8ecff;
                border-radius: 8px;
                padding: 0.8rem 1rem;
                font-size: 0.82rem;
                margin: 0.6rem 0 0 0;
            }
            div[data-testid="stVerticalBlock"] > div[style*="border"] {
                border-radius: 12px !important;
                border-color: #e2e6f3 !important;
                background: #ffffff;
            }
            .stButton > button[kind="primary"] {
                background: #3d4f9f;
                border: none;
            }
            .stButton > button[kind="primary"]:hover {
                background: #2f3d7a;
                border: none;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header():
    st.markdown(
        """
        <div class="app-header">
            <h1>Noah's Quest Migration</h1>
            <p>Deliverect → Quest migration with backup &amp; restore</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_nav() -> str:
    if "active_page" not in st.session_state:
        st.session_state.active_page = "migrate"

    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            "Migrate",
            type="primary" if st.session_state.active_page == "migrate" else "secondary",
            use_container_width=True,
        ):
            st.session_state.active_page = "migrate"
            st.rerun()
    with col2:
        if st.button(
            "Revert",
            type="primary" if st.session_state.active_page == "revert" else "secondary",
            use_container_width=True,
        ):
            st.session_state.active_page = "revert"
            st.rerun()

    st.markdown("<div style='margin-bottom: 1.2rem'></div>", unsafe_allow_html=True)
    return st.session_state.active_page


def step_heading(title: str, step: str = None):
    if step:
        st.markdown(f'<span class="step-label">Step {step}</span>', unsafe_allow_html=True)
    st.markdown(f"#### {title}")


def location_card(name: str, location_id: str):
    st.markdown(
        f"""
        <div class="location-card">
            <p class="name">{name}</p>
            <p class="id">{location_id}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def format_box():
    st.markdown(
        """
        <div class="format-box">
            <strong>Expected format:</strong> a <code>.zip</code> backup created by this app.<br><br>
            <pre>manifest.json
location.json
channelLinks/
  {channelLinkId}.json
  ...</pre>
            Restores the full location and all channel links from the snapshot.
        </div>
        """,
        unsafe_allow_html=True,
    )


def get_config_value(key: str) -> str:
    value = os.getenv(key, "")
    try:
        return st.secrets[key]
    except Exception:
        return value


def load_credentials():
    client_id = get_config_value("CLIENT_ID")
    client_secret = get_config_value("CLIENT_SECRET")
    allowed_account_id = get_config_value("ALLOWED_ACCOUNT_ID")

    if not client_id or not client_secret or not allowed_account_id:
        st.error("App is not configured. Set CLIENT_ID, CLIENT_SECRET, and ALLOWED_ACCOUNT_ID in secrets.")
        st.stop()

    set_credentials(client_id, client_secret)
    return allowed_account_id.strip()


def show_results(results: list[dict]):
    if not results:
        return

    with st.container(border=True):
        st.markdown("**Results**")
        for result in results:
            if result.get("type") == "warning":
                st.warning(result["message"])
                continue

            message = result.get("action") or f"{result['type']} {result.get('name') or result.get('id')}"
            if result.get("ok"):
                st.success(message)
                st.caption(f"HTTP {result['status']}")
            else:
                st.error(message)
                st.caption(f"HTTP {result['status']}")
                if result.get("response"):
                    st.json(result["response"])


def init_migrate_session_state():
    defaults = {
        "location_id_input": "",
        "location_id": None,
        "location_name": None,
        "location_confirmed": False,
        "backup_bytes": None,
        "backup_filename": None,
        "backup_downloaded": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def reset_from_location_change():
    st.session_state.location_id = None
    st.session_state.location_name = None
    st.session_state.location_confirmed = False
    st.session_state.backup_bytes = None
    st.session_state.backup_filename = None
    st.session_state.backup_downloaded = False
