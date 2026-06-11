import os
from datetime import datetime, timezone
from typing import Optional

import requests
import streamlit as st


def _get_webhook_url() -> str:
    value = os.getenv("ZAPIER_WEBHOOK_URL", "")
    try:
        return st.secrets["ZAPIER_WEBHOOK_URL"]
    except Exception:
        return value


def _send(payload: dict):
    webhook_url = _get_webhook_url()
    if not webhook_url:
        return

    try:
        requests.post(webhook_url, json=payload, timeout=5)
    except Exception:
        pass


def _migrate_location_id() -> Optional[str]:
    location_id = st.session_state.get("location_id")
    if location_id:
        return location_id
    location_input = st.session_state.get("location_id_input", "")
    return location_input or None


def _migrate_location_name() -> Optional[str]:
    return st.session_state.get("location_name")


def _revert_location_id() -> Optional[str]:
    return st.session_state.get("revert_location_id")


def _revert_location_name() -> Optional[str]:
    return st.session_state.get("revert_location_name")


def track_page(action: str, location_id: Optional[str] = None, location_name: Optional[str] = None):
    """Fire once per page visit (not on every Streamlit rerun)."""
    last_page = st.session_state.get("_tracked_page")
    if last_page == action:
        return

    st.session_state["_tracked_page"] = action
    st.session_state["_tracked_action"] = action

    if location_id is None:
        if action == "migrate":
            location_id = _migrate_location_id()
            location_name = location_name or _migrate_location_name()
        elif action == "revert":
            location_id = _revert_location_id()
            location_name = location_name or _revert_location_name()

    _send(
        {
            "page": f"{action}_page_view_{location_name}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )


def track_event(
    event_name: str,
    action: Optional[str] = None,
    location_id: Optional[str] = None,
    location_name: Optional[str] = None,
    **details,
):
    """Fire when a user completes a meaningful action."""
    action = action or st.session_state.get("_tracked_action")

    if location_id is None:
        if action == "migrate":
            location_id = _migrate_location_id()
            location_name = location_name or _migrate_location_name()
        elif action == "revert":
            location_id = _revert_location_id()
            location_name = location_name or _revert_location_name()

    _send(
        {
            "page": f"{event_name}_{location_name}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
