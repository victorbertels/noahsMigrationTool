import streamlit as st

st.set_page_config(
    page_title="Noah's Migration Tools",
    layout="centered",
    initial_sidebar_state="collapsed",
)

from account_migration import (
    AccountMoveGuardrailError,
    FORCE_PICKER_LOGOUT_ENABLED,
    classify_account_locations,
    create_account_move_backup_zip,
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
    show_account_move_results,
    show_results,
    step_heading,
    wizard_steps,
)


def migrate_page(allowed_account_id: str):
    wizard_steps(
        QUEST_MIGRATE_WIZARD_STEPS,
        quest_migrate_current_step(),
        note="Only <strong>Run migrate</strong> changes live data. Earlier steps are confirm &amp; backup.",
    )
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
            track_event("location_lookup_started", action="migrate", location_id=location_id_input)
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
            st.warning("This is the live migration. Location and channel settings will be updated.")
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
    dry_run: bool = False,
    picker_logout_token: str = "",
) -> list[dict]:
    progress = st.progress(
        0.0,
        text="Starting dry run…" if dry_run else "Starting account move…",
    )
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
        dry_run=dry_run,
        picker_logout_token=picker_logout_token,
    )
    progress.progress(1.0, text="Finished")
    status.caption("Finished")
    return results


def _account_move_per_location(
    original_account_id: str,
    destination_account_id: str,
    role_group_id: str,
):
    with st.container(border=True):
        step_heading("Confirm original location", "3")
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
                st.warning(
                    "This location has nothing to move." + marker_note
                )
                return

            if not st.session_state.am_confirmed:
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
                        st.rerun()
                with cancel_col:
                    if st.button("No, choose another", use_container_width=True, key="am_cancel"):
                        reset_account_move_per_location()
                        st.session_state.am_location_id_input = ""
                        st.rerun()
            else:
                st.success("Move confirmed.")

    if st.session_state.am_confirmed and st.session_state.am_snapshot:
        with st.container(border=True):
            step_heading("Download backup", "4")
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

    if st.session_state.am_confirmed and st.session_state.am_backup_downloaded:
        with st.container(border=True):
            step_heading("Run account move", "5")
            st.info(
                "Dry run reads current state and lists every write that would happen "
                "(busy mode, logout, snoozes, channel links, locations, users) — no POSTs/PATCHes."
            )
            st.warning(
                "Run account move is live: busy mode, snooze copy, then channel links / "
                "locations / Quest users are updated on Deliverect."
            )
            st.caption(
                "Prep: closes original + destination via busy mode"
                + (
                    ", logs out Quest pickers"
                    if FORCE_PICKER_LOGOUT_ENABLED
                    else " (picker force logout muted)"
                )
                + ", and copies active snoozed PLUs to the destination. Then moves channel links, "
                "clears them on the original (except Test Channel), appends "
                "`#MIGRATEDTO{destinationId}#` to the original name, and assigns each Quest "
                "user a matched or duplicated role."
            )
            picker_logout_token = ""
            if FORCE_PICKER_LOGOUT_ENABLED:
                picker_logout_token = st.text_input(
                    "Picker logout token",
                    type="password",
                    placeholder="Paste a user/portal Bearer token (not M2M)",
                    help=(
                        "Used only for picker-backend force logout. Machine-to-machine tokens "
                        "are rejected by that API. Optional for dry run; required for live logout."
                    ),
                    key="am_picker_logout_token",
                )
            dry_col, live_col = st.columns(2)
            with dry_col:
                run_dry = st.button(
                    "Dry run",
                    use_container_width=True,
                    key="am_dry_run",
                )
            with live_col:
                run_live = st.button(
                    "Run account move",
                    type="primary",
                    use_container_width=True,
                    key="am_run",
                )
            if run_dry or run_live:
                dry_run = bool(run_dry)
                if (
                    FORCE_PICKER_LOGOUT_ENABLED
                    and not dry_run
                    and not (picker_logout_token or "").strip()
                ):
                    st.error(
                        "Paste a user/portal token in Picker logout token before the live move "
                        "(M2M tokens do not work for force logout)."
                    )
                else:
                    try:
                        results = _run_account_move_with_progress(
                            [st.session_state.am_location_id],
                            original_account_id,
                            destination_account_id,
                            role_group_id,
                            dry_run=dry_run,
                            picker_logout_token=picker_logout_token,
                        )
                        track_event(
                            "account_move_dry_run" if dry_run else "account_move_run",
                            action="account_move",
                            mode="per_location",
                            dry_run=dry_run,
                            location_id=st.session_state.am_location_id,
                            success=all(
                                result.get("ok", True)
                                for result in results
                                if result.get("type") != "warning"
                            ),
                        )
                        show_account_move_results(
                            results,
                            title="Dry run overview" if dry_run else "Location overview",
                            success_label="Would migrate" if dry_run else "Fully migrated",
                        )
                    except AccountMoveGuardrailError as error:
                        st.error(str(error))
                    except Exception as error:
                        st.error(str(error))


def _account_move_rest_of_account(
    original_account_id: str,
    destination_account_id: str,
    role_group_id: str,
):
    with st.container(border=True):
        step_heading("Load remaining locations", "3")
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

        if not st.session_state.am_rest_loaded or not st.session_state.am_rest_rows:
            return

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
            return

    with st.container(border=True):
        step_heading("Download backup", "4")
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
                        # Refresh location docs, reuse already-fetched channel links.
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

    if st.session_state.am_backup_downloaded:
        with st.container(border=True):
            step_heading("Run account move", "5")
            st.info(
                "Dry run reads current state and lists every write that would happen "
                "(busy mode, logout, snoozes, channel links, locations, users) — no POSTs/PATCHes."
            )
            st.warning(
                "Run account move is live: busy mode, snooze copy, then channel links / "
                f"locations / Quest users are updated for {len(ready)} ready location(s)."
            )
            st.caption(
                "Same as per-location: busy-mode close"
                + (
                    ", picker logout, "
                    if FORCE_PICKER_LOGOUT_ENABLED
                    else " (picker force logout muted), "
                )
                + "snooze copy, then channel links move, original gets `#MIGRATEDTO…#`, "
                "and Quest users get a matched or duplicated role."
            )
            picker_logout_token = ""
            if FORCE_PICKER_LOGOUT_ENABLED:
                picker_logout_token = st.text_input(
                    "Picker logout token",
                    type="password",
                    placeholder="Paste a user/portal Bearer token (not M2M)",
                    help=(
                        "Used only for picker-backend force logout. Machine-to-machine tokens "
                        "are rejected by that API. Optional for dry run; required for live logout."
                    ),
                    key="am_picker_logout_token",
                )
            dry_col, live_col = st.columns(2)
            with dry_col:
                run_dry = st.button(
                    "Dry run for ready locations",
                    use_container_width=True,
                    key="am_rest_dry_run",
                )
            with live_col:
                run_live = st.button(
                    "Run account move for ready locations",
                    type="primary",
                    use_container_width=True,
                    key="am_rest_run",
                )
            if run_dry or run_live:
                dry_run = bool(run_dry)
                location_ids = [row["original"]["_id"] for row in ready]
                if (
                    FORCE_PICKER_LOGOUT_ENABLED
                    and not dry_run
                    and not (picker_logout_token or "").strip()
                ):
                    st.error(
                        "Paste a user/portal token in Picker logout token before the live move "
                        "(M2M tokens do not work for force logout)."
                    )
                else:
                    try:
                        results = _run_account_move_with_progress(
                            location_ids,
                            original_account_id,
                            destination_account_id,
                            role_group_id,
                            dry_run=dry_run,
                            picker_logout_token=picker_logout_token,
                        )
                        track_event(
                            "account_move_dry_run" if dry_run else "account_move_run",
                            action="account_move",
                            mode="rest_of_account",
                            dry_run=dry_run,
                            location_count=len(location_ids),
                            success=all(
                                result.get("ok", True)
                                for result in results
                                if result.get("type") != "warning"
                            ),
                        )
                        show_account_move_results(
                            results,
                            title="Dry run overview" if dry_run else "Location overview",
                            success_label="Would migrate" if dry_run else "Fully migrated",
                        )
                        if not dry_run:
                            # Force reload classification next time after a live move
                            st.session_state.am_rest_loaded = False
                    except AccountMoveGuardrailError as error:
                        st.error(str(error))
                    except Exception as error:
                        st.error(str(error))


def account_move_page():
    wizard_steps(
        ACCOUNT_MOVE_WIZARD_STEPS,
        account_move_current_step(),
        note="Only <strong>Run move</strong> changes live data. Dry run is read-only. Steps 1–4 are setup, confirm &amp; backup.",
    )
    with st.container(border=True):
        step_heading("Accounts", "1")
        st.caption(
            "Enter the old/new Deliverect account IDs. Quest users keep their current role when "
            "possible: we match it by name on the destination, or duplicate it if missing. "
            "Pick a fallback destination role below for users that have no role."
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

        # Load destination roles once the new account ID is set.
        if accounts_match_ok:
            if (
                st.session_state.am_roles is None
                or st.session_state.am_roles_account_id != st.session_state.am_new_account_id
            ):
                try:
                    with st.spinner("Loading destination roles…"):
                        roles = list_all_roles(st.session_state.am_new_account_id)
                    # Prefer a readable name field; fall back to _id.
                    roles = sorted(
                        roles,
                        key=lambda role: (role.get("name") or role.get("_id") or "").lower(),
                    )
                    st.session_state.am_roles = roles
                    st.session_state.am_roles_account_id = st.session_state.am_new_account_id
                    # Clear previous selection if roles were reloaded for a new account.
                    if st.session_state.am_role_group_id and not any(
                        role.get("_id") == st.session_state.am_role_group_id for role in roles
                    ):
                        st.session_state.am_role_group_id = ""
                        st.session_state.am_role_name = None
                except Exception as error:
                    st.session_state.am_roles = []
                    st.session_state.am_roles_account_id = st.session_state.am_new_account_id
                    st.error(f"Could not load roles: {error}")

            roles = st.session_state.am_roles or []
            if not roles:
                st.info(
                    "No roles found on the destination account yet. "
                    "Quest users' roles will be duplicated from the old account during the move."
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
                none_option = ""
                options = [none_option] + role_ids
                current_role = st.session_state.am_role_group_id or none_option
                if current_role not in options:
                    current_role = none_option
                selected_id = st.selectbox(
                    "Fallback destination role (optional)",
                    options=options,
                    index=options.index(current_role),
                    format_func=lambda role_id: (
                        "— None (match/duplicate each Quest user's role) —"
                        if role_id == none_option
                        else f"{role_labels.get(role_id, role_id)} ({role_id})"
                    ),
                    key="am_role_select",
                    help=(
                        "Used only when a Quest user has no role, or their role cannot be "
                        "matched/duplicated. Otherwise each user keeps a same-named "
                        "(or newly duplicated) role."
                    ),
                )
                if selected_id:
                    st.session_state.am_role_group_id = selected_id
                    st.session_state.am_role_name = role_labels.get(selected_id, selected_id)
                else:
                    st.session_state.am_role_group_id = ""
                    st.session_state.am_role_name = None
            else:
                st.session_state.am_role_group_id = ""
                st.session_state.am_role_name = None

        accounts_ready = accounts_match_ok

        if not st.session_state.am_accounts_confirmed:
            if st.button(
                "Use these accounts",
                type="primary",
                disabled=not accounts_ready,
                use_container_width=True,
                key="am_confirm_accounts",
            ):
                st.session_state.am_accounts_confirmed = True
                track_event(
                    "account_move_accounts_confirmed",
                    action="account_move",
                    old_account_id=st.session_state.am_old_account_id,
                    new_account_id=st.session_state.am_new_account_id,
                    role_group_id=st.session_state.am_role_group_id or None,
                    role_name=st.session_state.am_role_name,
                )
                st.rerun()
            return

        if st.session_state.am_role_group_id:
            role_label = st.session_state.am_role_name or st.session_state.am_role_group_id
            role_note = (
                f"fallback role **{role_label}** (`{st.session_state.am_role_group_id}`)"
            )
        else:
            role_note = "Quest roles matched/duplicated from each user (no fallback selected)"
        st.success(
            f"Moving from `{st.session_state.am_old_account_id}` → "
            f"`{st.session_state.am_new_account_id}` · {role_note}"
        )
        if st.button("Change accounts", use_container_width=True, key="am_change_accounts"):
            reset_account_move_from_accounts_change()
            st.rerun()

    original_account_id = st.session_state.am_old_account_id
    destination_account_id = st.session_state.am_new_account_id
    role_group_id = st.session_state.am_role_group_id

    with st.container(border=True):
        step_heading("Mode", "2")
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

    if st.session_state.am_mode == "per_location":
        _account_move_per_location(
            original_account_id, destination_account_id, role_group_id
        )
    else:
        _account_move_rest_of_account(
            original_account_id, destination_account_id, role_group_id
        )


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
