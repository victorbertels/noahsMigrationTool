"""Copy set custom fields from every item onto the destination account.

Items are Deliverect products. An item is matched to the destination account
by PLU, product type, and location name. Account-level items (no location)
match other account-level items. Location names ignore a trailing
``#MIGRATEDTO…#`` marker so a site that was already moved still lines up.

Only values that are actually set are copied. Blank strings, empty objects,
and empty lists are left alone. Destination-only custom field keys are kept;
when both sides set the same key, the source value is written.

Checked attributes: ``customFields``, ``metadata``, and ``metaData``.

Run:

    python copy_custom_fields.py --source-account ACCOUNT --destination-account ACCOUNT --dry-run
    python copy_custom_fields.py --source-account ACCOUNT --destination-account ACCOUNT
"""

from __future__ import annotations

import argparse
import copy
import sys
from typing import Optional

from account_migration import get_match_name
from api import (
    get_location,
    get_product,
    list_all_locations,
    list_all_products,
    patch_product,
)

CUSTOM_FIELD_ATTRIBUTES = ("customFields", "metadata", "metaData")
_KEYED_FIELD_NAMES = ("key", "field", "name")


class CustomFieldCopyError(Exception):
    """Raised when a custom-field copy cannot run safely."""


def _is_blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _keyed_field_name(item: dict) -> Optional[str]:
    for field_name in _KEYED_FIELD_NAMES:
        if field_name in item and not _is_blank(item.get(field_name)):
            return field_name
    return None


def normalize_custom_value(value):
    """Return the set portion of a custom-field value, or None when nothing is set."""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    if isinstance(value, dict):
        normalized = {}
        for key, item in value.items():
            item_norm = normalize_custom_value(item)
            if item_norm is None or item_norm == {} or item_norm == []:
                continue
            normalized[key] = item_norm
        return normalized or None
    if isinstance(value, list):
        normalized = []
        for item in value:
            if isinstance(item, dict) and _keyed_field_name(item):
                field_name = _keyed_field_name(item)
                value_norm = normalize_custom_value(item.get("value"))
                if value_norm is None or value_norm == {} or value_norm == []:
                    continue
                copied = dict(item)
                copied["value"] = value_norm
                normalized.append(copied)
                continue
            item_norm = normalize_custom_value(item)
            if item_norm is None or item_norm == {} or item_norm == []:
                continue
            normalized.append(item_norm)
        return normalized or None
    return value


def extract_set_custom_fields(product: dict) -> dict:
    """Attributes on this item that have at least one custom field set."""
    found = {}
    for attribute in CUSTOM_FIELD_ATTRIBUTES:
        if attribute not in product:
            continue
        normalized = normalize_custom_value(product.get(attribute))
        if normalized is None:
            continue
        found[attribute] = normalized
    return found


def _merge_keyed_list(current: list, incoming: list) -> list:
    incoming_keys = []
    incoming_by_key = {}
    for item in incoming:
        field_name = _keyed_field_name(item)
        field_value = item.get(field_name) if field_name else None
        incoming_keys.append(field_value)
        incoming_by_key[field_value] = item

    merged = [copy.deepcopy(incoming_by_key[key]) for key in incoming_keys]
    seen = set(incoming_keys)
    for item in current:
        if not isinstance(item, dict):
            merged.append(copy.deepcopy(item))
            continue
        field_name = _keyed_field_name(item)
        if not field_name:
            merged.append(copy.deepcopy(item))
            continue
        field_value = item.get(field_name)
        if field_value not in seen:
            merged.append(copy.deepcopy(item))
            seen.add(field_value)
    return merged


def merge_custom_field_value(current, incoming):
    """Overlay set source values onto the destination value."""
    incoming_norm = normalize_custom_value(incoming)
    if incoming_norm is None:
        return copy.deepcopy(current) if current is not None else None

    if isinstance(incoming_norm, dict):
        base = current if isinstance(current, dict) else {}
        merged = {key: copy.deepcopy(value) for key, value in base.items()}
        for key, value in incoming_norm.items():
            if key in merged and isinstance(merged[key], (dict, list)) and isinstance(value, (dict, list)):
                merged[key] = merge_custom_field_value(merged[key], value)
            else:
                merged[key] = copy.deepcopy(value)
        return merged

    if isinstance(incoming_norm, list):
        current_list = current if isinstance(current, list) else []
        if incoming_norm and all(
            isinstance(item, dict) and _keyed_field_name(item) for item in incoming_norm
        ):
            return _merge_keyed_list(current_list, incoming_norm)
        return copy.deepcopy(incoming_norm)

    return copy.deepcopy(incoming_norm)


def build_custom_field_patch(destination: dict, source_fields: dict) -> dict:
    """PATCH body that copies set source custom fields onto one destination item."""
    payload = {}
    for attribute, incoming in source_fields.items():
        current = destination.get(attribute)
        merged = merge_custom_field_value(current, incoming)
        if current != merged:
            payload[attribute] = merged
    return payload


def describe_custom_fields(fields: dict) -> str:
    parts = []
    custom = fields.get("customFields")
    if isinstance(custom, dict):
        keys = ", ".join(str(key) for key in custom.keys())
        parts.append(f"customFields ({keys})" if keys else "customFields")
    elif isinstance(custom, list):
        parts.append(f"customFields ({len(custom)})")
    elif custom is not None:
        parts.append("customFields")

    for attribute in ("metadata", "metaData"):
        value = fields.get(attribute)
        if value is None:
            continue
        if isinstance(value, list):
            names = []
            for item in value:
                if isinstance(item, dict):
                    label = item.get("key") or item.get("field") or item.get("name")
                    if label:
                        names.append(str(label))
            if names:
                parts.append(f"{attribute} ({', '.join(names)})")
            else:
                parts.append(f"{attribute} ({len(value)})")
        else:
            parts.append(attribute)
    return "; ".join(parts) or "custom fields"


def location_scope_names(locations: list[dict]) -> dict[str, str]:
    """Map location id → match name (migration marker removed)."""
    names = {}
    for location in locations:
        location_id = location.get("_id")
        if not location_id:
            continue
        names[str(location_id)] = get_match_name(location)
    return names


def _scope_for_product(product: dict, location_names: dict[str, str]) -> tuple[str, Optional[str]]:
    """Return (scope name, error). An empty scope name means an account-level item."""
    location_id = product.get("location")
    if not location_id:
        return "", None
    location_id = str(location_id)
    if location_id not in location_names:
        return "", f"location {location_id} was not found"
    name = (location_names[location_id] or "").strip()
    if not name:
        return "", f"location {location_id} has no name to match on"
    return name, None


def _match_key(plu: str, product_type, scope: str) -> tuple:
    return (plu, product_type, scope)


def _belongs_to_account(product: dict, account_id: Optional[str]) -> bool:
    if not account_id:
        return True
    owner = product.get("account")
    return owner is None or owner == account_id


def build_copy_plan(
    source_products: list[dict],
    destination_products: list[dict],
    source_location_names: dict[str, str],
    destination_location_names: dict[str, str],
    source_account_id: Optional[str] = None,
    destination_account_id: Optional[str] = None,
) -> dict:
    """Plan which set custom fields should be copied. Does not call the API."""
    destination_index: dict[tuple, list[dict]] = {}
    destination_count = 0
    for product in destination_products:
        if product.get("_deleted") or not _belongs_to_account(product, destination_account_id):
            continue
        destination_count += 1
        plu = (product.get("plu") or "").strip()
        if not plu:
            continue
        scope, error = _scope_for_product(product, destination_location_names)
        if error:
            continue
        key = _match_key(plu, product.get("productType"), scope)
        destination_index.setdefault(key, []).append(product)

    rows = []
    source_count = 0
    for index, product in enumerate(source_products):
        if product.get("_deleted") or not _belongs_to_account(product, source_account_id):
            continue
        source_count += 1
        fields = extract_set_custom_fields(product)
        if not fields:
            continue

        plu = (product.get("plu") or "").strip()
        name = product.get("name") or plu or product.get("_id") or f"item-{index}"
        product_type = product.get("productType")
        source_id = product.get("_id") or f"index:{index}"
        base = {
            "source_id": source_id,
            "name": name,
            "plu": plu,
            "product_type": product_type,
            "custom_fields": fields,
            "fields_label": describe_custom_fields(fields),
        }

        if not plu:
            rows.append(
                {
                    **base,
                    "status": "skipped",
                    "scope": "",
                    "destination_id": None,
                    "destination_name": None,
                    "patch": {},
                    "detail": "Item has custom fields but no PLU, so it cannot be matched.",
                }
            )
            continue

        scope, error = _scope_for_product(product, source_location_names)
        scope_label = scope or "Account"
        if error:
            rows.append(
                {
                    **base,
                    "status": "unmatched",
                    "scope": "",
                    "destination_id": None,
                    "destination_name": None,
                    "patch": {},
                    "detail": f"Cannot match item: {error}.",
                }
            )
            continue

        matches = destination_index.get(_match_key(plu, product_type, scope), [])
        if not matches:
            rows.append(
                {
                    **base,
                    "status": "unmatched",
                    "scope": scope_label,
                    "destination_id": None,
                    "destination_name": None,
                    "patch": {},
                    "detail": (
                        f"No destination item with PLU {plu}, "
                        f"product type {product_type!r}, scope {scope_label}."
                    ),
                }
            )
            continue

        for destination in matches:
            patch = build_custom_field_patch(destination, fields)
            status = "ready" if patch else "unchanged"
            destination_name = destination.get("name") or destination.get("_id")
            if patch:
                detail = f"Copy {base['fields_label']} onto {destination_name}."
            else:
                detail = "Destination already has these custom fields."
            rows.append(
                {
                    **base,
                    "status": status,
                    "scope": scope_label,
                    "destination_id": destination.get("_id"),
                    "destination_name": destination_name,
                    "patch": patch,
                    "detail": detail,
                }
            )

    return {
        "source_item_count": source_count,
        "destination_item_count": destination_count,
        "items_with_custom_fields": len({row["source_id"] for row in rows}),
        "ready": sum(1 for row in rows if row["status"] == "ready"),
        "unchanged": sum(1 for row in rows if row["status"] == "unchanged"),
        "unmatched": sum(1 for row in rows if row["status"] == "unmatched"),
        "skipped": sum(1 for row in rows if row["status"] == "skipped"),
        "rows": rows,
    }


def _require_accounts(source_account_id: str, destination_account_id: str):
    if not source_account_id or not source_account_id.strip():
        raise CustomFieldCopyError("Source account ID is required.")
    if not destination_account_id or not destination_account_id.strip():
        raise CustomFieldCopyError("Destination account ID is required.")
    if source_account_id.strip() == destination_account_id.strip():
        raise CustomFieldCopyError("Source and destination account IDs must be different.")


def _fill_missing_locations(products: list[dict], names: dict[str, str]):
    missing = []
    for product in products:
        location_id = product.get("location")
        if not location_id:
            continue
        location_id = str(location_id)
        if location_id not in names and location_id not in missing:
            missing.append(location_id)
    for location_id in missing:
        location, status = get_location(location_id)
        if status == 200 and isinstance(location, dict) and location.get("_id"):
            names[str(location["_id"])] = get_match_name(location)


def scan_items_for_custom_fields(
    source_account_id: str,
    destination_account_id: str,
    on_progress=None,
) -> dict:
    """Load both accounts and plan custom-field copies. Does not write."""
    source_account_id = (source_account_id or "").strip()
    destination_account_id = (destination_account_id or "").strip()
    _require_accounts(source_account_id, destination_account_id)

    def progress(fraction: float, message: str):
        if on_progress:
            on_progress(fraction, message)

    progress(0.05, "Loading source items…")
    source_products = list_all_products(source_account_id)
    progress(0.35, "Loading destination items…")
    destination_products = list_all_products(destination_account_id)
    progress(0.6, "Loading locations…")
    source_names = location_scope_names(list_all_locations(source_account_id))
    destination_names = location_scope_names(list_all_locations(destination_account_id))
    progress(0.8, "Resolving item locations…")
    _fill_missing_locations(source_products, source_names)
    _fill_missing_locations(destination_products, destination_names)
    progress(0.9, "Matching items with custom fields…")
    plan = build_copy_plan(
        source_products,
        destination_products,
        source_names,
        destination_names,
        source_account_id=source_account_id,
        destination_account_id=destination_account_id,
    )
    plan["source_account_id"] = source_account_id
    plan["destination_account_id"] = destination_account_id
    progress(1.0, "Scan complete")
    return plan


def _result_row(
    row: dict,
    *,
    ok: bool,
    status,
    action: str,
    dry_run: bool,
    response=None,
) -> dict:
    result = {
        "type": "product",
        "id": row.get("destination_id"),
        "name": row.get("destination_name") or row.get("name"),
        "plu": row.get("plu"),
        "source_id": row.get("source_id"),
        "scope": row.get("scope"),
        "fields_label": row.get("fields_label"),
        "ok": ok,
        "status": status,
        "action": action,
        "dry_run": dry_run,
    }
    if response is not None:
        result["response"] = response
    return result


def apply_custom_field_copies(
    rows: list[dict],
    destination_account_id: str,
    dry_run: bool = False,
    on_progress=None,
) -> list[dict]:
    """Copy planned custom fields onto destination items."""
    destination_account_id = (destination_account_id or "").strip()
    if not destination_account_id:
        raise CustomFieldCopyError("Destination account ID is required.")

    ready = [
        row for row in rows if row.get("status") == "ready" and row.get("destination_id")
    ]
    results = []
    total = max(len(ready), 1)

    for index, row in enumerate(ready):
        destination_id = row["destination_id"]
        label = row.get("destination_name") or destination_id
        plu = row.get("plu") or label
        fields = row.get("custom_fields") or {}
        fields_label = row.get("fields_label") or describe_custom_fields(fields)
        if on_progress:
            verb = "Would copy" if dry_run else "Copying"
            on_progress(index / total, f"{verb} {plu}…")

        if dry_run:
            results.append(
                _result_row(
                    row,
                    ok=True,
                    status=200,
                    action=f"[DRY RUN] Would copy {fields_label} onto {label}.",
                    dry_run=True,
                )
            )
            continue

        current, status = get_product(destination_id)
        if status != 200 or not isinstance(current, dict):
            results.append(
                _result_row(
                    row,
                    ok=False,
                    status=status,
                    action=f"Failed to load destination item {label} (HTTP {status}).",
                    dry_run=False,
                    response=current,
                )
            )
            continue

        if current.get("account") != destination_account_id:
            results.append(
                _result_row(
                    row,
                    ok=False,
                    status=status,
                    action=(
                        f"Destination item {label} belongs to account "
                        f"{current.get('account')}, expected {destination_account_id}."
                    ),
                    dry_run=False,
                )
            )
            continue

        patch = build_custom_field_patch(current, fields)
        if not patch:
            results.append(
                _result_row(
                    row,
                    ok=True,
                    status=200,
                    action=f"{label} already has these custom fields.",
                    dry_run=False,
                )
            )
            continue

        response, patch_status = patch_product(destination_id, patch, current.get("_etag"))
        if patch_status == 412:
            refreshed, refreshed_status = get_product(destination_id)
            if (
                refreshed_status == 200
                and isinstance(refreshed, dict)
                and refreshed.get("account") == destination_account_id
            ):
                patch = build_custom_field_patch(refreshed, fields)
                if not patch:
                    results.append(
                        _result_row(
                            row,
                            ok=True,
                            status=200,
                            action=f"{label} already has these custom fields.",
                            dry_run=False,
                        )
                    )
                    continue
                response, patch_status = patch_product(
                    destination_id,
                    patch,
                    refreshed.get("_etag"),
                )

        ok = 200 <= patch_status < 300
        results.append(
            _result_row(
                row,
                ok=ok,
                status=patch_status,
                action=(
                    f"Copied {fields_label} onto {label}."
                    if ok
                    else f"Failed to copy custom fields onto {label} (HTTP {patch_status})."
                ),
                dry_run=False,
                response=response,
            )
        )

    if on_progress:
        on_progress(1.0, "Finished")
    return results


def _print_plan(plan: dict):
    print(
        f"Scanned {plan['source_item_count']} source item(s) and "
        f"{plan['destination_item_count']} destination item(s)."
    )
    print(
        f"{plan['items_with_custom_fields']} item(s) have custom fields set: "
        f"{plan['ready']} to copy, {plan['unchanged']} already match, "
        f"{plan['unmatched']} unmatched, {plan['skipped']} skipped."
    )
    for row in plan["rows"]:
        scope = row.get("scope") or "—"
        destination = row.get("destination_name") or "—"
        print(
            f"[{row['status']}] {row.get('plu') or '—'} {row.get('name')} "
            f"(scope {scope} → {destination}) {row.get('detail')}"
        )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Copy custom fields that are set on source-account items "
            "onto the matching items in the destination account."
        )
    )
    parser.add_argument("--source-account", required=True, help="Account to read items from.")
    parser.add_argument(
        "--destination-account",
        required=True,
        help="Account to write custom fields onto.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be copied without updating the destination account.",
    )
    args = parser.parse_args(argv)

    def progress(fraction: float, message: str):
        print(f"[{fraction:.0%}] {message}", flush=True)

    try:
        plan = scan_items_for_custom_fields(
            args.source_account,
            args.destination_account,
            on_progress=progress,
        )
    except CustomFieldCopyError as error:
        print(error, file=sys.stderr)
        return 2
    except Exception as error:
        print(error, file=sys.stderr)
        return 1

    _print_plan(plan)
    if plan["ready"] == 0:
        print("No custom fields to copy.")
        return 0

    try:
        results = apply_custom_field_copies(
            plan["rows"],
            plan["destination_account_id"],
            dry_run=args.dry_run,
            on_progress=progress,
        )
    except CustomFieldCopyError as error:
        print(error, file=sys.stderr)
        return 2
    except Exception as error:
        print(error, file=sys.stderr)
        return 1

    failures = [result for result in results if not result.get("ok")]
    copied = len(results) - len(failures)
    prefix = "Would copy" if args.dry_run else "Copied"
    print(f"{prefix} {copied} item(s); {len(failures)} failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
