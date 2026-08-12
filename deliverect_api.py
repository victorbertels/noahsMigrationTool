import json
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode

import requests

from auth import getHeaders

BASE_URL = "https://api.deliverect.io"

PUT_RESTRICTED_KEYS = {
    "_id",
    "_created",
    "_updated",
    "_etag",
    "_links",
    "_deleted",
    "isCanary",
    "lastProductSync",
    "channelLinksDetails",
}


def prepare_put_payload(data: Dict) -> Dict:
    """Remove read-only fields before a PUT request."""
    return {key: value for key, value in data.items() if key not in PUT_RESTRICTED_KEYS}


def _request(
    method: str,
    path: str,
    payload: Optional[Dict] = None,
    etag: Optional[str] = None,
    params: Optional[Dict] = None,
):
    headers = getHeaders()
    headers["Content-Type"] = "application/json"
    if etag:
        headers["If-Match"] = etag
    else:
        headers.pop("If-Match", None)

    url = f"{BASE_URL}/{path}"
    if params:
        url = f"{url}?{urlencode(params)}"

    response = requests.request(
        method,
        url,
        headers=headers,
        json=payload if payload is not None else None,
    )
    return response


def get_location(location_id: str) -> Tuple[Dict, int]:
    response = _request("GET", f"locations/{location_id}")
    return response.json(), response.status_code


def list_all_locations(account_id: str) -> List[Dict]:
    """Fetch all locations for an account using cursor pagination."""
    locations: List[Dict] = []
    page = 1
    cursor = "new"

    while True:
        params = {
            "where": json.dumps({"account": account_id}),
            "max_results": 500,
            "cursor": cursor,
            "page": page,
        }
        response = _request("GET", "locations", params=params)
        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to list locations for account {account_id}: HTTP {response.status_code}"
            )

        data = response.json()
        items = data.get("_items", data if isinstance(data, list) else [])
        locations.extend(items)

        meta = data.get("_meta", {}) if isinstance(data, dict) else {}
        total = meta.get("total")
        if total is not None and len(locations) >= total:
            break
        if len(items) < 500:
            break

        if page == 1 and meta.get("cursor"):
            cursor = meta["cursor"]
        page += 1

    return locations


def patch_location(location_id: str, payload: Dict, etag: str) -> Tuple[Dict, int]:
    response = _request("PATCH", f"locations/{location_id}", payload=payload, etag=etag)
    return response.json(), response.status_code


def put_location(location_id: str, payload: Dict, etag: str) -> Tuple[Dict, int]:
    response = _request("PUT", f"locations/{location_id}", payload=payload, etag=etag)
    return response.json(), response.status_code


def get_channel_link(channel_link_id: str) -> Tuple[Dict, int]:
    response = _request("GET", f"channelLinks/{channel_link_id}")
    return response.json(), response.status_code


def patch_channel_link(channel_link_id: str, payload: Dict, etag: str) -> Tuple[Dict, int]:
    response = _request("PATCH", f"channelLinks/{channel_link_id}", payload=payload, etag=etag)
    return response.json(), response.status_code


def put_channel_link(channel_link_id: str, payload: Dict, etag: str) -> Tuple[Dict, int]:
    response = _request("PUT", f"channelLinks/{channel_link_id}", payload=payload, etag=etag)
    return response.json(), response.status_code


def list_all_users(account_id: str) -> List[Dict]:
    """Fetch all users for an account using cursor pagination."""
    users: List[Dict] = []
    page = 1
    cursor = "new"

    while True:
        params = {
            "where": json.dumps({"account": account_id}),
            "max_results": 500,
            "cursor": cursor,
            "page": page,
        }
        response = _request("GET", "users", params=params)
        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to list users for account {account_id}: HTTP {response.status_code}"
            )

        data = response.json()
        items = data.get("_items", data if isinstance(data, list) else [])
        users.extend(items)

        meta = data.get("_meta", {}) if isinstance(data, dict) else {}
        total = meta.get("total")
        if total is not None and len(users) >= total:
            break
        if len(items) < 500:
            break

        if page == 1 and meta.get("cursor"):
            cursor = meta["cursor"]
        page += 1

    return users


def get_user(user_id: str) -> Tuple[Dict, int]:
    response = _request("GET", f"users/{user_id}")
    return response.json(), response.status_code


def patch_user(user_id: str, payload: Dict, etag: str) -> Tuple[Dict, int]:
    response = _request("PATCH", f"users/{user_id}", payload=payload, etag=etag)
    return response.json(), response.status_code


def list_all_roles(account_id: str) -> List[Dict]:
    """Fetch all roles for an account using cursor pagination."""
    roles: List[Dict] = []
    page = 1
    cursor = "new"

    while True:
        params = {
            "where": json.dumps({"account": {"$in": [account_id]}}),
            "max_results": 500,
            "cursor": cursor,
            "page": page,
        }
        response = _request("GET", "roles", params=params)
        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to list roles for account {account_id}: HTTP {response.status_code}"
            )

        data = response.json()
        items = data.get("_items", data if isinstance(data, list) else [])
        roles.extend(items)

        meta = data.get("_meta", {}) if isinstance(data, dict) else {}
        total = meta.get("total")
        if total is not None and len(roles) >= total:
            break
        if len(items) < 500:
            break

        if page == 1 and meta.get("cursor"):
            cursor = meta["cursor"]
        page += 1

    return roles
