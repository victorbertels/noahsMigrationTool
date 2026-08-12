import io
import json
import re
import zipfile
from datetime import datetime, timezone
from typing import Optional

from api import (
    build_role_duplicate_payload,
    create_role,
    get_channel_link,
    get_location,
    get_role,
    get_user,
    list_all_locations,
    list_all_roles,
    list_all_users,
    patch_channel_link,
    patch_location,
    patch_user,
    prepare_put_payload,
    put_channel_link,
)

MIGRATED_MARKER_RE = re.compile(r"#MIGRATED(?:TO)?[0-9a-fA-F]+#")

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


def find_quest_users_for_location(users: list[dict], original_location_id: str) -> list[dict]:
    """Quest users: exactly one allowed location, and it is this original location."""
    matches = []
    for user in users:
        linked = user.get("locations") or []
        if len(linked) == 1 and linked[0] == original_location_id:
            matches.append(user)
    return matches


def build_users_by_location(users: list[dict]) -> dict[str, list[dict]]:
    """Index Quest users (exactly one location) by that location id."""
    by_location: dict[str, list[dict]] = {}
    for user in users:
        linked = user.get("locations") or []
        if len(linked) != 1:
            continue
        location_id = linked[0]
        by_location.setdefault(location_id, []).append(user)
    return by_location


def get_match_name(location: dict) -> str:
    """Location name used for matching, with any #MIGRATEDTO…# marker removed."""
    name = location.get("name") or ""
    return MIGRATED_MARKER_RE.sub("", name).strip()


def migrated_marker(destination_location_id: str) -> str:
    return f"#MIGRATEDTO{destination_location_id}#"


def has_migrated_marker(name: str) -> bool:
    return bool(MIGRATED_MARKER_RE.search(name or ""))


def strip_migrated_marker(name: str) -> str:
    """Remove any #MIGRATED…# / #MIGRATEDTO…# suffix from a location name."""
    return MIGRATED_MARKER_RE.sub("", name or "").strip()


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


def _require_role_group(role_group_id: str):
    if not role_group_id or not str(role_group_id).strip():
        raise AccountMoveGuardrailError(
            "Destination role ID is required before moving Quest users."
        )


def _role_name_key(name: Optional[str]) -> str:
    return (name or "").strip().lower()


def index_roles_by_id(roles: list[dict]) -> dict[str, dict]:
    return {
        str(role.get("_id")): role
        for role in roles
        if role.get("_id") is not None
    }


def index_roles_by_name(roles: list[dict]) -> dict[str, dict]:
    by_name: dict[str, dict] = {}
    for role in roles:
        key = _role_name_key(role.get("name"))
        if key and key not in by_name:
            by_name[key] = role
    return by_name


def _lookup_role(
    role_id: str,
    roles_by_id: dict[str, dict],
) -> Optional[dict]:
    if role_id in roles_by_id:
        return roles_by_id[role_id]
    role, status = get_role(role_id)
    if status == 200 and isinstance(role, dict) and role.get("_id"):
        roles_by_id[str(role["_id"])] = role
        return role
    return None


def resolve_or_duplicate_destination_role(
    source_role_id: Optional[str],
    destination_account_id: str,
    destination_roles_by_id: dict[str, dict],
    destination_roles_by_name: dict[str, dict],
    source_roles_by_id: dict[str, dict],
    fallback_role_id: Optional[str] = None,
    created_by_source_role_id: Optional[dict[str, str]] = None,
) -> tuple[str, str]:
    """Pick a destination role for a Quest user.

    Preference order:
    1. Same role id if it already exists on destination (e.g. global templates)
    2. Destination role with the same name
    3. Duplicate the source role onto the destination account
    4. Fallback destination role selected in the UI

    Returns (destination_role_id, resolution_note).
    """
    cache = created_by_source_role_id if created_by_source_role_id is not None else {}
    source_id = str(source_role_id).strip() if source_role_id else ""

    if source_id and source_id in cache:
        return cache[source_id], "reused previously duplicated role"

    if source_id and source_id in destination_roles_by_id:
        return source_id, "same role id on destination"

    source_role = _lookup_role(source_id, source_roles_by_id) if source_id else None
    if source_role:
        # Template roles are global — reuse the same id on any account.
        if source_role.get("template"):
            if source_id:
                cache[source_id] = source_id
            return source_id, "template role"

        name_key = _role_name_key(source_role.get("name"))
        matched = destination_roles_by_name.get(name_key) if name_key else None
        if matched and matched.get("_id"):
            dest_id = str(matched["_id"])
            if source_id:
                cache[source_id] = dest_id
            return dest_id, f"matched by name '{source_role.get('name')}'"

        # Duplicate custom (or missing) role onto destination.
        try:
            payload = build_role_duplicate_payload(source_role, destination_account_id)
        except ValueError as error:
            if fallback_role_id:
                return str(fallback_role_id), f"fallback ({error})"
            raise AccountMoveGuardrailError(str(error)) from error

        created, status = create_role(payload)
        if 200 <= status < 300 and isinstance(created, dict) and created.get("_id"):
            dest_id = str(created["_id"])
            destination_roles_by_id[dest_id] = created
            if name_key:
                destination_roles_by_name[name_key] = created
            if source_id:
                cache[source_id] = dest_id
            return dest_id, f"duplicated '{source_role.get('name')}' onto destination"

        # Race: another create may have landed the same name — reload by name.
        try:
            refreshed = list_all_roles(destination_account_id)
        except Exception:
            refreshed = []
        for role in refreshed:
            rid = role.get("_id")
            if rid is not None:
                destination_roles_by_id[str(rid)] = role
            key = _role_name_key(role.get("name"))
            if key and key not in destination_roles_by_name:
                destination_roles_by_name[key] = role
        matched = destination_roles_by_name.get(name_key) if name_key else None
        if matched and matched.get("_id"):
            dest_id = str(matched["_id"])
            if source_id:
                cache[source_id] = dest_id
            return dest_id, f"matched by name after create conflict '{source_role.get('name')}'"

        detail = created if isinstance(created, dict) else {}
        message = detail.get("_error", {}).get("message") or detail.get("message") or created
        if fallback_role_id:
            return (
                str(fallback_role_id),
                f"fallback (could not duplicate role: HTTP {status} {message})",
            )
        raise AccountMoveGuardrailError(
            f"Could not duplicate role '{source_role.get('name')}' onto destination "
            f"(HTTP {status}): {message}"
        )

    if fallback_role_id:
        return str(fallback_role_id), "fallback destination role"

    raise AccountMoveGuardrailError(
        "Quest user has no role, and no fallback destination role was selected."
    )


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
    original_users: Optional[list[dict]] = None,
) -> list[dict]:
    dest_index = build_destination_index(destination_locations)
    if original_users is None:
        original_users = list_all_users(original_account_id)
    users_by_location = build_users_by_location(original_users)
    rows = []
    for original in original_locations:
        match_name = get_match_name(original)
        destination = dest_index.get(match_name) if match_name else None

        all_channel_links = _load_channel_links_for_location(original, original_account_id)
        movable, retained = partition_channel_links(all_channel_links)
        status = classify_location(original, destination, movable_channel_links=movable)
        quest_users = users_by_location.get(original["_id"], [])

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
                "users": quest_users,
            }
        )
    return rows


def fetch_move_snapshot(
    original_location_id: str,
    original_account_id: str,
    destination_account_id: str,
    destination_locations: Optional[list[dict]] = None,
    original_users: Optional[list[dict]] = None,
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

    if original_users is None:
        original_users = list_all_users(original_account_id)
    quest_users = find_quest_users_for_location(original_users, original_location_id)

    return {
        "original_location": original,
        "destination_location": destination,
        "channel_links": movable,
        "retained_channel_links": retained,
        "users": quest_users,
        "match_name": match_name,
        "status": status,
    }


def create_account_move_backup_zip(
    moves: list[dict],
    original_account_id: str,
    destination_account_id: str,
    mode: str,
) -> tuple[bytes, str, dict]:
    """Build a backup zip from move snapshots.

    Includes every channel link on the original location (movable + retained Test Channel).
    Returns (zip_bytes, filename, summary).
    """
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
    total_channel_links = 0
    total_movable = 0
    total_users = 0
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

            movable = list(move.get("channel_links") or [])
            retained = list(move.get("retained_channel_links") or [])
            users = list(move.get("users") or [])
            by_id = {}
            for channel_link in movable + retained:
                channel_link_id = channel_link.get("_id")
                if not channel_link_id:
                    raise RuntimeError(
                        f"Channel link missing _id while backing up location {original_id}."
                    )
                by_id[channel_link_id] = channel_link

            # Also include any IDs listed on the location that were not partitioned
            # (should not happen, but keeps the zip complete).
            for channel_link_id in original.get("channelLinks") or []:
                if channel_link_id not in by_id:
                    channel_link, status = get_channel_link(channel_link_id)
                    if status != 200:
                        raise RuntimeError(
                            f"Failed to fetch channel link {channel_link_id} for backup: "
                            f"HTTP {status}"
                        )
                    by_id[channel_link_id] = channel_link

            archive.writestr(
                f"{prefix}/original_location.json",
                json.dumps(original, indent=2, default=str),
            )
            archive.writestr(
                f"{prefix}/destination_location.json",
                json.dumps(destination, indent=2, default=str),
            )

            all_ids = list(by_id.keys())
            movable_ids = [item["_id"] for item in movable]
            for channel_link_id, channel_link in by_id.items():
                archive.writestr(
                    f"{prefix}/channelLinks/{channel_link_id}.json",
                    json.dumps(channel_link, indent=2, default=str),
                )

            user_ids = []
            for user in users:
                user_id = user.get("_id")
                if not user_id:
                    raise RuntimeError(
                        f"User missing _id while backing up location {original_id}."
                    )
                user_ids.append(user_id)
                archive.writestr(
                    f"{prefix}/users/{user_id}.json",
                    json.dumps(user, indent=2, default=str),
                )

            total_channel_links += len(all_ids)
            total_movable += len(movable_ids)
            total_users += len(user_ids)
            manifest_moves.append(
                {
                    "original_location_id": original_id,
                    "original_location_name": original.get("name"),
                    "destination_location_id": destination["_id"],
                    "destination_location_name": destination.get("name"),
                    "match_name": move.get("match_name"),
                    "channel_link_ids": all_ids,
                    "movable_channel_link_ids": movable_ids,
                    "retained_channel_link_ids": [item["_id"] for item in retained],
                    "user_ids": user_ids,
                }
            )

        manifest = {
            "type": "account_move",
            "mode": mode,
            "original_account_id": original_account_id,
            "destination_account_id": destination_account_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "location_count": len(manifest_moves),
            "channel_link_count": total_channel_links,
            "movable_channel_link_count": total_movable,
            "user_count": total_users,
            "moves": manifest_moves,
        }
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, default=str))

    buffer.seek(0)
    zip_bytes = buffer.getvalue()
    summary = {
        "filename": filename,
        "location_count": len(manifest_moves),
        "channel_link_count": total_channel_links,
        "movable_channel_link_count": total_movable,
        "user_count": total_users,
        "size_bytes": len(zip_bytes),
    }
    return zip_bytes, filename, summary


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

            all_ids = entry.get("channel_link_ids") or []
            movable_ids = entry.get("movable_channel_link_ids")
            if movable_ids is None:
                # Older backups only stored movable links under channel_link_ids.
                movable_ids = all_ids

            channel_links = []
            for channel_link_id in movable_ids:
                channel_links.append(
                    json.loads(archive.read(f"{prefix}/channelLinks/{channel_link_id}.json"))
                )

            retained_channel_links = []
            for channel_link_id in entry.get("retained_channel_link_ids") or []:
                path = f"{prefix}/channelLinks/{channel_link_id}.json"
                if path in archive.namelist():
                    retained_channel_links.append(json.loads(archive.read(path)))

            users = []
            for user_id in entry.get("user_ids") or []:
                path = f"{prefix}/users/{user_id}.json"
                if path in archive.namelist():
                    users.append(json.loads(archive.read(path)))

            moves.append(
                {
                    "original_location": original,
                    "destination_location": destination,
                    "channel_links": channel_links,
                    "retained_channel_links": retained_channel_links,
                    "users": users,
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
    users: Optional[list] = None,
    role_group_id: Optional[str] = None,
    destination_roles_by_id: Optional[dict[str, dict]] = None,
    destination_roles_by_name: Optional[dict[str, dict]] = None,
    source_roles_by_id: Optional[dict[str, dict]] = None,
    created_roles_by_source_id: Optional[dict[str, str]] = None,
    on_progress=None,
) -> list[dict]:
    results = []
    original_id = original["_id"]
    destination_id = destination["_id"]
    original_name = original.get("name", original_id)
    destination_name = destination.get("name", destination_id)
    retained_channel_link_ids = list(retained_channel_link_ids or [])
    location_meta = {
        "original_location_id": original_id,
        "original_location_name": original_name,
        "destination_location_id": destination_id,
        "destination_location_name": destination_name,
    }

    def _progress(message: str):
        if on_progress:
            on_progress(message)

    if not channel_link_ids:
        results.append(
            {
                "type": "warning",
                "message": (
                    f"Location {original_name} has no channel links to move "
                    "(Test Channel is left in place) — skipped."
                ),
                **location_meta,
            }
        )
        return results

    _progress(f"Refreshing {original_name}…")
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
                **location_meta,
            }
        )
        return results

    current_destination, destination_status = get_location(destination_id)
    if destination_status != 200:
        results.append(
            {
                "type": "location",
                "id": destination_id,
                "name": destination_name,
                "action": f"Failed to refresh destination location {destination_name}",
                "status": destination_status,
                "ok": False,
                **location_meta,
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
                    **location_meta,
                }
            )
            _progress(f"{original_name}: failed to fetch channel link")
            continue

        if is_retained_test_channel(channel_link):
            results.append(
                {
                    "type": "warning",
                    "message": (
                        f"Leaving Test Channel ({channel_link_id}) on {original_name}."
                    ),
                    **location_meta,
                }
            )
            if channel_link_id not in retained_channel_link_ids:
                retained_channel_link_ids.append(channel_link_id)
            continue

        cl_label = channel_link.get("name") or channel_link_id
        _progress(f"{original_name}: moving {cl_label}…")
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
                    f"Moved channel link {cl_label} "
                    f"from {original_name} → {destination_name}."
                ),
                "status": response_status,
                "ok": ok,
                "response": response_data,
                **location_meta,
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
                **location_meta,
            }
        )
        return results

    _progress(f"{original_name}: updating original location…")
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
            "role": "original",
            "action": (
                f"Updated {original_name}: moved channel links away, renamed with "
                f"{migrated_marker(destination_id)}."
                f"{retained_note}"
            ),
            "status": original_patch_status,
            "ok": 200 <= original_patch_status < 300,
            "response": original_response,
            **location_meta,
        }
    )

    destination_links = list(current_destination.get("channelLinks") or [])
    for channel_link_id in moved_ids:
        if channel_link_id not in destination_links:
            destination_links.append(channel_link_id)

    _progress(f"{original_name}: updating destination {destination_name}…")
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
            "name": destination_name,
            "role": "destination",
            "action": (
                f"Updated destination {destination_name} with "
                f"{len(destination_links)} channel link(s)."
            ),
            "status": destination_patch_status,
            "ok": 200 <= destination_patch_status < 300,
            "response": destination_response,
            **location_meta,
        }
    )

    quest_users = list(users or [])
    if quest_users:
        dest_by_id = destination_roles_by_id if destination_roles_by_id is not None else {}
        dest_by_name = (
            destination_roles_by_name if destination_roles_by_name is not None else {}
        )
        source_by_id = source_roles_by_id if source_roles_by_id is not None else {}
        created_cache = (
            created_roles_by_source_id if created_roles_by_source_id is not None else {}
        )
        # Load role indexes lazily if the caller did not provide them.
        if destination_roles_by_id is None or destination_roles_by_name is None:
            dest_roles = list_all_roles(destination_account_id)
            dest_by_id = index_roles_by_id(dest_roles)
            dest_by_name = index_roles_by_name(dest_roles)
        if source_roles_by_id is None:
            source_by_id = index_roles_by_id(list_all_roles(original_account_id))

        for user in quest_users:
            user_id = user["_id"]
            user_label = user.get("name") or user.get("email") or user_id
            _progress(f"{original_name}: moving user {user_label}…")
            current_user, user_status = get_user(user_id)
            if user_status != 200:
                results.append(
                    {
                        "type": "user",
                        "id": user_id,
                        "name": user_label,
                        "action": f"Failed to fetch user {user_label}",
                        "status": user_status,
                        "ok": False,
                        **location_meta,
                    }
                )
                continue

            if current_user.get("account") != original_account_id:
                results.append(
                    {
                        "type": "warning",
                        "message": (
                            f"User {user_label} is not on the original account "
                            f"({current_user.get('account')}) — skipped."
                        ),
                        **location_meta,
                    }
                )
                continue

            linked = current_user.get("locations") or []
            if len(linked) != 1 or linked[0] != original_id:
                results.append(
                    {
                        "type": "warning",
                        "message": (
                            f"User {user_label} is no longer a single-location Quest user "
                            f"for {original_name} — skipped."
                        ),
                        **location_meta,
                    }
                )
                continue

            try:
                resolved_role_id, resolution = resolve_or_duplicate_destination_role(
                    current_user.get("role") or user.get("role"),
                    destination_account_id,
                    dest_by_id,
                    dest_by_name,
                    source_by_id,
                    fallback_role_id=role_group_id,
                    created_by_source_role_id=created_cache,
                )
            except AccountMoveGuardrailError as error:
                results.append(
                    {
                        "type": "user",
                        "id": user_id,
                        "name": user_label,
                        "action": (
                            f"Could not resolve destination role for {user_label}: {error}"
                        ),
                        "status": None,
                        "ok": False,
                        **location_meta,
                    }
                )
                continue

            user_payload = {
                "account": destination_account_id,
                "locations": [destination_id],
                "role": resolved_role_id,
            }
            user_response, user_patch_status = patch_user(
                user_id,
                user_payload,
                current_user.get("_etag"),
            )
            results.append(
                {
                    "type": "user",
                    "id": user_id,
                    "name": user_label,
                    "action": (
                        f"Moved user {user_label} to destination account / "
                        f"{destination_name} with role {resolved_role_id} "
                        f"({resolution})."
                    ),
                    "status": user_patch_status,
                    "ok": 200 <= user_patch_status < 300,
                    "response": user_response,
                    **location_meta,
                }
            )
    else:
        results.append(
            {
                "type": "warning",
                "message": (
                    f"No Quest users (exactly 1 location) linked to {original_name}."
                ),
                **location_meta,
            }
        )

    return results


def run_account_move(
    original_location_ids: list[str],
    original_account_id: str,
    destination_account_id: str,
    role_group_id: str,
    on_progress=None,
) -> list[dict]:
    _require_accounts(original_account_id, destination_account_id)
    # Fallback role is optional — we match/duplicate each Quest user's current role.
    fallback_role = (role_group_id or "").strip() or None
    destination_locations = list_all_locations(destination_account_id)
    original_users = list_all_users(original_account_id)
    destination_roles = list_all_roles(destination_account_id)
    source_roles = list_all_roles(original_account_id)
    destination_roles_by_id = index_roles_by_id(destination_roles)
    destination_roles_by_name = index_roles_by_name(destination_roles)
    source_roles_by_id = index_roles_by_id(source_roles)
    created_roles_by_source_id: dict[str, str] = {}
    results = []
    total = max(len(original_location_ids), 1)
    step = 0

    def _report(message: str, location_index: Optional[int] = None):
        if not on_progress:
            return
        # Tick within the current location's share of the bar.
        if location_index is None:
            on_progress(step / total, message)
        else:
            # Nudge forward slightly within this location's slice as substeps happen.
            base = location_index / total
            span = 1 / total
            on_progress(min(base + span * 0.85, (location_index + 1) / total), message)

    for index, original_location_id in enumerate(original_location_ids):
        _report(f"Loading location {original_location_id}…", index)
        try:
            snapshot = fetch_move_snapshot(
                original_location_id,
                original_account_id,
                destination_account_id,
                destination_locations=destination_locations,
                original_users=original_users,
            )
        except (AccountMoveGuardrailError, RuntimeError) as error:
            results.append(
                {
                    "type": "warning",
                    "message": str(error),
                    "original_location_id": original_location_id,
                    "original_location_name": original_location_id,
                }
            )
            step += 1
            _report(f"Skipped {original_location_id}", index)
            if on_progress:
                on_progress((index + 1) / total, f"Finished {index + 1}/{total}")
            continue

        original_name = snapshot["original_location"].get("name", original_location_id)
        destination = snapshot.get("destination_location")
        location_meta = {
            "original_location_id": original_location_id,
            "original_location_name": original_name,
            "destination_location_id": destination.get("_id") if destination else None,
            "destination_location_name": destination.get("name") if destination else None,
        }

        if snapshot["status"] == "already_moved":
            retained = snapshot.get("retained_channel_links") or []
            if retained and not snapshot.get("channel_links"):
                message = (
                    f"Location {original_name} ({original_location_id}) skipped — "
                    "only Test Channel remains (left in place)."
                )
            else:
                message = (
                    f"Location {original_name} ({original_location_id}) has already been moved "
                    "(no channel links to move)."
                )
            results.append({"type": "warning", "message": message, **location_meta})
            step += 1
            if on_progress:
                on_progress((index + 1) / total, f"Skipped {original_name}")
            continue

        def _location_progress(message: str, _index=index):
            _report(message, _index)

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
                users=snapshot.get("users") or [],
                role_group_id=fallback_role,
                destination_roles_by_id=destination_roles_by_id,
                destination_roles_by_name=destination_roles_by_name,
                source_roles_by_id=source_roles_by_id,
                created_roles_by_source_id=created_roles_by_source_id,
                on_progress=_location_progress,
            )
        )
        step += 1
        if on_progress:
            on_progress((index + 1) / total, f"Done {original_name} ({index + 1}/{total})")

    if on_progress:
        on_progress(1.0, "Finished")
    return results


def run_account_move_revert(
    backup: dict,
    original_account_id: str,
    destination_account_id: str,
    on_progress=None,
) -> list[dict]:
    validate_account_move_backup(backup, original_account_id, destination_account_id)
    results = []
    moves = backup["moves"]
    total = max(len(moves), 1)

    for index, move in enumerate(moves):
        original = move["original_location"]
        destination = move["destination_location"]
        original_id = original["_id"]
        destination_id = destination["_id"]
        channel_links = move["channel_links"]
        original_name = strip_migrated_marker(original.get("name") or original_id)
        destination_name = destination.get("name") or destination_id
        location_meta = {
            "original_location_id": original_id,
            "original_location_name": original_name,
            "destination_location_id": destination_id,
            "destination_location_name": destination_name,
        }

        def _progress(message: str):
            if on_progress:
                on_progress((index + 0.5) / total, message)

        _progress(f"Reverting {original_name}…")

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
                        **location_meta,
                    }
                )
                continue

            _progress(
                f"{original_name}: moving "
                f"{channel_link.get('name') or channel_link_id} back…"
            )
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
                        **location_meta,
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
                        "action": "Moved CL back but failed to refresh before PUT",
                        **location_meta,
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
                        f"to original location {original_name}."
                    ),
                    "status": response_status,
                    "ok": 200 <= response_status < 300,
                    "response": response_data,
                    **location_meta,
                }
            )

        # Restore both locations from the pre-move backup (name + channelLinks).
        current_original, original_status = get_location(original_id)
        if original_status != 200:
            results.append(
                {
                    "type": "location",
                    "id": original_id,
                    "status": original_status,
                    "ok": False,
                    "action": f"Failed to fetch original location {original_id} for revert",
                    **location_meta,
                }
            )
        else:
            validate_location_belongs(
                current_original, original_account_id, "Original location"
            )
            # Prefer backup name, always strip any leftover migration marker.
            restored_original_name = strip_migrated_marker(
                original.get("name") or current_original.get("name") or ""
            )
            _progress(f"{original_name}: restoring original name + channelLinks…")
            original_payload = {
                "name": restored_original_name,
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
                    "name": restored_original_name,
                    "role": "original",
                    "action": (
                        f"Restored original location to `{restored_original_name}` "
                        f"(removed #MIGRATEDTO…# if present) and channelLinks."
                    ),
                    "status": original_patch_status,
                    "ok": 200 <= original_patch_status < 300,
                    "response": original_response,
                    **location_meta,
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
                    **location_meta,
                }
            )
        else:
            validate_location_belongs(
                current_destination, destination_account_id, "Destination location"
            )
            restored_destination_name = strip_migrated_marker(
                destination.get("name") or current_destination.get("name") or ""
            )
            _progress(f"{original_name}: restoring destination channelLinks…")
            destination_payload = {
                "name": restored_destination_name,
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
                    "name": restored_destination_name,
                    "role": "destination",
                    "action": (
                        f"Restored destination location `{restored_destination_name}` "
                        f"(name + channelLinks)."
                    ),
                    "status": destination_patch_status,
                    "ok": 200 <= destination_patch_status < 300,
                    "response": destination_response,
                    **location_meta,
                }
            )

        for user in move.get("users") or []:
            user_id = user["_id"]
            user_label = user.get("name") or user.get("email") or user_id
            _progress(f"{original_name}: restoring user {user_label}…")
            current_user, user_status = get_user(user_id)
            if user_status != 200:
                results.append(
                    {
                        "type": "user",
                        "id": user_id,
                        "name": user_label,
                        "action": f"Failed to fetch user {user_label} for revert",
                        "status": user_status,
                        "ok": False,
                        **location_meta,
                    }
                )
                continue

            user_payload = {
                "account": original_account_id,
                "locations": list(user.get("locations") or [original_id]),
            }
            if "role" in user:
                user_payload["role"] = user.get("role")
            user_response, user_patch_status = patch_user(
                user_id,
                user_payload,
                current_user.get("_etag"),
            )
            results.append(
                {
                    "type": "user",
                    "id": user_id,
                    "name": user_label,
                    "action": (
                        f"Restored user {user_label} to original account / "
                        f"{original_name}."
                    ),
                    "status": user_patch_status,
                    "ok": 200 <= user_patch_status < 300,
                    "response": user_response,
                    **location_meta,
                }
            )

        if on_progress:
            on_progress((index + 1) / total, f"Reverted {original_name} ({index + 1}/{total})")

    if on_progress:
        on_progress(1.0, "Finished")
    return results
