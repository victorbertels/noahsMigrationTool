import os

import streamlit as st

from auth import set_credentials
from migration import (
    AccountGuardrailError,
    create_backup_zip,
    load_backup_zip,
    run_migration,
    run_revert,
)


def get_config_value(key: str) -> str:
    value = os.getenv(key, "")
    try:
        return st.secrets[key]
    except Exception:
        return value


def configure_settings():
    client_id = get_config_value("CLIENT_ID")
    client_secret = get_config_value("CLIENT_SECRET")
    allowed_account_id = get_config_value("ALLOWED_ACCOUNT_ID")

    with st.sidebar:
        st.header("Settings")
        client_id = st.text_input("Client ID", value=client_id)
        client_secret = st.text_input("Client secret", value=client_secret, type="password")
        allowed_account_id = st.text_input(
            "Allowed account ID",
            value=allowed_account_id,
            help="Migration and revert only run for this Deliverect account.",
        )

    if not client_id or not client_secret:
        st.warning("Enter your Deliverect API credentials in the sidebar.")
        st.stop()

    if not allowed_account_id:
        st.warning("Enter the allowed account ID in the sidebar.")
        st.stop()

    set_credentials(client_id, client_secret)
    return allowed_account_id.strip()


def show_results(results: list[dict]):
    for result in results:
        if result.get("type") == "warning":
            st.warning(result["message"])
            continue

        label = f"{result['type']} {result.get('name') or result.get('id')}"
        if result.get("ok"):
            st.success(f"{label}: HTTP {result['status']}")
        else:
            st.error(f"{label}: HTTP {result['status']}")
            if result.get("response"):
                st.json(result["response"])


st.set_page_config(page_title="Noah's Quest Migration", layout="wide")
st.title("Noah's Quest Migration")
st.caption("Migrate Deliverect locations to Quest, with a downloadable backup and full revert.")

allowed_account_id = configure_settings()

migrate_tab, revert_tab = st.tabs(["Migrate", "Revert"])

with migrate_tab:
    location_id = st.text_input("Location ID", placeholder="6a2ad9de3547b47db45c7b3b")

    if "backup_bytes" not in st.session_state:
        st.session_state.backup_bytes = None
        st.session_state.backup_filename = None
        st.session_state.backup_location_id = None
        st.session_state.backup_account_id = None

    if st.button("Create backup", disabled=not location_id):
        try:
            backup_bytes, backup_filename = create_backup_zip(location_id, allowed_account_id)
            st.session_state.backup_bytes = backup_bytes
            st.session_state.backup_filename = backup_filename
            st.session_state.backup_location_id = location_id
            st.session_state.backup_account_id = allowed_account_id
            st.success("Backup created. Download it before running the migration.")
        except AccountGuardrailError as error:
            st.error(str(error))
        except Exception as error:
            st.error(str(error))

    if st.session_state.backup_bytes:
        st.download_button(
            label="Download backup zip",
            data=st.session_state.backup_bytes,
            file_name=st.session_state.backup_filename,
            mime="application/zip",
        )

    backup_confirmed = st.checkbox(
        "I have downloaded the backup zip and want to continue",
        disabled=not st.session_state.backup_bytes,
    )

    backup_matches = (
        st.session_state.backup_location_id == location_id
        and st.session_state.backup_account_id == allowed_account_id
    )

    if st.button(
        "Run migration",
        type="primary",
        disabled=not backup_confirmed or not backup_matches,
    ):
        try:
            with st.spinner("Running migration..."):
                results = run_migration(location_id, allowed_account_id)
            show_results(results)
        except AccountGuardrailError as error:
            st.error(str(error))
        except Exception as error:
            st.error(str(error))

with revert_tab:
    st.write("Upload a backup zip to restore the location and all channel links with PUT.")
    uploaded_backup = st.file_uploader("Backup zip", type=["zip"])

    if uploaded_backup and st.button("Restore from backup", type="primary"):
        try:
            backup = load_backup_zip(uploaded_backup.getvalue())
            st.info(
                f"Restoring location {backup['manifest']['location_id']} "
                f"from {backup['manifest']['created_at']}"
            )
            with st.spinner("Restoring..."):
                results = run_revert(backup, allowed_account_id)
            show_results(results)
        except AccountGuardrailError as error:
            st.error(str(error))
        except Exception as error:
            st.error(str(error))
