import os

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from auth import set_credentials


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
    for result in results:
        if result.get("type") == "warning":
            st.warning(result["message"])
            continue

        message = result.get("action") or f"{result['type']} {result.get('name') or result.get('id')}"
        if result.get("ok"):
            st.success(message)
            st.caption(f"Done — HTTP {result['status']}")
        else:
            st.error(message)
            st.caption(f"Failed — HTTP {result['status']}")
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
