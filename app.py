import streamlit as st

from analytics import track_event, track_page
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
    apply_styles,
    format_box,
    init_migrate_session_state,
    load_credentials,
    location_card,
    render_header,
    render_nav,
    reset_from_location_change,
    show_results,
    step_heading,
)


def migrate_page(allowed_account_id: str):
    with st.container(border=True):
        step_heading("Confirm location", "1")
        location_id_input = st.text_input(
            "Location ID",
            value=st.session_state.location_id_input,
            placeholder="6a2ad9de3547b47db45c7b3b",
        )

        if location_id_input != st.session_state.location_id_input:
            st.session_state.location_id_input = location_id_input
            reset_from_location_change()

        if st.button("Look up location", disabled=not location_id_input, use_container_width=True):
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
                    track_event("location_lookup", action="migrate")
            except AccountGuardrailError as error:
                st.error(str(error))
            except Exception as error:
                st.error(str(error))

        if st.session_state.location_id and st.session_state.location_name:
            location_card(st.session_state.location_name, st.session_state.location_id)

            if not st.session_state.location_confirmed:
                confirm_col, cancel_col = st.columns(2)
                with confirm_col:
                    if st.button("Yes, this is the right location", type="primary", use_container_width=True):
                        st.session_state.location_confirmed = True
                        track_event("location_confirmed", action="migrate")
                        st.rerun()
                with cancel_col:
                    if st.button("No, choose another", use_container_width=True):
                        reset_from_location_change()
                        st.session_state.location_id_input = ""
                        st.rerun()
            else:
                st.success("Location confirmed.")

    if st.session_state.location_confirmed:
        with st.container(border=True):
            step_heading("Download backup", "2")
            st.caption("Create and download a zip backup before running the migration.")

            if st.button("Create backup zip", use_container_width=True):
                try:
                    backup_bytes, backup_filename = create_backup_zip(
                        st.session_state.location_id,
                        allowed_account_id,
                    )
                    st.session_state.backup_bytes = backup_bytes
                    st.session_state.backup_filename = backup_filename
                    st.session_state.backup_downloaded = False
                    track_event("backup_created", action="migrate", filename=backup_filename)
                    st.success("Backup ready.")
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
                    use_container_width=True,
                )
                st.session_state.backup_downloaded = st.checkbox(
                    "I have downloaded the backup zip",
                    value=st.session_state.backup_downloaded,
                )

    if st.session_state.location_confirmed and st.session_state.backup_downloaded:
        with st.container(border=True):
            step_heading("Run migration", "3")
            st.caption("Updates Wolt channels to retail, routes food channels to Quest, and tags the location.")

            if st.button("Run migration", type="primary", use_container_width=True):
                try:
                    with st.spinner("Running migration..."):
                        results = run_migration(st.session_state.location_id, allowed_account_id)
                    track_event(
                        "migration_run",
                        action="migrate",
                        success=all(result.get("ok", True) for result in results if result.get("type") != "warning"),
                    )
                    show_results(results)
                except AccountGuardrailError as error:
                    st.error(str(error))
                except Exception as error:
                    st.error(str(error))


def revert_page(allowed_account_id: str):
    with st.container(border=True):
        step_heading("Restore from backup")
        st.caption("Upload a backup zip to revert the location and all channel links.")
        format_box()

    st.markdown("<div style='margin-top: 1rem'></div>", unsafe_allow_html=True)

    with st.container(border=True):
        uploaded_backup = st.file_uploader(
            "Upload backup zip",
            type=["zip"],
            help="Only .zip files in the backup format above are supported.",
        )

        if uploaded_backup is not None:
            st.caption(f"Selected: `{uploaded_backup.name}`")
            if st.session_state.get("_tracked_upload") != uploaded_backup.name:
                try:
                    backup = load_backup_zip(uploaded_backup.getvalue())
                    st.session_state.revert_location_id = backup["manifest"]["location_id"]
                    st.session_state.revert_location_name = backup["location"].get("name")
                    st.session_state._tracked_upload = uploaded_backup.name
                    track_event("backup_uploaded", action="revert")
                except Exception:
                    pass

        if st.button(
            "Restore from backup",
            type="primary",
            disabled=uploaded_backup is None,
            use_container_width=True,
        ):
            try:
                backup = load_backup_zip(uploaded_backup.getvalue())
                st.info(
                    f"Restoring **{backup['location'].get('name', 'location')}** "
                    f"(`{backup['manifest']['location_id']}`) "
                    f"from {backup['manifest']['created_at']}"
                )
                with st.spinner("Restoring..."):
                    results = run_revert(backup, allowed_account_id)
                st.session_state.revert_location_id = backup["manifest"]["location_id"]
                st.session_state.revert_location_name = backup["location"].get("name")
                track_event(
                    "revert_run",
                    action="revert",
                    backup_created_at=backup["manifest"]["created_at"],
                    success=all(result.get("ok", True) for result in results if result.get("type") != "warning"),
                )
                show_results(results)
            except AccountGuardrailError as error:
                st.error(str(error))
            except Exception as error:
                st.error(str(error))


st.set_page_config(
    page_title="Noah's Quest Migration",
    layout="centered",
    initial_sidebar_state="collapsed",
)

apply_styles()
render_header()
allowed_account_id = load_credentials()
active_page = render_nav()

if active_page == "migrate":
    init_migrate_session_state()
    track_page("migrate")
    migrate_page(allowed_account_id)
else:
    track_page("revert")
    revert_page(allowed_account_id)
