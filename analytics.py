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


def _account_move_location_id() -> Optional[str]:
    location_id = st.session_state.get("am_location_id")
    if location_id:
        return location_id
    return st.session_state.get("am_location_id_input") or None


def _account_move_location_name() -> Optional[str]:
    return st.session_state.get("am_location_name")


def _revert_location_id() -> Optional[str]:
    return st.session_state.get("revert_location_id")


def _revert_location_name() -> Optional[str]:
    return st.session_state.get("revert_location_name")


def _label(location_id: Optional[str], location_name: Optional[str]) -> str:
    return location_name or location_id or ""


def _resolve_location_context(
    action: Optional[str],
    location_id: Optional[str],
    location_name: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    if location_id is not None:
        return location_id, location_name

    if action == "migrate":
        return _migrate_location_id(), location_name or _migrate_location_name()
    if action in ("account_move",):
        return _account_move_location_id(), location_name or _account_move_location_name()
    if action in ("revert", "account_revert"):
        return _revert_location_id(), location_name or _revert_location_name()
    return None, location_name


def track_page(action: str, location_id: Optional[str] = None, location_name: Optional[str] = None):
    """Fire once per page visit (not on every Streamlit rerun)."""
    last_page = st.session_state.get("_tracked_page")
    if last_page == action:
        return

    st.session_state["_tracked_page"] = action
    st.session_state["_tracked_action"] = action

    location_id, location_name = _resolve_location_context(action, location_id, location_name)

    _send(
        {
            "page": f"{action}_page_view_{_label(location_id, location_name)}",
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
    location_id, location_name = _resolve_location_context(action, location_id, location_name)

    mode = details.get("mode") or st.session_state.get("am_mode")
    label = _label(location_id, location_name)
    if mode and action in ("account_move", "account_revert"):
        page = f"{event_name}_{mode}_{label}" if label else f"{event_name}_{mode}"
    else:
        page = f"{event_name}_{label}"

    _send(
        {
            "page": page,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
