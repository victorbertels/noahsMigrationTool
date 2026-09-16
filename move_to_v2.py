"""Move locations to Simphony Gen2 V2 sync mode (syncMode = 3)."""

from __future__ import annotations

import copy
from typing import Optional

from api import get_location, list_all_locations, patch_location

TARGET_SYNC_MODE = 3
SIMPHONY_KEY = "simphony_gen2"


def get_simphony_gen2(location: dict) -> dict:
    pos = location.get("posSettings") or {}
    if not isinstance(pos, dict):
        return {}
    simphony = pos.get(SIMPHONY_KEY) or {}
    return simphony if isinstance(simphony, dict) else {}


def get_sync_mode(location: dict) -> Optional[object]:
    return get_simphony_gen2(location).get("syncMode")


def location_has_v2_sync_mode(location: dict) -> bool:
    return get_sync_mode(location) == TARGET_SYNC_MODE


def build_v2_pos_settings(location: dict) -> dict:
    """Copy location posSettings and force simphony_gen2.syncMode = 3 (override)."""
    pos = copy.deepcopy(location.get("posSettings") or {})
    if not isinstance(pos, dict):
        pos = {}
    simphony = pos.get(SIMPHONY_KEY)
    if not isinstance(simphony, dict):
        simphony = {}
    else:
        simphony = dict(simphony)
    simphony["syncMode"] = TARGET_SYNC_MODE
    pos[SIMPHONY_KEY] = simphony
    return pos


def classify_locations_for_v2(locations: list[dict]) -> dict:
    """Split account locations into already-on-V2 vs needs-update."""
    ready = []
    needs_update = []
    for location in locations:
        row = {
            "location": location,
            "id": location.get("_id"),
            "name": location.get("name") or location.get("_id"),
            "sync_mode": get_sync_mode(location),
        }
        if location_has_v2_sync_mode(location):
            ready.append(row)
        else:
            needs_update.append(row)
    return {"ready": ready, "needs_update": needs_update}


def scan_account_for_v2(account_id: str) -> dict:
    locations = list_all_locations(account_id)
    classified = classify_locations_for_v2(locations)
    return {
        "account_id": account_id,
        "locations": locations,
        "ready": classified["ready"],
        "needs_update": classified["needs_update"],
    }


def update_location_to_v2(location: dict) -> dict:
    """Refresh location, force syncMode=3, patch. Propagates into existing posSettings."""
    location_id = location.get("_id")
    name = location.get("name") or location_id
    if not location_id:
        return {
            "type": "location",
            "id": None,
            "name": name,
            "action": "Location missing _id — skipped.",
            "ok": False,
            "status": None,
            "sync_mode_before": get_sync_mode(location),
            "sync_mode_after": None,
        }

    current, status = get_location(location_id)
    if status != 200:
        return {
            "type": "location",
            "id": location_id,
            "name": name,
            "action": f"Failed to refresh location before update (HTTP {status}).",
            "ok": False,
            "status": status,
            "sync_mode_before": get_sync_mode(location),
            "sync_mode_after": None,
            "response": current,
        }

    before = get_sync_mode(current)
    if before == TARGET_SYNC_MODE:
        return {
            "type": "location",
            "id": location_id,
            "name": current.get("name") or name,
            "action": f"Already on syncMode={TARGET_SYNC_MODE} — skipped.",
            "ok": True,
            "status": status,
            "sync_mode_before": before,
            "sync_mode_after": before,
        }

    pos_settings = build_v2_pos_settings(current)
    response, patch_status = patch_location(
        location_id,
        {"posSettings": pos_settings},
        current.get("_etag"),
    )
    ok = 200 <= patch_status < 300
    after = TARGET_SYNC_MODE if ok else before
    if ok and isinstance(response, dict) and response.get("posSettings") is not None:
        after = get_sync_mode(response)

    return {
        "type": "location",
        "id": location_id,
        "name": current.get("name") or name,
        "action": (
            f"Set posSettings.{SIMPHONY_KEY}.syncMode "
            f"{before!r} → {TARGET_SYNC_MODE} (override)."
            if ok
            else f"Failed to set syncMode={TARGET_SYNC_MODE}."
        ),
        "ok": ok,
        "status": patch_status,
        "sync_mode_before": before,
        "sync_mode_after": after,
        "response": response,
    }


def run_move_to_v2(
    locations: list[dict],
    on_progress=None,
) -> list[dict]:
    """Update every given location to syncMode=3. Returns result rows."""
    results = []
    total = max(len(locations), 1)
    for index, location in enumerate(locations):
        name = location.get("name") or location.get("_id") or f"#{index + 1}"
        if on_progress:
            on_progress(index / total, f"Updating {name}…")
        results.append(update_location_to_v2(location))
    if on_progress:
        on_progress(1.0, "Finished")
    return results
