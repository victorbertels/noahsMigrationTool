import io
import json
import re
import zipfile
from datetime import datetime, timezone
from typing import Optional

from api import (
    get_channel_link,
    get_location,
    list_all_locations,
    patch_channel_link,
    patch_location,
    prepare_put_payload,
    put_channel_link,
)

MIGRATED_MARKER_RE = re.compile(r"#MIGRATED[0-9a-fA-F]+#")

# Stays on the original location; destination already has its own copy.
RETAINED_TEST_CHANNEL = 1
RETAINED_TEST_CHANNEL_NAME = "Test Channel"


class AccountMoveGuardrailError(Exception):
    """Raised when a resource is outside the allowed original/destination accounts."""


def is_retained_test_channel(channel_link: dict) -> bool:
    try:
        channel = int(channel_link.get("channel"))
    except (TypeError, ValueError):
        return False
    name = (channel_link.get("name") or "").strip()
    return channel == RETAINED_TEST_CHANNEL and name.lower() == RETAINED_TEST_CHANNEL_NAME.lower()


def partition_channel_links(channel_links: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split into (movable, retained Test Channel links)."""
    movable = []
    retained = []
    for channel_link in channel_links:
        if is_retained_test_channel(channel_link):
            retained.append(channel_link)
        else:
            movable.append(channel_link)
    return movable, retained


def get_match_name(location: dict) -> str:
    """Location name used for matching, with any #MIGRATEDTO…# marker removed."""
    name = location.get("name") or ""
    return MIGRATED_MARKER_RE.sub("", name).strip()


def migrated_marker(destination_location_id: str) -> str:
    return f"#MIGRATED{destination_location_id}#"


def has_migrated_marker(name: str) -> bool:
    return bool(MIGRATED_MARKER_RE.search(name or ""))


def apply_migrated_marker(name: str, destination_location_id: str) -> str:
    marker = migrated_marker(destination_location_id)
    if marker in (name or ""):
        return name
    if has_migrated_marker(name):
        return MIGRATED_MARKER_RE.sub(marker, name)
    base = (name or "").rstrip()
    return f"{base} {marker}".strip()


def _sanitize_filename_part(value: str) -> str:
    sanitized = re.sub(r"[^\w\-]+", "_", value.strip())
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    return sanitized[:80] or "location"


def _require_accounts(original_account_id: str, destination_account_id: str):
    if not original_account_id or not original_account_id.strip():
        raise AccountMoveGuardrailError("Original account ID is required.")
    if not destination_account_id or not destination_account_id.strip():
        raise AccountMoveGuardrailError("Destination account ID is required.")


def validate_location_belongs(location: dict, account_id: str, label: str = "Location"):
    location_account = location.get("account")
    if location_account != account_id:
        raise AccountMoveGuardrailError(
            f"{label} {location.get('_id')} belongs to account {location_account}, "
            f"expected {account_id}."
        )


def build_destination_index(destination_locations: list[dict]) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for location in destination_locations:
        name = get_match_name(location)
        if name:
            index[name] = location
    return index


def find_destination_by_name(
    name: Optional[str],
    destination_locations: list[dict],
) -> Optional[dict]:
    if not name:
        return None
    return build_destination_index(destination_locations).get(name)


def classify_location(
    original: dict,
    destination: Optional[dict],
    movable_channel_links: Optional[list] = None,
) -> str:
    name = original.get("name") or ""

    if has_migrated_marker(name):
        return "already_moved"

    if movable_channel_links is None:
        # IDs only — treat any remaining links as potentially movable until fetched.
        channel_links = original.get("channelLinks") or []
        if not channel_links:
            return "already_moved"
    elif not movable_channel_links:
        return "already_moved"

    if destination is None:
        return "unmatched"
    return "ready"


def _load_channel_links_for_location(
    location: dict,
    expected_account_id: str,
) -> list[dict]:
    location_id = location["_id"]
    channel_links = []
    for channel_link_id in location.get("channelLinks") or []:
        channel_link, channel_status = get_channel_link(channel_link_id)
        if channel_status != 200:
            raise RuntimeError(
                f"Failed to fetch channel link {channel_link_id}: HTTP {channel_status}"
            )
        if channel_link.get("account") != expected_account_id:
            raise AccountMoveGuardrailError(
                f"Channel link {channel_link_id} belongs to account "
                f"{channel_link.get('account')}, expected {expected_account_id}."
            )
        if channel_link.get("location") != location_id:
            raise AccountMoveGuardrailError(
                f"Channel link {channel_link_id} belongs to location "
                f"{channel_link.get('location')}, expected {location_id}."
            )
        channel_links.append(channel_link)
    return channel_links


def classify_account_locations(
    original_locations: list[dict],
    destination_locations: list[dict],
    original_account_id: str,
) -> list[dict]:
    dest_index = build_destination_index(destination_locations)
    rows = []
    for original in original_locations:
        match_name = get_match_name(original)
        destination = dest_index.get(match_name) if match_name else None

        all_channel_links = _load_channel_links_for_location(original, original_account_id)
        movable, retained = partition_channel_links(all_channel_links)
        status = classify_location(original, destination, movable_channel_links=movable)

        rows.append(
            {
                "status": status,
                "match_name": match_name,
                "original": original,
                "destination": destination,
                "channel_link_ids": [item["_id"] for item in movable],
                "retained_channel_link_ids": [item["_id"] for item in retained],
                "channel_links": movable,
                "retained_channel_links": retained,
            }
        )
    return rows


def fetch_move_snapshot(
    original_location_id: str,
    original_account_id: str,
    destination_account_id: str,
    destination_locations: Optional[list[dict]] = None,
) -> dict:
    _require_accounts(original_account_id, destination_account_id)

    original, status = get_location(original_location_id)
    if status != 200:
        raise RuntimeError(f"Failed to fetch location {original_location_id}: HTTP {status}")

    validate_location_belongs(original, original_account_id, "Original location")

    if destination_locations is None:
        destination_locations = list_all_locations(destination_account_id)

    match_name = get_match_name(original)
    destination = find_destination_by_name(match_name, destination_locations)

    all_channel_links = _load_channel_links_for_location(original, original_account_id)
    movable, retained = partition_channel_links(all_channel_links)
    status = classify_location(original, destination, movable_channel_links=movable)

    if destination is None and status != "already_moved":
        raise RuntimeError(
            f"No destination location found with name {match_name!r} "
            f"(original location {original.get('name')})."
        )

    if destination is not None:
        validate_location_belongs(destination, destination_account_id, "Destination location")

    return {
        "original_location": original,
        "destination_location": destination,
        "channel_links": movable,
        "retained_channel_links": retained,
        "match_name": match_name,
        "status": status,
    }


def create_account_move_backup_zip(
    moves: list[dict],
    original_account_id: str,
    destination_account_id: str,
    mode: str,
) -> tuple[bytes, str]:
    """Build a backup zip from a list of move snapshots (fetch_move_snapshot results)."""
    _require_accounts(original_account_id, destination_account_id)
    if not moves:
        raise RuntimeError("No moves to back up.")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    if len(moves) == 1:
        original = moves[0]["original_location"]
        name_part = _sanitize_filename_part(original.get("name", "location"))
        filename = f"account_move_backup_{name_part}_{original['_id']}_{timestamp}.zip"
    else:
        filename = f"account_move_backup_{mode}_{len(moves)}_locations_{timestamp}.zip"

    manifest_moves = []
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for move in moves:
            original = move["original_location"]
            destination = move["destination_location"]
            if destination is None:
                raise RuntimeError(
                    f"Cannot back up move for {original.get('_id')}: missing destination location."
                )
            original_id = original["_id"]
            prefix = f"moves/{original_id}"

            archive.writestr(
                f"{prefix}/original_location.json",
                json.dumps(original, indent=2),
            )
            archive.writestr(
                f"{prefix}/destination_location.json",
                json.dumps(destination, indent=2),
            )
            for channel_link in move["channel_links"]:
                archive.writestr(
                    f"{prefix}/channelLinks/{channel_link['_id']}.json",
                    json.dumps(channel_link, indent=2),
                )

            manifest_moves.append(
                {
                    "original_location_id": original_id,
                    "original_location_name": original.get("name"),
                    "destination_location_id": destination["_id"],
                    "destination_location_name": destination.get("name"),
                    "match_name": move.get("match_name"),
                    "channel_link_ids": [item["_id"] for item in move["channel_links"]],
                }
            )

        manifest = {
            "type": "account_move",
            "mode": mode,
            "original_account_id": original_account_id,
            "destination_account_id": destination_account_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "moves": manifest_moves,
        }
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))

    return buffer.getvalue(), filename


def load_account_move_backup_zip(zip_bytes: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("type") != "account_move":
            raise RuntimeError(
                f"Backup type is {manifest.get('type')!r}, expected 'account_move'."
            )

        moves = []
        for entry in manifest["moves"]:
            original_id = entry["original_location_id"]
            prefix = f"moves/{original_id}"
            original = json.loads(archive.read(f"{prefix}/original_location.json"))
            destination = json.loads(archive.read(f"{prefix}/destination_location.json"))
            channel_links = []
            for channel_link_id in entry["channel_link_ids"]:
                channel_links.append(
                    json.loads(archive.read(f"{prefix}/channelLinks/{channel_link_id}.json"))
                )
            moves.append(
                {
                    "original_location": original,
                    "destination_location": destination,
                    "channel_links": channel_links,
                    "match_name": entry.get("match_name"),
                }
            )

    return {"manifest": manifest, "moves": moves}


def validate_account_move_backup(
    backup: dict,
    original_account_id: str,
    destination_account_id: str,
):
    _require_accounts(original_account_id, destination_account_id)
    manifest = backup["manifest"]
    if manifest.get("type") != "account_move":
        raise AccountMoveGuardrailError(
            f"Backup type is {manifest.get('type')!r}, expected 'account_move'."
        )

    if manifest.get("original_account_id") != original_account_id:
        raise AccountMoveGuardrailError(
            f"Backup original account {manifest.get('original_account_id')} "
            f"does not match entered old account {original_account_id}."
        )
    if manifest.get("destination_account_id") != destination_account_id:
        raise AccountMoveGuardrailError(
            f"Backup destination account {manifest.get('destination_account_id')} "
            f"does not match entered new account {destination_account_id}."
        )

    for move in backup["moves"]:
        validate_location_belongs(
            move["original_location"], original_account_id, "Original location"
        )
        validate_location_belongs(
            move["destination_location"], destination_account_id, "Destination location"
        )


def _move_single_location(
    original: dict,
    destination: dict,
    channel_link_ids: list,
    original_account_id: str,
    destination_account_id: str,
    retained_channel_link_ids: Optional[list] = None,
) -> list[dict]:
    results = []
    original_id = original["_id"]
    destination_id = destination["_id"]
    original_name = original.get("name", original_id)
    retained_channel_link_ids = list(retained_channel_link_ids or [])

    if not channel_link_ids:
        results.append(
            {
                "type": "warning",
                "message": (
                    f"Location {original_name} has no channel links to move "
                    "(Test Channel is left in place) — skipped."
                ),
            }
        )
        return results

    # Refresh etags before mutating
    current_original, original_status = get_location(original_id)
    if original_status != 200:
        results.append(
            {
                "type": "location",
                "id": original_id,
                "name": original_name,
                "action": f"Failed to refresh original location {original_name}",
                "status": original_status,
                "ok": False,
            }
        )
        return results

    current_destination, destination_status = get_location(destination_id)
    if destination_status != 200:
        results.append(
            {
                "type": "location",
                "id": destination_id,
                "name": destination.get("name"),
                "action": f"Failed to refresh destination location {destination.get('name')}",
                "status": destination_status,
                "ok": False,
            }
        )
        return results

    validate_location_belongs(current_original, original_account_id, "Original location")
    validate_location_belongs(
        current_destination, destination_account_id, "Destination location"
    )

    moved_ids = []
    for channel_link_id in channel_link_ids:
        channel_link, channel_status = get_channel_link(channel_link_id)
        if channel_status != 200:
            results.append(
                {
                    "type": "channel_link",
                    "id": channel_link_id,
                    "status": channel_status,
                    "ok": False,
                    "action": f"Failed to fetch channel link {channel_link_id}",
                }
            )
            continue

        if is_retained_test_channel(channel_link):
            results.append(
                {
                    "type": "warning",
                    "message": (
                        f"Leaving Test Channel ({channel_link_id}) on {original_name}."
                    ),
                }
            )
            if channel_link_id not in retained_channel_link_ids:
                retained_channel_link_ids.append(channel_link_id)
            continue

        response_data, response_status = patch_channel_link(
            channel_link_id,
            {"account": destination_account_id, "location": destination_id},
            channel_link.get("_etag"),
        )
        ok = 200 <= response_status < 300
        if ok:
            moved_ids.append(channel_link_id)
        results.append(
            {
                "type": "channel_link",
                "id": channel_link_id,
                "name": channel_link.get("name"),
                "action": (
                    f"Moved channel link {channel_link.get('name') or channel_link_id} "
                    f"from {original_name} → {current_destination.get('name')}."
                ),
                "status": response_status,
                "ok": ok,
                "response": response_data,
            }
        )

    if not moved_ids:
        results.append(
            {
                "type": "warning",
                "message": (
                    f"Location {original_name} had nothing to move after skipping "
                    "Test Channel — skipped without renaming."
                ),
            }
        )
        return results

    new_name = apply_migrated_marker(current_original.get("name", ""), destination_id)
    original_payload = {"channelLinks": retained_channel_link_ids, "name": new_name}
    original_response, original_patch_status = patch_location(
        original_id,
        original_payload,
        current_original.get("_etag"),
    )
    retained_note = (
        f" Kept {len(retained_channel_link_ids)} Test Channel link(s) on original."
        if retained_channel_link_ids
        else ""
    )
    results.append(
        {
            "type": "location",
            "id": original_id,
            "name": new_name,
            "action": (
                f"Updated {original_name}: moved channel links away, renamed with "
                f"{migrated_marker(destination_id)}."
                f"{retained_note}"
            ),
            "status": original_patch_status,
            "ok": 200 <= original_patch_status < 300,
            "response": original_response,
        }
    )

    destination_links = list(current_destination.get("channelLinks") or [])
    for channel_link_id in moved_ids:
        if channel_link_id not in destination_links:
            destination_links.append(channel_link_id)

    # Re-fetch destination for fresh etag after CL patches may have side effects
    refreshed_destination, refreshed_status = get_location(destination_id)
    destination_etag = (
        refreshed_destination.get("_etag")
        if refreshed_status == 200
        else current_destination.get("_etag")
    )
    if refreshed_status == 200:
        destination_links = list(refreshed_destination.get("channelLinks") or [])
        for channel_link_id in moved_ids:
            if channel_link_id not in destination_links:
                destination_links.append(channel_link_id)

    destination_response, destination_patch_status = patch_location(
        destination_id,
        {"channelLinks": destination_links},
        destination_etag,
    )
    results.append(
        {
            "type": "location",
            "id": destination_id,
            "name": current_destination.get("name"),
            "action": (
                f"Updated destination {current_destination.get('name')} with "
                f"{len(destination_links)} channel link(s)."
            ),
            "status": destination_patch_status,
            "ok": 200 <= destination_patch_status < 300,
            "response": destination_response,
        }
    )

    return results


def run_account_move(
    original_location_ids: list[str],
    original_account_id: str,
    destination_account_id: str,
) -> list[dict]:
    _require_accounts(original_account_id, destination_account_id)
    destination_locations = list_all_locations(destination_account_id)
    results = []

    for original_location_id in original_location_ids:
        try:
            snapshot = fetch_move_snapshot(
                original_location_id,
                original_account_id,
                destination_account_id,
                destination_locations=destination_locations,
            )
        except (AccountMoveGuardrailError, RuntimeError) as error:
            results.append(
                {
                    "type": "warning",
                    "message": str(error),
                }
            )
            continue

        if snapshot["status"] == "already_moved":
            name = snapshot["original_location"].get("name")
            retained = snapshot.get("retained_channel_links") or []
            if retained and not snapshot.get("channel_links"):
                message = (
                    f"Location {name} ({original_location_id}) skipped — "
                    "only Test Channel remains (left in place)."
                )
            else:
                message = (
                    f"Location {name} ({original_location_id}) has already been moved "
                    "(no channel links to move)."
                )
            results.append({"type": "warning", "message": message})
            continue

        results.extend(
            _move_single_location(
                snapshot["original_location"],
                snapshot["destination_location"],
                [item["_id"] for item in snapshot["channel_links"]],
                original_account_id,
                destination_account_id,
                retained_channel_link_ids=[
                    item["_id"] for item in snapshot.get("retained_channel_links") or []
                ],
            )
        )

    return results


def run_account_move_revert(
    backup: dict,
    original_account_id: str,
    destination_account_id: str,
) -> list[dict]:
    validate_account_move_backup(backup, original_account_id, destination_account_id)
    results = []

    for move in backup["moves"]:
        original = move["original_location"]
        destination = move["destination_location"]
        original_id = original["_id"]
        destination_id = destination["_id"]
        channel_links = move["channel_links"]

        for channel_link in channel_links:
            channel_link_id = channel_link["_id"]
            current, current_status = get_channel_link(channel_link_id)
            if current_status != 200:
                results.append(
                    {
                        "type": "channel_link",
                        "id": channel_link_id,
                        "status": current_status,
                        "ok": False,
                        "action": f"Failed to fetch channel link {channel_link_id} for revert",
                    }
                )
                continue

            # First move account/location back, then restore full snapshot
            patch_data, patch_status = patch_channel_link(
                channel_link_id,
                {"account": original_account_id, "location": original_id},
                current.get("_etag"),
            )
            if not (200 <= patch_status < 300):
                results.append(
                    {
                        "type": "channel_link",
                        "id": channel_link_id,
                        "name": channel_link.get("name"),
                        "action": (
                            f"Failed to move channel link "
                            f"{channel_link.get('name') or channel_link_id} back to original."
                        ),
                        "status": patch_status,
                        "ok": False,
                        "response": patch_data,
                    }
                )
                continue

            refreshed, refreshed_status = get_channel_link(channel_link_id)
            if refreshed_status != 200:
                results.append(
                    {
                        "type": "channel_link",
                        "id": channel_link_id,
                        "status": refreshed_status,
                        "ok": False,
                        "action": f"Moved CL back but failed to refresh before PUT",
                    }
                )
                continue

            payload = prepare_put_payload(channel_link)
            response_data, response_status = put_channel_link(
                channel_link_id,
                payload,
                refreshed.get("_etag"),
            )
            results.append(
                {
                    "type": "channel_link",
                    "id": channel_link_id,
                    "name": channel_link.get("name"),
                    "action": (
                        f"Restored channel link {channel_link.get('name') or channel_link_id} "
                        f"to original location {original.get('name')}."
                    ),
                    "status": response_status,
                    "ok": 200 <= response_status < 300,
                    "response": response_data,
                }
            )

        current_original, original_status = get_location(original_id)
        if original_status != 200:
            results.append(
                {
                    "type": "location",
                    "id": original_id,
                    "status": original_status,
                    "ok": False,
                    "action": f"Failed to fetch original location {original_id} for revert",
                }
            )
        else:
            validate_location_belongs(
                current_original, original_account_id, "Original location"
            )
            # Only restore fields we changed on migrate — avoid PUT of read-only fields
            # like channelLinksDetails.
            original_payload = {
                "name": original.get("name"),
                "channelLinks": list(original.get("channelLinks") or []),
            }
            original_response, original_patch_status = patch_location(
                original_id,
                original_payload,
                current_original.get("_etag"),
            )
            results.append(
                {
                    "type": "location",
                    "id": original_id,
                    "name": original.get("name"),
                    "action": (
                        f"Restored original location {original.get('name')} "
                        f"(name + channelLinks)."
                    ),
                    "status": original_patch_status,
                    "ok": 200 <= original_patch_status < 300,
                    "response": original_response,
                }
            )

        current_destination, destination_status = get_location(destination_id)
        if destination_status != 200:
            results.append(
                {
                    "type": "location",
                    "id": destination_id,
                    "status": destination_status,
                    "ok": False,
                    "action": f"Failed to fetch destination location {destination_id} for revert",
                }
            )
        else:
            validate_location_belongs(
                current_destination, destination_account_id, "Destination location"
            )
            destination_payload = {
                "channelLinks": list(destination.get("channelLinks") or []),
            }
            destination_response, destination_patch_status = patch_location(
                destination_id,
                destination_payload,
                current_destination.get("_etag"),
            )
            results.append(
                {
                    "type": "location",
                    "id": destination_id,
                    "name": destination.get("name"),
                    "action": (
                        f"Restored destination location {destination.get('name')} "
                        f"channelLinks."
                    ),
                    "status": destination_patch_status,
                    "ok": 200 <= destination_patch_status < 300,
                    "response": destination_response,
                }
            )

    return results
