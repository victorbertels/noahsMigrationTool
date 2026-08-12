import streamlit as st

st.set_page_config(
    page_title="Noah's Migration Tools",
    layout="centered",
    initial_sidebar_state="collapsed",
)

from account_migration import (
    AccountMoveGuardrailError,
    classify_account_locations,
    create_account_move_backup_zip,
    ensure_destination_role_from_source,
    fetch_move_snapshot,
    has_migrated_marker,
    load_account_move_backup_zip,
    run_account_move,
    run_account_move_revert,
)
from analytics import track_event, track_page
from api import get_location, list_all_locations, list_all_roles
from migration import (
    AccountGuardrailError,
    create_backup_zip,
    load_backup_zip,
    run_migration,
    run_revert,
    validate_location_account,
)
from app_ui import (
    ACCOUNT_MOVE_WIZARD_STEPS,
    QUEST_MIGRATE_WIZARD_STEPS,
    account_move_current_step,
    account_move_format_box,
    account_move_match_summary,
    apply_styles,
    format_box,
    init_account_move_session_state,
    init_account_revert_session_state,
    init_migrate_session_state,
    load_credentials,
    location_card,
    quest_migrate_current_step,
    render_header,
    render_nav,
    render_password_gate,
    reset_account_move_from_accounts_change,
    reset_account_move_per_location,
    reset_account_move_rest,
    reset_from_location_change,
    set_account_move_step,
    set_quest_migrate_step,
    show_account_move_results,
    show_results,
    step_heading,
    wizard_nav_row,
    wizard_steps,
)


def migrate_page(allowed_account_id: str):
    step = quest_migrate_current_step()
    # Keep the viewed step coherent with completed gates when going forward.
    if step >= 2 and not st.session_state.location_confirmed:
        set_quest_migrate_step(1)
        step = 1
    elif step >= 3 and not st.session_state.backup_downloaded:
        set_quest_migrate_step(2)
        step = 2

    wizard_steps(
        QUEST_MIGRATE_WIZARD_STEPS,
        step,
        note="Only <strong>Run migrate</strong> changes live data. Use Back to revisit earlier steps.",
    )

    if step == 1:
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

            if st.button(
                "Look up location",
                disabled=not location_id_input,
                use_container_width=True,
            ):
                track_event(
                    "location_lookup_started",
                    action="migrate",
                    location_id=location_id_input,
                )
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
                location_card(st.session_state.location_name, st.session_state.location_id)

                if not st.session_state.location_confirmed:
                    confirm_col, cancel_col = st.columns(2)
                    with confirm_col:
                        if st.button(
                            "Yes, this is the right location",
                            type="primary",
                            use_container_width=True,
                        ):
                            st.session_state.location_confirmed = True
                            set_quest_migrate_step(2)
                            track_event("location_confirmed", action="migrate")
                            st.rerun()
                    with cancel_col:
                        if st.button("No, choose another", use_container_width=True):
                            reset_from_location_change()
                            st.session_state.location_id_input = ""
                            st.rerun()
                else:
                    st.success("Location confirmed.")
                    wizard_nav_row(
                        primary_label="Continue to backup",
                        primary_key="qm_continue_backup",
                        primary_step=2,
                        kind="quest_migrate",
                    )
        return

    if step == 2:
        with st.container(border=True):
            step_heading("Download backup", "2")
            st.caption(
                f"Location: **{st.session_state.location_name}** "
                f"(`{st.session_state.location_id}`)"
            )
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

            wizard_nav_row(
                back_step=1,
                back_key="qm_back_confirm",
                primary_label="Continue to run",
                primary_key="qm_continue_run",
                primary_disabled=not st.session_state.backup_downloaded,
                primary_step=3,
                kind="quest_migrate",
            )
        return

    with st.container(border=True):
        step_heading("Run migration", "3")
        st.caption(
            f"Location: **{st.session_state.location_name}** "
            f"(`{st.session_state.location_id}`)"
        )
        st.warning("This is the live migration. Location and channel settings will be updated.")
        st.caption(
            "Updates Wolt channels to retail, routes food channels to Quest, and tags the location."
        )

        if st.button("Run migration", type="primary", use_container_width=True):
            try:
                with st.spinner("Running migration..."):
                    results = run_migration(st.session_state.location_id, allowed_account_id)
                track_event(
                    "migration_run",
                    action="migrate",
                    success=all(
                        result.get("ok", True)
                        for result in results
                        if result.get("type") != "warning"
                    ),
                )
                show_results(results)
            except AccountGuardrailError as error:
                st.error(str(error))
            except Exception as error:
                st.error(str(error))

        wizard_nav_row(
            back_step=2,
            back_key="qm_back_backup",
            kind="quest_migrate",
        )

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
            help="Only .zip files in the Quest backup format above are supported.",
            key="quest_revert_uploader",
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
            key="quest_restore_button",
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


def _run_account_move_with_progress(
    location_ids: list[str],
    original_account_id: str,
    destination_account_id: str,
    role_group_id: str,
) -> list[dict]:
    progress = st.progress(0.0, text="Starting account move…")
    status = st.empty()

    def on_progress(fraction: float, message: str):
        progress.progress(min(max(fraction, 0.0), 1.0), text=message)
        status.caption(message)

    results = run_account_move(
        location_ids,
        original_account_id,
        destination_account_id,
        role_group_id,
        on_progress=on_progress,
    )
    progress.progress(1.0, text="Finished")
    status.caption("Finished")
    return results


def _account_move_context_caption():
    role_label = st.session_state.am_role_name or st.session_state.am_role_group_id
    mode_label = (
        "Per location"
        if st.session_state.am_mode == "per_location"
        else "Rest of account"
    )
    st.caption(
        f"`{st.session_state.am_old_account_id}` → `{st.session_state.am_new_account_id}` · "
        f"{mode_label} · role **{role_label}**"
    )


def _account_move_step_accounts():
    with st.container(border=True):
        step_heading("Accounts", "1")
        st.caption(
            "Enter the old/new Deliverect account IDs, then pick a destination role "
            "for Quest users (exactly one linked location). If the right role is missing, "
            "recreate it once from the old account — same name is reused, never duplicated."
        )

        old_col, new_col = st.columns(2)
        with old_col:
            old_account_id = st.text_input(
                "Old account ID",
                value=st.session_state.am_old_account_id,
                placeholder="69774c7c157f655400e9011b",
                key="am_old_account_input",
            )
        with new_col:
            new_account_id = st.text_input(
                "New account ID",
                value=st.session_state.am_new_account_id,
                placeholder="69775643204154fab7012d5f",
                key="am_new_account_input",
            )

        if (
            old_account_id.strip() != st.session_state.am_old_account_id
            or new_account_id.strip() != st.session_state.am_new_account_id
        ):
            st.session_state.am_old_account_id = old_account_id.strip()
            st.session_state.am_new_account_id = new_account_id.strip()
            reset_account_move_from_accounts_change()

        accounts_match_ok = bool(
            st.session_state.am_old_account_id and st.session_state.am_new_account_id
        )
        if (
            accounts_match_ok
            and st.session_state.am_old_account_id == st.session_state.am_new_account_id
        ):
            st.error("Old and new account IDs must be different.")
            accounts_match_ok = False

        if accounts_match_ok:
            if (
                st.session_state.am_roles is None
                or st.session_state.am_roles_account_id != st.session_state.am_new_account_id
            ):
                try:
                    with st.spinner("Loading destination roles…"):
                        roles = list_all_roles(st.session_state.am_new_account_id)
                    roles = sorted(
                        roles,
                        key=lambda role: (role.get("name") or role.get("_id") or "").lower(),
                    )
                    st.session_state.am_roles = roles
                    st.session_state.am_roles_account_id = st.session_state.am_new_account_id
                    if st.session_state.am_role_group_id and not any(
                        role.get("_id") == st.session_state.am_role_group_id for role in roles
                    ):
                        st.session_state.am_role_group_id = ""
                        st.session_state.am_role_name = None
                except Exception as error:
                    st.session_state.am_roles = []
                    st.session_state.am_roles_account_id = st.session_state.am_new_account_id
                    st.error(f"Could not load destination roles: {error}")

            if (
                st.session_state.am_source_roles is None
                or st.session_state.am_source_roles_account_id
                != st.session_state.am_old_account_id
            ):
                try:
                    with st.spinner("Loading old-account roles…"):
                        source_roles = list_all_roles(st.session_state.am_old_account_id)
                    source_roles = sorted(
                        source_roles,
                        key=lambda role: (role.get("name") or role.get("_id") or "").lower(),
                    )
                    st.session_state.am_source_roles = source_roles
                    st.session_state.am_source_roles_account_id = (
                        st.session_state.am_old_account_id
                    )
                except Exception as error:
                    st.session_state.am_source_roles = []
                    st.session_state.am_source_roles_account_id = (
                        st.session_state.am_old_account_id
                    )
                    st.error(f"Could not load old-account roles: {error}")

            roles = st.session_state.am_roles or []
            if not roles:
                st.warning(
                    "No roles found on the destination account. "
                    "Recreate one from the old account below, then select it."
                )
                role_ids = []
                role_labels = {}
            else:
                role_ids = [role.get("_id") for role in roles if role.get("_id")]
                role_labels = {
                    role.get("_id"): role.get("name") or role.get("_id")
                    for role in roles
                    if role.get("_id")
                }

            if role_ids:
                current_role = st.session_state.am_role_group_id
                if current_role not in role_ids:
                    current_role = role_ids[0]
                selected_id = st.selectbox(
                    "Destination role",
                    options=role_ids,
                    index=role_ids.index(current_role),
                    format_func=lambda role_id: f"{role_labels.get(role_id, role_id)} ({role_id})",
                    key="am_role_select",
                    help="Quest users will be assigned this role on the destination account.",
                )
                st.session_state.am_role_group_id = selected_id
                st.session_state.am_role_name = role_labels.get(selected_id, selected_id)
            else:
                st.session_state.am_role_group_id = ""
                st.session_state.am_role_name = None

            source_roles = st.session_state.am_source_roles or []
            recreateable = [
                role
                for role in source_roles
                if role.get("_id") and (role.get("name") or role.get("template"))
            ]
            with st.expander("Role missing? Recreate from old account", expanded=not role_ids):
                st.caption(
                    "Pick a role from the old account. If the destination already has the "
                    "same name, we select that one — we never create a second copy."
                )
                if not recreateable:
                    st.info("No roles found on the old account to recreate.")
                else:
                    source_ids = [role.get("_id") for role in recreateable]
                    source_labels = {
                        role.get("_id"): (
                            f"{role.get('name') or role.get('_id')}"
                            + (" (template)" if role.get("template") else "")
                        )
                        for role in recreateable
                    }
                    source_by_id = {role.get("_id"): role for role in recreateable}
                    recreate_source_id = st.selectbox(
                        "Old-account role to recreate",
                        options=source_ids,
                        format_func=lambda role_id: (
                            f"{source_labels.get(role_id, role_id)} ({role_id})"
                        ),
                        key="am_recreate_source_role",
                    )
                    if st.button(
                        "Recreate / reuse on destination",
                        use_container_width=True,
                        key="am_recreate_role_btn",
                    ):
                        try:
                            source_role = source_by_id.get(recreate_source_id)
                            with st.spinner("Ensuring destination role…"):
                                dest_role, action = ensure_destination_role_from_source(
                                    source_role,
                                    st.session_state.am_new_account_id,
                                    destination_roles=st.session_state.am_roles or [],
                                )
                            refreshed = list_all_roles(st.session_state.am_new_account_id)
                            refreshed = sorted(
                                refreshed,
                                key=lambda role: (
                                    role.get("name") or role.get("_id") or ""
                                ).lower(),
                            )
                            if dest_role.get("_id") and not any(
                                role.get("_id") == dest_role.get("_id") for role in refreshed
                            ):
                                refreshed = [dest_role] + refreshed
                            st.session_state.am_roles = refreshed
                            st.session_state.am_roles_account_id = (
                                st.session_state.am_new_account_id
                            )
                            st.session_state.am_role_group_id = dest_role.get("_id")
                            st.session_state.am_role_name = (
                                dest_role.get("name") or dest_role.get("_id")
                            )
                            track_event(
                                "account_move_role_recreated",
                                action="account_move",
                                role_action=action,
                                source_role_id=recreate_source_id,
                                destination_role_id=dest_role.get("_id"),
                                role_name=st.session_state.am_role_name,
                            )
                            if action == "created":
                                st.success(
                                    f"Created **{st.session_state.am_role_name}** on the "
                                    "destination account and selected it."
                                )
                            elif action == "already_exists":
                                st.info(
                                    f"**{st.session_state.am_role_name}** already exists on "
                                    "the destination — selected it (no duplicate created)."
                                )
                            else:
                                st.info(
                                    f"Using template role **{st.session_state.am_role_name}** "
                                    "(global — not recreated)."
                                )
                            st.rerun()
                        except AccountMoveGuardrailError as error:
                            st.error(str(error))
                        except Exception as error:
                            st.error(f"Could not recreate role: {error}")

        accounts_ready = bool(accounts_match_ok and st.session_state.am_role_group_id)
        if accounts_match_ok and not st.session_state.am_role_group_id:
            st.caption("Select a destination role (or recreate one) to continue.")

        if st.button(
            "Continue to mode",
            type="primary",
            disabled=not accounts_ready,
            use_container_width=True,
            key="am_confirm_accounts",
        ):
            st.session_state.am_accounts_confirmed = True
            set_account_move_step(2)
            track_event(
                "account_move_accounts_confirmed",
                action="account_move",
                old_account_id=st.session_state.am_old_account_id,
                new_account_id=st.session_state.am_new_account_id,
                role_group_id=st.session_state.am_role_group_id,
                role_name=st.session_state.am_role_name,
            )
            st.rerun()


def _account_move_step_mode():
    with st.container(border=True):
        step_heading("Mode", "2")
        _account_move_context_caption()
        mode = st.radio(
            "How do you want to move?",
            options=["per_location", "rest_of_account"],
            format_func=lambda value: (
                "Per location" if value == "per_location" else "Rest of account"
            ),
            horizontal=True,
            key="am_mode_radio",
        )
        if mode != st.session_state.am_mode:
            previous = st.session_state.am_mode
            st.session_state.am_mode = mode
            if mode == "per_location" and previous == "rest_of_account":
                reset_account_move_rest()
            elif mode == "rest_of_account" and previous == "per_location":
                reset_account_move_per_location()
            st.rerun()

        wizard_nav_row(
            back_step=1,
            back_key="am_back_accounts",
            primary_label="Continue to confirm",
            primary_key="am_continue_confirm",
            primary_step=3,
        )


def _account_move_per_location_confirm(original_account_id: str, destination_account_id: str):
    with st.container(border=True):
        step_heading("Confirm original location", "3")
        _account_move_context_caption()
        location_id_input = st.text_input(
            "Original location ID",
            value=st.session_state.am_location_id_input,
            placeholder="6a2ad9de3547b47db45c7b3b",
            key="am_location_input_widget",
        )

        if location_id_input != st.session_state.am_location_id_input:
            st.session_state.am_location_id_input = location_id_input
            reset_account_move_per_location()

        if st.button(
            "Look up location",
            disabled=not location_id_input,
            use_container_width=True,
            key="am_lookup",
        ):
            track_event(
                "account_move_lookup_started",
                action="account_move",
                mode="per_location",
                location_id=location_id_input,
            )
            try:
                snapshot = fetch_move_snapshot(
                    location_id_input,
                    original_account_id,
                    destination_account_id,
                )
                original = snapshot["original_location"]
                destination = snapshot["destination_location"]
                st.session_state.am_location_id = original["_id"]
                st.session_state.am_location_name = original.get("name", "Unknown")
                st.session_state.am_match_name = snapshot.get("match_name")
                st.session_state.am_channel_link_count = len(snapshot["channel_links"])
                st.session_state.am_retained_count = len(
                    snapshot.get("retained_channel_links") or []
                )
                st.session_state.am_user_count = len(snapshot.get("users") or [])
                if destination is not None:
                    st.session_state.am_destination_id = destination["_id"]
                    st.session_state.am_destination_name = destination.get("name", "Unknown")
                else:
                    st.session_state.am_destination_id = None
                    st.session_state.am_destination_name = None
                st.session_state.am_status = snapshot["status"]
                st.session_state.am_snapshot = snapshot
                st.session_state.am_confirmed = False
                st.session_state.am_backup_bytes = None
                st.session_state.am_backup_filename = None
                st.session_state.am_backup_summary = None
                st.session_state.am_backup_downloaded = False
            except AccountMoveGuardrailError as error:
                st.error(str(error))
            except Exception as error:
                st.error(str(error))

        can_continue = False
        if st.session_state.am_location_id:
            location_card(st.session_state.am_location_name, st.session_state.am_location_id)
            retained = st.session_state.get("am_retained_count") or 0
            user_count = st.session_state.get("am_user_count") or 0
            retained_note = (
                f" · Leaving Test Channel: **{retained}**" if retained else ""
            )
            st.caption(
                f"Match name: `{st.session_state.am_match_name}` · "
                f"To move: **{st.session_state.am_channel_link_count}** CL · "
                f"**{user_count}** Quest user(s)"
                f"{retained_note}"
            )
            if st.session_state.am_destination_id:
                st.info(
                    f"Destination: **{st.session_state.am_destination_name}** "
                    f"(`{st.session_state.am_destination_id}`)"
                )

            if st.session_state.am_status == "already_moved":
                marker_note = ""
                if has_migrated_marker(st.session_state.am_location_name or ""):
                    marker_note = " Name already contains a `#MIGRATED…#` marker."
                elif st.session_state.get("am_retained_count"):
                    marker_note = " Only Test Channel remains (left in place)."
                st.warning("This location has nothing to move." + marker_note)
            elif not st.session_state.am_confirmed:
                confirm_col, cancel_col = st.columns(2)
                with confirm_col:
                    if st.button(
                        "Yes, move these channel links",
                        type="primary",
                        use_container_width=True,
                        key="am_confirm",
                    ):
                        st.session_state.am_confirmed = True
                        track_event(
                            "account_move_confirmed",
                            action="account_move",
                            mode="per_location",
                            location_id=st.session_state.am_location_id,
                        )
                        set_account_move_step(4)
                        st.rerun()
                with cancel_col:
                    if st.button("No, choose another", use_container_width=True, key="am_cancel"):
                        reset_account_move_per_location()
                        st.session_state.am_location_id_input = ""
                        st.rerun()
            else:
                st.success("Move confirmed.")
                can_continue = True

        wizard_nav_row(
            back_step=2,
            back_key="am_back_mode_per",
            primary_label="Continue to backup",
            primary_key="am_continue_backup_per",
            primary_disabled=not can_continue,
            primary_step=4 if can_continue else None,
        )


def _account_move_rest_confirm(original_account_id: str, destination_account_id: str):
    with st.container(border=True):
        step_heading("Load remaining locations", "3")
        _account_move_context_caption()
        st.caption(
            "Loads both accounts, matches by exact location name, and migrates every original "
            "location that still has channel links."
        )

        if st.button("Load account locations", use_container_width=True, key="am_rest_load"):
            try:
                with st.spinner("Loading locations..."):
                    originals = list_all_locations(original_account_id)
                    destinations = list_all_locations(destination_account_id)
                    rows = classify_account_locations(
                        originals,
                        destinations,
                        original_account_id,
                    )
                st.session_state.am_rest_rows = rows
                st.session_state.am_rest_loaded = True
                st.session_state.am_backup_bytes = None
                st.session_state.am_backup_filename = None
                st.session_state.am_backup_summary = None
                st.session_state.am_backup_downloaded = False
                st.session_state.am_rest_snapshots = None
                track_event(
                    "account_move_rest_loaded",
                    action="account_move",
                    mode="rest_of_account",
                    ready=sum(1 for row in rows if row["status"] == "ready"),
                    already_moved=sum(1 for row in rows if row["status"] == "already_moved"),
                    unmatched=sum(1 for row in rows if row["status"] == "unmatched"),
                )
            except Exception as error:
                st.error(str(error))

        can_continue = False
        if st.session_state.am_rest_loaded and st.session_state.am_rest_rows:
            rows = st.session_state.am_rest_rows
            ready = [row for row in rows if row["status"] == "ready"]
            already_moved = [row for row in rows if row["status"] == "already_moved"]
            unmatched = [row for row in rows if row["status"] == "unmatched"]

            account_move_match_summary(len(ready), len(already_moved), len(unmatched))

            if ready:
                st.markdown("**Ready to move**")
                st.dataframe(
                    [
                        {
                            "Original": row["original"].get("name"),
                            "Original ID": row["original"]["_id"],
                            "Destination": row["destination"].get("name") if row["destination"] else "",
                            "Destination ID": row["destination"]["_id"] if row["destination"] else "",
                            "Match name": row["match_name"],
                            "To move": len(row["channel_link_ids"]),
                            "Quest users": len(row.get("users") or []),
                            "Keep Test Channel": len(row.get("retained_channel_link_ids") or []),
                        }
                        for row in ready
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
                can_continue = True

            if unmatched:
                with st.expander(f"Unmatched ({len(unmatched)})"):
                    for row in unmatched:
                        st.write(
                            f"- {row['original'].get('name')} (`{row['original']['_id']}`) "
                            f"name `{row['match_name']}` — {len(row['channel_link_ids'])} to move"
                        )

            if already_moved:
                with st.expander(f"Already moved / skipped ({len(already_moved)})"):
                    for row in already_moved:
                        retained = len(row.get("retained_channel_link_ids") or [])
                        reason = (
                            "only Test Channel left"
                            if retained and not row["channel_link_ids"]
                            else "already moved / nothing to move"
                        )
                        st.write(
                            f"- {row['original'].get('name')} (`{row['original']['_id']}`) — {reason}"
                        )

            if not ready:
                st.warning("No locations left to move.")

        wizard_nav_row(
            back_step=2,
            back_key="am_back_mode_rest",
            primary_label="Continue to backup",
            primary_key="am_continue_backup_rest",
            primary_disabled=not can_continue,
            primary_step=4 if can_continue else None,
        )


def _account_move_backup_step(original_account_id: str, destination_account_id: str):
    with st.container(border=True):
        step_heading("Download backup", "4")
        _account_move_context_caption()

        if st.session_state.am_mode == "per_location":
            if not st.session_state.am_confirmed or not st.session_state.am_snapshot:
                st.warning("Confirm a location first.")
                wizard_nav_row(back_step=3, back_key="am_back_confirm_from_backup_empty")
                return

            st.caption("Create and download a zip backup before moving channel links.")
            if st.button("Create backup zip", use_container_width=True, key="am_create_backup"):
                try:
                    backup_bytes, backup_filename, summary = create_account_move_backup_zip(
                        [st.session_state.am_snapshot],
                        original_account_id,
                        destination_account_id,
                        mode="per_location",
                    )
                    st.session_state.am_backup_bytes = backup_bytes
                    st.session_state.am_backup_filename = backup_filename
                    st.session_state.am_backup_summary = summary
                    st.session_state.am_backup_downloaded = False
                    track_event(
                        "account_move_backup_created",
                        action="account_move",
                        mode="per_location",
                        location_id=st.session_state.am_location_id,
                        filename=backup_filename,
                        channel_link_count=summary["channel_link_count"],
                    )
                    st.success(
                        f"Backup ready · {summary['channel_link_count']} channel link(s) "
                        f"({summary['movable_channel_link_count']} to move) · "
                        f"{summary.get('user_count', 0)} Quest user(s)."
                    )
                except Exception as error:
                    st.error(str(error))

            if st.session_state.am_backup_bytes:
                summary = st.session_state.get("am_backup_summary") or {}
                st.caption(
                    f"Zip includes **{summary.get('channel_link_count', '?')}** channel link(s) "
                    f"across **{summary.get('location_count', 1)}** location(s)."
                )
                st.download_button(
                    label="Download backup zip",
                    data=st.session_state.am_backup_bytes,
                    file_name=st.session_state.am_backup_filename,
                    mime="application/zip",
                    use_container_width=True,
                    key="am_download_backup",
                )
                st.session_state.am_backup_downloaded = st.checkbox(
                    "I have downloaded the backup zip",
                    value=st.session_state.am_backup_downloaded,
                    key="am_backup_checkbox",
                )
        else:
            rows = st.session_state.am_rest_rows or []
            ready = [row for row in rows if row["status"] == "ready"]
            if not ready:
                st.warning("Load ready locations first.")
                wizard_nav_row(back_step=3, back_key="am_back_confirm_from_backup_rest_empty")
                return

            st.caption(f"Backup covers all {len(ready)} ready location(s).")
            if st.button("Create backup zip", use_container_width=True, key="am_rest_backup"):
                try:
                    with st.spinner("Building backup (fetching full location snapshots)..."):
                        snapshots = []
                        progress = st.progress(0.0, text="Preparing backup…")
                        for index, row in enumerate(ready):
                            progress.progress(
                                (index) / max(len(ready), 1),
                                text=f"Backing up {row['original'].get('name')}…",
                            )
                            original, original_status = get_location(row["original"]["_id"])
                            if original_status != 200:
                                raise RuntimeError(
                                    f"Failed to refresh original location "
                                    f"{row['original']['_id']}: HTTP {original_status}"
                                )
                            destination, destination_status = get_location(
                                row["destination"]["_id"]
                            )
                            if destination_status != 200:
                                raise RuntimeError(
                                    f"Failed to refresh destination location "
                                    f"{row['destination']['_id']}: HTTP {destination_status}"
                                )
                            snapshots.append(
                                {
                                    "original_location": original,
                                    "destination_location": destination,
                                    "channel_links": list(row.get("channel_links") or []),
                                    "retained_channel_links": list(
                                        row.get("retained_channel_links") or []
                                    ),
                                    "users": list(row.get("users") or []),
                                    "match_name": row.get("match_name"),
                                    "status": row.get("status"),
                                }
                            )
                        backup_bytes, backup_filename, summary = create_account_move_backup_zip(
                            snapshots,
                            original_account_id,
                            destination_account_id,
                            mode="rest_of_account",
                        )
                        progress.progress(1.0, text="Backup zip ready")
                    st.session_state.am_backup_bytes = backup_bytes
                    st.session_state.am_backup_filename = backup_filename
                    st.session_state.am_backup_summary = summary
                    st.session_state.am_backup_downloaded = False
                    st.session_state.am_rest_snapshots = snapshots
                    track_event(
                        "account_move_backup_created",
                        action="account_move",
                        mode="rest_of_account",
                        filename=backup_filename,
                        location_count=summary["location_count"],
                        channel_link_count=summary["channel_link_count"],
                    )
                    st.success(
                        f"Backup ready · {summary['location_count']} location(s) · "
                        f"{summary['channel_link_count']} channel link(s) "
                        f"({summary['movable_channel_link_count']} to move) · "
                        f"{summary.get('user_count', 0)} Quest user(s)."
                    )
                except Exception as error:
                    st.error(str(error))

            if st.session_state.am_backup_bytes:
                summary = st.session_state.get("am_backup_summary") or {}
                st.caption(
                    f"Zip includes **{summary.get('channel_link_count', '?')}** channel link(s) "
                    f"across **{summary.get('location_count', '?')}** location(s) "
                    f"· {summary.get('size_bytes', 0):,} bytes."
                )
                st.download_button(
                    label="Download backup zip",
                    data=bytes(st.session_state.am_backup_bytes),
                    file_name=st.session_state.am_backup_filename,
                    mime="application/zip",
                    use_container_width=True,
                    key="am_rest_download",
                )
                st.session_state.am_backup_downloaded = st.checkbox(
                    "I have downloaded the backup zip",
                    value=st.session_state.am_backup_downloaded,
                    key="am_rest_checkbox",
                )

        wizard_nav_row(
            back_step=3,
            back_key="am_back_confirm_from_backup",
            primary_label="Continue to run move",
            primary_key="am_continue_run",
            primary_disabled=not st.session_state.am_backup_downloaded,
            primary_step=5,
        )


def _account_move_run_step(
    original_account_id: str,
    destination_account_id: str,
    role_group_id: str,
):
    with st.container(border=True):
        step_heading("Run account move", "5")
        _account_move_context_caption()
        st.warning(
            "This is the live move. Channel links, location names, and Quest users "
            "will be updated on Deliverect."
        )

        if st.session_state.am_mode == "per_location":
            st.caption(
                "Moves channel links to the destination account/location, clears them on the "
                "original, and appends `#MIGRATEDTO{destinationId}#` to the original name."
            )
            if st.button("Run account move", type="primary", use_container_width=True, key="am_run"):
                try:
                    results = _run_account_move_with_progress(
                        [st.session_state.am_location_id],
                        original_account_id,
                        destination_account_id,
                        role_group_id,
                    )
                    track_event(
                        "account_move_run",
                        action="account_move",
                        mode="per_location",
                        location_id=st.session_state.am_location_id,
                        success=all(
                            result.get("ok", True)
                            for result in results
                            if result.get("type") != "warning"
                        ),
                    )
                    show_account_move_results(results)
                except AccountMoveGuardrailError as error:
                    st.error(str(error))
                except Exception as error:
                    st.error(str(error))
        else:
            rows = st.session_state.am_rest_rows or []
            ready = [row for row in rows if row["status"] == "ready"]
            st.caption(f"Moves channel links for {len(ready)} location(s).")
            if st.button(
                "Run account move for ready locations",
                type="primary",
                use_container_width=True,
                key="am_rest_run",
            ):
                try:
                    location_ids = [row["original"]["_id"] for row in ready]
                    results = _run_account_move_with_progress(
                        location_ids,
                        original_account_id,
                        destination_account_id,
                        role_group_id,
                    )
                    track_event(
                        "account_move_run",
                        action="account_move",
                        mode="rest_of_account",
                        location_count=len(location_ids),
                        success=all(
                            result.get("ok", True)
                            for result in results
                            if result.get("type") != "warning"
                        ),
                    )
                    show_account_move_results(results)
                    st.session_state.am_rest_loaded = False
                except AccountMoveGuardrailError as error:
                    st.error(str(error))
                except Exception as error:
                    st.error(str(error))

        wizard_nav_row(back_step=4, back_key="am_back_backup_from_run")


def account_move_page():
    step = account_move_current_step()

    # Clamp the viewed step to what the session has unlocked.
    if step >= 2 and not st.session_state.am_accounts_confirmed:
        set_account_move_step(1)
        step = 1
    elif step >= 4:
        if st.session_state.am_mode == "per_location" and not st.session_state.am_confirmed:
            set_account_move_step(3)
            step = 3
        elif st.session_state.am_mode == "rest_of_account" and not (
            st.session_state.am_rest_loaded
            and any(
                row.get("status") == "ready"
                for row in (st.session_state.am_rest_rows or [])
            )
        ):
            set_account_move_step(3)
            step = 3
    if step >= 5 and not st.session_state.am_backup_downloaded:
        set_account_move_step(4)
        step = 4

    wizard_steps(
        ACCOUNT_MOVE_WIZARD_STEPS,
        step,
        note="Only <strong>Run move</strong> changes live data. Use Back to revisit earlier steps.",
    )

    if step == 1:
        _account_move_step_accounts()
        return

    if step == 2:
        _account_move_step_mode()
        return

    original_account_id = st.session_state.am_old_account_id
    destination_account_id = st.session_state.am_new_account_id
    role_group_id = st.session_state.am_role_group_id

    if step == 3:
        if st.session_state.am_mode == "per_location":
            _account_move_per_location_confirm(original_account_id, destination_account_id)
        else:
            _account_move_rest_confirm(original_account_id, destination_account_id)
        return

    if step == 4:
        _account_move_backup_step(original_account_id, destination_account_id)
        return

    _account_move_run_step(original_account_id, destination_account_id, role_group_id)


def account_revert_page():
    with st.container(border=True):
        step_heading("Accounts")
        st.caption(
            "Enter the same old and new account IDs used for the move. "
            "They must match the backup manifest."
        )

        old_col, new_col = st.columns(2)
        with old_col:
            old_account_id = st.text_input(
                "Old account ID",
                value=st.session_state.ar_old_account_id,
                placeholder="69774c7c157f655400e9011b",
                key="ar_old_account_input",
            )
        with new_col:
            new_account_id = st.text_input(
                "New account ID",
                value=st.session_state.ar_new_account_id,
                placeholder="69775643204154fab7012d5f",
                key="ar_new_account_input",
            )

        st.session_state.ar_old_account_id = old_account_id.strip()
        st.session_state.ar_new_account_id = new_account_id.strip()

        accounts_ready = bool(
            st.session_state.ar_old_account_id and st.session_state.ar_new_account_id
        )
        if (
            accounts_ready
            and st.session_state.ar_old_account_id == st.session_state.ar_new_account_id
        ):
            st.error("Old and new account IDs must be different.")
            accounts_ready = False

    with st.container(border=True):
        step_heading("Restore account move from backup")
        st.caption(
            "Upload an account-move backup zip to move channel links back and restore both locations."
        )
        account_move_format_box()

    st.markdown("<div style='margin-top: 1rem'></div>", unsafe_allow_html=True)

    with st.container(border=True):
        uploaded_backup = st.file_uploader(
            "Upload account-move backup zip",
            type=["zip"],
            help="Only .zip files in the Account move backup format above are supported.",
            key="account_revert_uploader",
        )

        if uploaded_backup is not None:
            st.caption(f"Selected: `{uploaded_backup.name}`")
            if st.session_state.get("_tracked_am_upload") != uploaded_backup.name:
                try:
                    backup = load_account_move_backup_zip(uploaded_backup.getvalue())
                    moves = backup["manifest"].get("moves", [])
                    st.session_state.account_revert_move_count = len(moves)
                    if moves:
                        st.session_state.revert_location_id = moves[0]["original_location_id"]
                        st.session_state.revert_location_name = moves[0].get(
                            "original_location_name"
                        )
                    st.session_state._tracked_am_upload = uploaded_backup.name
                    track_event(
                        "account_move_backup_uploaded",
                        action="account_revert",
                        mode=backup["manifest"].get("mode"),
                        location_count=len(moves),
                    )
                except Exception:
                    pass

        if st.button(
            "Restore account move",
            type="primary",
            disabled=uploaded_backup is None or not accounts_ready,
            use_container_width=True,
            key="account_restore_button",
        ):
            try:
                backup = load_account_move_backup_zip(uploaded_backup.getvalue())
                moves = backup["manifest"].get("moves", [])
                st.info(
                    f"Restoring **{len(moves)}** location move(s) "
                    f"from {backup['manifest'].get('created_at')}"
                )
                progress = st.progress(0.0, text="Starting revert…")
                status = st.empty()

                def on_progress(fraction: float, message: str):
                    progress.progress(min(max(fraction, 0.0), 1.0), text=message)
                    status.caption(message)

                results = run_account_move_revert(
                    backup,
                    st.session_state.ar_old_account_id,
                    st.session_state.ar_new_account_id,
                    on_progress=on_progress,
                )
                progress.progress(1.0, text="Finished")
                status.caption("Finished")
                if moves:
                    st.session_state.revert_location_id = moves[0]["original_location_id"]
                    st.session_state.revert_location_name = moves[0].get(
                        "original_location_name"
                    )
                track_event(
                    "account_move_revert_run",
                    action="account_revert",
                    mode=backup["manifest"].get("mode"),
                    location_count=len(moves),
                    backup_created_at=backup["manifest"].get("created_at"),
                    old_account_id=st.session_state.ar_old_account_id,
                    new_account_id=st.session_state.ar_new_account_id,
                    success=all(
                        result.get("ok", True)
                        for result in results
                        if result.get("type") != "warning"
                    ),
                )
                show_account_move_results(
                    results,
                    title="Revert overview",
                    success_label="Fully restored",
                )
            except AccountMoveGuardrailError as error:
                st.error(str(error))
            except Exception as error:
                st.error(str(error))


apply_styles()
render_password_gate()
render_header()
allowed_account_id = load_credentials()
active_page = render_nav()

if active_page == "migrate":
    init_migrate_session_state()
    track_page("migrate")
    migrate_page(allowed_account_id)
elif active_page == "revert":
    track_page("revert")
    revert_page(allowed_account_id)
elif active_page == "account_move":
    init_account_move_session_state()
    track_page("account_move")
    account_move_page()
else:
    init_account_revert_session_state()
    track_page("account_revert")
    account_revert_page()
