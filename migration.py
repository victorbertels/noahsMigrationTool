import io
import json
import re
import zipfile
from datetime import datetime, timezone

from deliverect_api import (
    get_channel_link,
    get_location,
    patch_channel_link,
    patch_location,
    prepare_put_payload,
    put_channel_link,
    put_location,
)

WOLT_NAMES = ["Wolt Storefront - Q8", "Wolt"]
WOLT_CHANNELS = [16, 6016]


def _wolt_migration_action(name: str, original_tags: list) -> str:
    if name == "Wolt Storefront - Q8":
        intro = f"Found Wolt Storefront ({name}) → converting to Wolt retail channel (6016)"
    else:
        intro = f"Found Wolt ({name}) → converting to Wolt retail channel (6016)"

    steps = [intro]
    if "Quest" not in original_tags:
        steps.append("adding Quest tag")
    else:
        steps.append("keeping Quest tag")
    steps.extend(
        [
            "enabling sendToQuest",
            "disabling DMA",
            "enabling autoAcceptRetailOrder",
        ]
    )
    return ", ".join(steps) + "."


def _food_channel_migration_action(name: str) -> str:
    return (
        f"Found {name} → updating food channel to route orders to Quest "
        "(sendToQuest on, insertPosOrderAfterDmaAccept off, DMA off)."
    )


def _location_migration_action(location: dict, original_tags: list) -> str:
    location_name = location.get("name", "location")
    changes = []
    if "Quest Migrated" not in original_tags:
        changes.append("adding 'Quest Migrated'")
    if "Not migrated" in original_tags:
        changes.append("removing 'Not migrated'")
    if not changes:
        changes.append("tags already up to date")
    return f"Updating location {location_name} → {', '.join(changes)}."


class AccountGuardrailError(Exception):
    """Raised when a resource is outside the allowed Deliverect account."""


def _require_allowed_account_id(allowed_account_id: str):
    if not allowed_account_id or not allowed_account_id.strip():
        raise AccountGuardrailError("Allowed account ID is required before any changes.")


def validate_location_account(location: dict, allowed_account_id: str):
    _require_allowed_account_id(allowed_account_id)
    location_account = location.get("account")
    if location_account != allowed_account_id:
        raise AccountGuardrailError(
            f"Location {location.get('_id')}does not belong to {allowed_account_id}."
        )


def validate_channel_link_account(channel_link: dict, allowed_account_id: str, location_id: str):
    _require_allowed_account_id(allowed_account_id)
    channel_link_id = channel_link.get("_id")
    channel_link_account = channel_link.get("account")
    if channel_link_account != allowed_account_id:
        raise AccountGuardrailError(
            f"Channel link {channel_link_id} belongs to account {channel_link_account}, "
            f"but only account {allowed_account_id} is allowed."
        )
    if channel_link.get("location") != location_id:
        raise AccountGuardrailError(
            f"Channel link {channel_link_id} belongs to location {channel_link.get('location')}, "
            f"not location {location_id}."
        )


def _sanitize_filename_part(value: str) -> str:
    sanitized = re.sub(r"[^\w\-]+", "_", value.strip())
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    return sanitized[:80] or "location"


def fetch_location_snapshot(location_id: str, allowed_account_id: str) -> dict:
    location, status = get_location(location_id)
    if status != 200:
        raise RuntimeError(f"Failed to fetch location {location_id}: HTTP {status}")

    validate_location_account(location, allowed_account_id)

    channel_links = []
    for channel_link_id in location.get("channelLinks", []):
        channel_link, channel_status = get_channel_link(channel_link_id)
        if channel_status != 200:
            raise RuntimeError(
                f"Failed to fetch channel link {channel_link_id}: HTTP {channel_status}"
            )
        validate_channel_link_account(channel_link, allowed_account_id, location_id)
        channel_links.append(channel_link)

    return {
        "location_id": location_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "location": location,
        "channel_links": channel_links,
    }


def create_backup_zip(location_id: str, allowed_account_id: str) -> tuple[bytes, str]:
    snapshot = fetch_location_snapshot(location_id, allowed_account_id)
    location_name = _sanitize_filename_part(snapshot["location"].get("name", "location"))
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"backup_{location_name}_{location_id}_{timestamp}.zip"

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        manifest = {
            "location_id": location_id,
            "location_name": snapshot["location"].get("name"),
            "account_id": allowed_account_id,
            "created_at": snapshot["created_at"],
            "channel_link_ids": [item["_id"] for item in snapshot["channel_links"]],
        }
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))
        archive.writestr("location.json", json.dumps(snapshot["location"], indent=2))
        for channel_link in snapshot["channel_links"]:
            archive.writestr(
                f"channelLinks/{channel_link['_id']}.json",
                json.dumps(channel_link, indent=2),
            )

    return buffer.getvalue(), filename


def load_backup_zip(zip_bytes: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        location = json.loads(archive.read("location.json"))
        channel_links = []
        for channel_link_id in manifest["channel_link_ids"]:
            channel_links.append(
                json.loads(archive.read(f"channelLinks/{channel_link_id}.json"))
            )

    return {
        "manifest": manifest,
        "location": location,
        "channel_links": channel_links,
    }


def run_migration(location_id: str, allowed_account_id: str) -> list[dict]:
    location, status = get_location(location_id)
    if status != 200:
        raise RuntimeError(f"Failed to fetch location {location_id}: HTTP {status}")

    validate_location_account(location, allowed_account_id)

    results = []
    channel_link_ids = location.get("channelLinks", [])
    if not channel_link_ids:
        results.append(
            {
                "type": "warning",
                "message": f"No channel links found for location {location_id}",
            }
        )

    for channel_link_id in channel_link_ids:
        channel_link, channel_status = get_channel_link(channel_link_id)
        if channel_status != 200:
            results.append(
                {
                    "type": "channel_link",
                    "id": channel_link_id,
                    "status": channel_status,
                    "ok": False,
                }
            )
            continue

        validate_channel_link_account(channel_link, allowed_account_id, location_id)

        name = channel_link.get("name")
        channel = channel_link.get("channel")
        tags = channel_link.get("tags", []).copy()
        etag = channel_link.get("_etag")

        original_tags = tags.copy()

        if name in WOLT_NAMES and channel in WOLT_CHANNELS:
            action = _wolt_migration_action(name, original_tags)
            if "Quest" not in tags:
                tags.append("Quest")
            payload = {
                "channel": 6016,
                "tags": tags,
                "channelSettings": {
                    "autoAcceptOrderStatus": 0,
                    "sendToQuest": True,
                    "insertPosOrderAfterDmaAccept": False,
                },
                "posSettings": {
                    "simphony_gen2": {
                        "autoAcceptRetailOrder": True,
                        "enabledDMA": False,
                    }
                },
            }
        else:
            action = _food_channel_migration_action(name)
            payload = {
                "channelSettings": {
                    "sendToQuest": True,
                    "insertPosOrderAfterDmaAccept": False,
                },
                "posSettings": {"simphony_gen2": {"enabledDMA": False}},
                "enabledDMA": False,
            }

        response_data, response_status = patch_channel_link(channel_link_id, payload, etag)
        results.append(
            {
                "type": "channel_link",
                "id": channel_link_id,
                "name": name,
                "action": action,
                "status": response_status,
                "ok": 200 <= response_status < 300,
                "response": response_data,
            }
        )

    original_location_tags = location.get("tags", []).copy()
    location_tags = original_location_tags.copy()
    if "Quest Migrated" not in location_tags:
        location_tags.append("Quest Migrated")
    if "Not migrated" in location_tags:
        location_tags.remove("Not migrated")

    location_payload = {"tags": location_tags}
    location_response, location_status = patch_location(
        location_id,
        location_payload,
        location.get("_etag"),
    )
    results.append(
        {
            "type": "location",
            "id": location_id,
            "name": location.get("name"),
            "action": _location_migration_action(location, original_location_tags),
            "status": location_status,
            "ok": 200 <= location_status < 300,
            "response": location_response,
        }
    )

    return results


def validate_backup_account(backup: dict, allowed_account_id: str):
    _require_allowed_account_id(allowed_account_id)

    manifest_account = backup["manifest"].get("account_id")
    if manifest_account and manifest_account != allowed_account_id:
        raise AccountGuardrailError(
            f"Backup was created for account {manifest_account}, "
            f"but only account {allowed_account_id} is allowed."
        )

    validate_location_account(backup["location"], allowed_account_id)
    location_id = backup["location"]["_id"]
    for channel_link in backup["channel_links"]:
        validate_channel_link_account(channel_link, allowed_account_id, location_id)


def run_revert(backup: dict, allowed_account_id: str) -> list[dict]:
    validate_backup_account(backup, allowed_account_id)

    results = []
    location_id = backup["location"]["_id"]

    for channel_link in backup["channel_links"]:
        channel_link_id = channel_link["_id"]
        current, current_status = get_channel_link(channel_link_id)
        if current_status != 200:
            results.append(
                {
                    "type": "channel_link",
                    "id": channel_link_id,
                    "status": current_status,
                    "ok": False,
                }
            )
            continue

        validate_channel_link_account(current, allowed_account_id, location_id)

        payload = prepare_put_payload(channel_link)
        response_data, response_status = put_channel_link(
            channel_link_id,
            payload,
            current.get("_etag"),
        )
        results.append(
            {
                "type": "channel_link",
                "id": channel_link_id,
                "name": channel_link.get("name"),
                "status": response_status,
                "ok": 200 <= response_status < 300,
                "response": response_data,
            }
        )

    current_location, current_status = get_location(location_id)
    if current_status != 200:
        results.append(
            {
                "type": "location",
                "id": location_id,
                "status": current_status,
                "ok": False,
            }
        )
        return results

    validate_location_account(current_location, allowed_account_id)

    location_payload = prepare_put_payload(backup["location"])
    location_response, location_status = put_location(
        location_id,
        location_payload,
        current_location.get("_etag"),
    )
    results.append(
        {
            "type": "location",
            "id": location_id,
            "status": location_status,
            "ok": 200 <= location_status < 300,
            "response": location_response,
        }
    )

    return results
