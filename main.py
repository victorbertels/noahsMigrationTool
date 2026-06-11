import os

from dotenv import load_dotenv

from migration import run_migration

load_dotenv()

locationId = "6a2ad9de3547b47db45c7b3b"
allowedAccountId = os.getenv("ALLOWED_ACCOUNT_ID", "")

if not allowedAccountId:
    raise ValueError("ALLOWED_ACCOUNT_ID must be set in the environment or .env file")

results = run_migration(locationId, allowedAccountId)
for result in results:
    if result.get("type") == "warning":
        print(result["message"])
        continue
    status = "OK" if result.get("ok") else "FAILED"
    message = result.get("action") or f"{result['type']} {result.get('name') or result.get('id')}"
    print(f"[{status}] {message} (HTTP {result['status']})")
