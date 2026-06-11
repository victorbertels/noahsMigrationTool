from typing import Dict, Optional, Tuple

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
}


def prepare_put_payload(data: Dict) -> Dict:
    """Remove read-only fields before a PUT request."""
    return {key: value for key, value in data.items() if key not in PUT_RESTRICTED_KEYS}


def _request(method: str, path: str, payload: Optional[Dict] = None, etag: Optional[str] = None):
    headers = getHeaders()
    headers["Content-Type"] = "application/json"
    if etag:
        headers["If-Match"] = etag
    else:
        headers.pop("If-Match", None)

    response = requests.request(
        method,
        f"{BASE_URL}/{path}",
        headers=headers,
        json=payload if payload is not None else None,
    )
    return response


def get_location(location_id: str) -> Tuple[Dict, int]:
    response = _request("GET", f"locations/{location_id}")
    return response.json(), response.status_code


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
