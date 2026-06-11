import streamlit as st

from api import get_location
from migration import (
    AccountGuardrailError,
    create_backup_zip,
    load_backup_zip,
    run_migration,
    run_revert,
    validate_location_account,
)
from ui import (
    init_migrate_session_state,
    load_credentials,
    reset_from_location_change,
    show_results,
)

ZIP_FORMAT = """
**Expected format:** a `.zip` file created by this app's backup, containing:

```
manifest.json
location.json
channelLinks/
  {channelLinkId}.json
  ...
```

The zip restores the full location and all channel links from the backup snapshot.
"""


def migrate_page():
    allowed_account_id = load_credentials()
    init_migrate_session_state()

    st.title("Migrate")
    st.caption("Confirm the location, download a backup, then run the Quest migration.")

    st.subheader("1. Confirm location")
    location_id_input = st.text_input(
        "Location ID",
        value=st.session_state.location_id_input,
        placeholder="6a2ad9de3547b47db45c7b3b",
    )

    if location_id_input != st.session_state.location_id_input:
        st.session_state.location_id_input = location_id_input
        reset_from_location_change()

    if st.button("Look up location", disabled=not location_id_input):
        try:
            location, status = get_location(location_id_input)
            if status != 200:
                st.error(f"Could not find location (HTTP {status}).")
            else:
                validate_location_account(location, allowed_account_id)
                st.session_state.location_id = location_id_input
                st.session_state.location_name = location.get("name", "Unknown")
                st.session_state.location_confirmed = False
                st.session_state.backup_bytes = None
                st.session_state.backup_filename = None
                st.session_state.backup_downloaded = False
        except AccountGuardrailError as error:
            st.error(str(error))
        except Exception as error:
            st.error(str(error))

    if st.session_state.location_id and st.session_state.location_name:
        st.info(f"**{st.session_state.location_name}**")
        st.write(f"Location ID: `{st.session_state.location_id}`")

        if not st.session_state.location_confirmed:
            confirm_col, cancel_col = st.columns(2)
            with confirm_col:
                if st.button("Yes, this is the right location", type="primary"):
                    st.session_state.location_confirmed = True
                    st.rerun()
            with cancel_col:
                if st.button("No, choose another location"):
                    reset_from_location_change()
                    st.session_state.location_id_input = ""
                    st.rerun()
        else:
            st.success("Location confirmed.")

    if st.session_state.location_confirmed:
        st.divider()
        st.subheader("2. Download backup")

        if st.button("Create backup zip"):
            try:
                backup_bytes, backup_filename = create_backup_zip(
                    st.session_state.location_id,
                    allowed_account_id,
                )
                st.session_state.backup_bytes = backup_bytes
                st.session_state.backup_filename = backup_filename
                st.session_state.backup_downloaded = False
                st.success("Backup ready. Download it before continuing.")
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
            st.session_state.backup_downloaded = st.checkbox(
                "I have downloaded the backup zip",
                value=st.session_state.backup_downloaded,
            )

    if st.session_state.location_confirmed and st.session_state.backup_downloaded:
        st.divider()
        st.subheader("3. Run migration")

        if st.button("Run migration", type="primary"):
            try:
                with st.spinner("Running migration..."):
                    results = run_migration(st.session_state.location_id, allowed_account_id)
                show_results(results)
            except AccountGuardrailError as error:
                st.error(str(error))
            except Exception as error:
                st.error(str(error))


def revert_page():
    allowed_account_id = load_credentials()

    st.title("Revert")
    st.caption("Restore a location and its channel links from a backup zip.")

    st.markdown(ZIP_FORMAT)

    uploaded_backup = st.file_uploader(
        "Upload backup zip",
        type=["zip"],
        help="Only .zip files in the backup format described above are supported.",
    )

    if uploaded_backup is not None:
        st.caption(f"Selected: `{uploaded_backup.name}`")

    if st.button("Restore from backup", type="primary", disabled=uploaded_backup is None):
        try:
            backup = load_backup_zip(uploaded_backup.getvalue())
            st.info(
                f"Restoring **{backup['location'].get('name', 'location')}** "
                f"(`{backup['manifest']['location_id']}`) "
                f"from {backup['manifest']['created_at']}"
            )
            with st.spinner("Restoring..."):
                results = run_revert(backup, allowed_account_id)
            show_results(results)
        except AccountGuardrailError as error:
            st.error(str(error))
        except Exception as error:
            st.error(str(error))


st.set_page_config(
    page_title="Noah's Quest Migration",
    layout="wide",
    initial_sidebar_state="collapsed",
)

migrate = st.Page(migrate_page, title="Migrate", default=True)
revert = st.Page(revert_page, title="Revert")

pg = st.navigation([migrate, revert])
pg.run()
