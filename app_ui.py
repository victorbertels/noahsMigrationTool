import hmac
import os

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from auth import set_credentials


def apply_styles():
    st.markdown(
        """
        <style>
            [data-testid="stSidebar"] { display: none; }
            [data-testid="collapsedControl"] { display: none; }
            .block-container { padding-top: 1.5rem; max-width: 820px; }
            .app-header {
                background: linear-gradient(135deg, #1a1f36 0%, #2d3561 100%);
                border-radius: 14px;
                padding: 1.6rem 1.8rem;
                margin-bottom: 1.2rem;
                color: #ffffff;
            }
            .app-header h1 {
                margin: 0;
                font-size: 1.75rem;
                font-weight: 700;
                letter-spacing: -0.02em;
            }
            .app-header p {
                margin: 0.35rem 0 0 0;
                color: #c8d0f0;
                font-size: 0.95rem;
            }
            .step-label {
                display: inline-block;
                background: #eef1ff;
                color: #3d4f9f;
                font-size: 0.72rem;
                font-weight: 700;
                letter-spacing: 0.06em;
                text-transform: uppercase;
                padding: 0.2rem 0.55rem;
                border-radius: 999px;
                margin-bottom: 0.35rem;
            }
            .wizard-rail {
                background: #f7f8fc;
                border: 1px solid #e2e6f3;
                border-radius: 12px;
                padding: 0.9rem 1rem 1rem 1rem;
                margin: 0 0 1.1rem 0;
            }
            .wizard-rail-note {
                font-size: 0.82rem;
                color: #6b7280;
                margin: 0 0 0.65rem 0;
            }
            .wizard-rail-note strong {
                color: #b45309;
            }
            .wizard-steps {
                display: flex;
                flex-wrap: wrap;
                align-items: flex-start;
                gap: 0.35rem 0;
                list-style: none;
                margin: 0;
                padding: 0;
            }
            .wizard-step {
                display: flex;
                align-items: center;
                gap: 0.4rem;
                min-width: 0;
            }
            .wizard-step + .wizard-step::before {
                content: "";
                width: 1.1rem;
                height: 2px;
                background: #d1d5db;
                margin: 0 0.35rem 0 0.15rem;
                flex-shrink: 0;
            }
            .wizard-bullet {
                width: 1.35rem;
                height: 1.35rem;
                border-radius: 999px;
                border: 2px solid #c5cbe3;
                background: #ffffff;
                color: #6b7280;
                font-size: 0.72rem;
                font-weight: 700;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                flex-shrink: 0;
            }
            .wizard-label {
                font-size: 0.82rem;
                font-weight: 600;
                color: #6b7280;
                white-space: nowrap;
            }
            .wizard-tag {
                font-size: 0.65rem;
                font-weight: 700;
                letter-spacing: 0.04em;
                text-transform: uppercase;
                color: #b45309;
                background: #fff7ed;
                border: 1px solid #fed7aa;
                border-radius: 999px;
                padding: 0.1rem 0.4rem;
                margin-left: 0.15rem;
            }
            .wizard-step.done .wizard-bullet {
                background: #ecfdf5;
                border-color: #34d399;
                color: #047857;
            }
            .wizard-step.done .wizard-label {
                color: #047857;
            }
            .wizard-step.done + .wizard-step::before {
                background: #6ee7b7;
            }
            .wizard-step.active .wizard-bullet {
                background: #3d4f9f;
                border-color: #3d4f9f;
                color: #ffffff;
            }
            .wizard-step.active .wizard-label {
                color: #1a1f36;
            }
            .wizard-step.move .wizard-bullet {
                border-color: #f59e0b;
            }
            .wizard-step.move.active .wizard-bullet {
                background: #b45309;
                border-color: #b45309;
                color: #ffffff;
            }
            .wizard-step.move.active .wizard-label {
                color: #92400e;
            }
            .wizard-step.move.done .wizard-bullet {
                background: #fff7ed;
                border-color: #f59e0b;
                color: #b45309;
            }
            .location-card {
                background: #f7f8fc;
                border: 1px solid #e2e6f3;
                border-radius: 12px;
                padding: 1rem 1.2rem;
                margin: 0.5rem 0 1rem 0;
            }
            .location-card .name {
                font-size: 1.15rem;
                font-weight: 600;
                color: #1a1f36;
                margin: 0;
            }
            .location-card .id {
                font-size: 0.85rem;
                color: #6b7280;
                margin: 0.25rem 0 0 0;
                font-family: monospace;
            }
            .match-summary {
                display: flex;
                flex-wrap: wrap;
                gap: 0.6rem;
                margin: 0.75rem 0 1rem 0;
            }
            .match-chip {
                display: inline-flex;
                align-items: center;
                gap: 0.35rem;
                padding: 0.45rem 0.75rem;
                border-radius: 999px;
                font-size: 0.88rem;
                font-weight: 600;
                border: 1px solid transparent;
            }
            .match-chip.ready {
                background: #ecfdf5;
                color: #047857;
                border-color: #a7f3d0;
            }
            .match-chip.muted {
                background: #f3f4f6;
                color: #6b7280;
                border-color: #e5e7eb;
            }
            .match-chip.warn {
                background: #fff7ed;
                color: #c2410c;
                border-color: #fed7aa;
            }
            .match-all-good {
                background: #ecfdf5;
                border: 1px solid #a7f3d0;
                border-radius: 12px;
                padding: 0.85rem 1rem;
                margin: 0.5rem 0 1rem 0;
                color: #065f46;
            }
            .match-all-good strong {
                display: block;
                font-size: 1rem;
                margin-bottom: 0.15rem;
            }
            .match-all-good span {
                font-size: 0.9rem;
                color: #047857;
            }
            .format-box {
                background: #f9fafb;
                border: 1px solid #e5e7eb;
                border-radius: 10px;
                padding: 1rem 1.2rem;
                font-size: 0.9rem;
                color: #374151;
            }
            .format-box code {
                background: #eef1ff;
                color: #3d4f9f;
                padding: 0.1rem 0.35rem;
                border-radius: 4px;
            }
            .format-box pre {
                background: #1a1f36;
                color: #e8ecff;
                border-radius: 8px;
                padding: 0.8rem 1rem;
                font-size: 0.82rem;
                margin: 0.6rem 0 0 0;
            }
            div[data-testid="stVerticalBlock"] > div[style*="border"] {
                border-radius: 12px !important;
                border-color: #e2e6f3 !important;
                background: #ffffff;
            }
            .stButton > button[kind="primary"] {
                background: #3d4f9f;
                border: none;
            }
            .stButton > button[kind="primary"]:hover {
                background: #2f3d7a;
                border: none;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header():
    st.markdown(
        """
        <div class="app-header">
            <h1>Noah's Migration Tools</h1>
            <p>Quest settings migration and account channel-link moves, with backup &amp; restore</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


PAGE_LABELS = {
    "migrate": "Quest migrate",
    "revert": "Quest revert",
    "account_move": "Account move",
    "account_revert": "Account revert",
}


def render_nav() -> str:
    if "active_page" not in st.session_state:
        st.session_state.active_page = "migrate"

    # Migrate older session values from the 2-button nav
    if st.session_state.active_page not in PAGE_LABELS:
        st.session_state.active_page = "migrate"

    row1 = st.columns(2)
    row2 = st.columns(2)
    page_order = ["migrate", "revert", "account_move", "account_revert"]
    for index, page_key in enumerate(page_order):
        column = row1[index] if index < 2 else row2[index - 2]
        with column:
            if st.button(
                PAGE_LABELS[page_key],
                type="primary" if st.session_state.active_page == page_key else "secondary",
                use_container_width=True,
                key=f"nav_{page_key}",
            ):
                st.session_state.active_page = page_key
                st.rerun()

    st.markdown("<div style='margin-bottom: 1.2rem'></div>", unsafe_allow_html=True)
    return st.session_state.active_page


def step_heading(title: str, step: str = None):
    if step:
        st.markdown(f'<span class="step-label">Step {step}</span>', unsafe_allow_html=True)
    st.markdown(f"#### {title}")


def wizard_steps(steps: list[dict], current_step: int, note: str | None = None):
    """Render a horizontal step rail.

    Each step dict: {"label": str, "is_move": bool (optional)}.
    current_step is 1-based. Steps before current are done; current is active.
    """
    note_html = ""
    if note:
        note_html = f'<p class="wizard-rail-note">{note}</p>'

    items = []
    for index, step in enumerate(steps, start=1):
        classes = ["wizard-step"]
        if index < current_step:
            classes.append("done")
        elif index == current_step:
            classes.append("active")
        if step.get("is_move"):
            classes.append("move")

        tag = (
            '<span class="wizard-tag">moves data</span>'
            if step.get("is_move")
            else ""
        )
        bullet = "✓" if index < current_step else str(index)
        items.append(
            f'<li class="{" ".join(classes)}">'
            f'<span class="wizard-bullet">{bullet}</span>'
            f'<span class="wizard-label">{step["label"]}</span>'
            f"{tag}"
            f"</li>"
        )

    st.markdown(
        f'<div class="wizard-rail">{note_html}'
        f'<ol class="wizard-steps">{"".join(items)}</ol></div>',
        unsafe_allow_html=True,
    )


def account_move_current_step() -> int:
    """1-based wizard step for Account Move, based on session gates."""
    if not st.session_state.get("am_accounts_confirmed"):
        return 1
    if st.session_state.get("am_mode") == "per_location":
        if not st.session_state.get("am_location_id"):
            return 2
        if not st.session_state.get("am_confirmed"):
            return 3
        if not st.session_state.get("am_backup_downloaded"):
            return 4
        return 5
    # rest_of_account — mode is chosen; highlight load/confirm until backup/run.
    if not st.session_state.get("am_rest_loaded"):
        return 3
    if not st.session_state.get("am_backup_downloaded"):
        if not st.session_state.get("am_backup_bytes"):
            return 3
        return 4
    return 5


ACCOUNT_MOVE_WIZARD_STEPS = [
    {"label": "Accounts"},
    {"label": "Mode"},
    {"label": "Confirm"},
    {"label": "Backup"},
    {"label": "Run move", "is_move": True},
]


QUEST_MIGRATE_WIZARD_STEPS = [
    {"label": "Confirm"},
    {"label": "Backup"},
    {"label": "Run migrate", "is_move": True},
]


def quest_migrate_current_step() -> int:
    if not st.session_state.get("location_confirmed"):
        return 1
    if not st.session_state.get("backup_downloaded"):
        return 2
    return 3


def location_card(name: str, location_id: str):
    st.markdown(
        f"""
        <div class="location-card">
            <p class="name">{name}</p>
            <p class="id">{location_id}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def account_move_match_summary(ready_count: int, already_moved_count: int, unmatched_count: int):
    total = ready_count + already_moved_count + unmatched_count
    all_matched = unmatched_count == 0 and total > 0

    if all_matched:
        if already_moved_count == 0:
            detail = f"All {ready_count} location(s) matched and ready to move."
        elif ready_count == 0:
            detail = f"All {already_moved_count} location(s) are already moved or skipped."
        else:
            detail = (
                f"{ready_count} ready to move · {already_moved_count} already moved/skipped. "
                "Nothing unmatched."
            )
        st.markdown(
            f"""
            <div class="match-all-good">
                <strong>All locations matched</strong>
                <span>{detail}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        chips = [f'<span class="match-chip ready">Ready · {ready_count}</span>']
        if already_moved_count:
            chips.append(
                f'<span class="match-chip muted">Already moved · {already_moved_count}</span>'
            )
        st.markdown(
            f'<div class="match-summary">{"".join(chips)}</div>',
            unsafe_allow_html=True,
        )
        return

    chips = [f'<span class="match-chip ready">Ready · {ready_count}</span>']
    if already_moved_count:
        chips.append(
            f'<span class="match-chip muted">Already moved · {already_moved_count}</span>'
        )
    chips.append(
        f'<span class="match-chip warn">Unmatched · {unmatched_count}</span>'
    )
    st.markdown(
        f'<div class="match-summary">{"".join(chips)}</div>',
        unsafe_allow_html=True,
    )
    st.warning(
        f"{unmatched_count} location(s) could not be matched by name and will be skipped."
    )


def format_box():
    st.markdown(
        """
        <div class="format-box">
            <strong>Expected format:</strong> a <code>.zip</code> backup created by Quest migrate.<br><br>
            <pre>manifest.json
location.json
channelLinks/
  {channelLinkId}.json
  ...</pre>
            Restores the full location and all channel links from the snapshot.
        </div>
        """,
        unsafe_allow_html=True,
    )


def account_move_format_box():
    st.markdown(
        """
        <div class="format-box">
            <strong>Expected format:</strong> a <code>.zip</code> backup created by Account move.<br><br>
            <pre>manifest.json
moves/{originalLocationId}/
  original_location.json
  destination_location.json
  channelLinks/{channelLinkId}.json
  ...</pre>
            Moves channel links back to the original account/location and restores both location snapshots.
        </div>
        """,
        unsafe_allow_html=True,
    )


def get_config_value(key: str) -> str:
    value = os.getenv(key, "")
    try:
        return st.secrets[key]
    except Exception:
        return value


def render_password_gate():
    if st.session_state.get("authenticated"):
        return

    expected_password = get_config_value("APP_PASSWORD")
    if not expected_password:
        st.error("App is not configured. Set APP_PASSWORD in secrets or environment.")
        st.stop()

    st.markdown(
        """
        <div class="app-header">
            <h1>Noah's Migration Tools</h1>
            <p>Enter the password to access this tool.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.container(border=True):
        password = st.text_input("Password", type="password", key="gate_password")
        if st.button("Continue", type="primary", use_container_width=True):
            if hmac.compare_digest(password, expected_password):
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Incorrect password.")

    st.stop()


def load_credentials():
    client_id = get_config_value("CLIENT_ID")
    client_secret = get_config_value("CLIENT_SECRET")
    allowed_account_id = get_config_value("ALLOWED_ACCOUNT_ID")

    if not client_id or not client_secret or not allowed_account_id:
        st.error(
            "App is not configured. Set CLIENT_ID, CLIENT_SECRET, and "
            "ALLOWED_ACCOUNT_ID in secrets or environment."
        )
        st.stop()

    set_credentials(client_id, client_secret)
    return allowed_account_id.strip()


def show_results(results: list[dict]):
    if not results:
        return

    with st.container(border=True):
        st.markdown("**Results**")

        rows = []
        failures = []
        for result in results:
            if result.get("type") == "warning":
                rows.append(
                    {
                        "Status": "🟡",
                        "Type": "warning",
                        "Name": "",
                        "Detail": result.get("message", ""),
                        "HTTP": "",
                    }
                )
                continue

            ok = result.get("ok")
            rows.append(
                {
                    "Status": "🟢" if ok else "🔴",
                    "Type": result.get("type") or "",
                    "Name": result.get("name") or result.get("id") or "",
                    "Detail": result.get("action")
                    or f"{result.get('type')} {result.get('name') or result.get('id')}",
                    "HTTP": result.get("status", ""),
                }
            )
            if not ok:
                failures.append(result)

        ok_count = sum(1 for row in rows if row["Status"] == "🟢")
        fail_count = sum(1 for row in rows if row["Status"] == "🔴")
        warn_count = sum(1 for row in rows if row["Status"] == "🟡")

        if fail_count == 0 and warn_count == 0 and ok_count:
            st.markdown(
                f'<div class="match-all-good"><strong>All {ok_count} step(s) succeeded</strong></div>',
                unsafe_allow_html=True,
            )
        elif fail_count == 0 and ok_count:
            st.success(f"{ok_count} succeeded · {warn_count} skipped/info")
        elif fail_count:
            st.error(f"{fail_count} failed · {ok_count} succeeded · {warn_count} skipped/info")

        st.dataframe(rows, use_container_width=True, hide_index=True)

        for failure in failures:
            with st.expander(
                f"Error details · {failure.get('name') or failure.get('id')}",
                expanded=False,
            ):
                if failure.get("response"):
                    st.json(failure["response"])
                else:
                    st.write(failure)


def summarize_account_move_locations(
    results: list[dict],
    success_label: str = "Fully migrated",
) -> list[dict]:
    """Collapse step results into one row per original location."""
    by_location: dict[str, dict] = {}

    for result in results:
        location_id = result.get("original_location_id") or result.get("id") or "unknown"
        if location_id not in by_location:
            by_location[location_id] = {
                "original_location_id": location_id,
                "original_location_name": result.get("original_location_name")
                or result.get("name")
                or location_id,
                "destination_location_id": result.get("destination_location_id"),
                "destination_location_name": result.get("destination_location_name"),
                "channel_ok": 0,
                "channel_fail": 0,
                "channel_total": 0,
                "user_ok": 0,
                "user_fail": 0,
                "user_total": 0,
                "snooze_ok": 0,
                "snooze_fail": 0,
                "snooze_total": 0,
                "snooze_plus": 0,
                "busy_ok": 0,
                "busy_fail": 0,
                "busy_total": 0,
                "logout_ok": 0,
                "logout_fail": 0,
                "logout_total": 0,
                "location_ok": True,
                "had_location_step": False,
                "skipped": False,
                "channel_rows": [],
                "user_rows": [],
                "snooze_rows": [],
                "busy_rows": [],
                "logout_rows": [],
                "failures": [],
            }

        bucket = by_location[location_id]
        if result.get("destination_location_name"):
            bucket["destination_location_name"] = result["destination_location_name"]
        if result.get("destination_location_id"):
            bucket["destination_location_id"] = result["destination_location_id"]
        if result.get("original_location_name"):
            bucket["original_location_name"] = result["original_location_name"]

        if result.get("type") == "warning":
            if (
                bucket["channel_total"] == 0
                and bucket["user_total"] == 0
                and bucket["busy_total"] == 0
                and bucket["logout_total"] == 0
                and bucket["snooze_total"] == 0
                and not bucket["had_location_step"]
            ):
                bucket["skipped"] = True
            continue

        if result.get("type") == "busy":
            bucket["skipped"] = False
            bucket["busy_total"] += 1
            bucket["busy_rows"].append(
                {
                    "Status": "🟢" if result.get("ok") else "🔴",
                    "Site": result.get("name") or result.get("id") or "",
                    "Detail": result.get("action") or "",
                    "HTTP": result.get("status", ""),
                }
            )
            if result.get("ok"):
                bucket["busy_ok"] += 1
            else:
                bucket["busy_fail"] += 1
                bucket["failures"].append(result)
            continue

        if result.get("type") == "logout":
            bucket["skipped"] = False
            bucket["logout_total"] += 1
            bucket["logout_rows"].append(
                {
                    "Status": "🟢" if result.get("ok") else "🔴",
                    "User": result.get("name") or result.get("id") or "",
                    "Detail": result.get("action") or "",
                    "HTTP": result.get("status", ""),
                }
            )
            if result.get("ok"):
                bucket["logout_ok"] += 1
            else:
                bucket["logout_fail"] += 1
                bucket["failures"].append(result)
            continue

        if result.get("type") == "channel_link":
            bucket["skipped"] = False
            bucket["channel_total"] += 1
            bucket["channel_rows"].append(
                {
                    "Status": "🟢" if result.get("ok") else "🔴",
                    "Channel": result.get("name") or result.get("id") or "",
                    "Detail": result.get("action") or "",
                    "HTTP": result.get("status", ""),
                }
            )
            if result.get("ok"):
                bucket["channel_ok"] += 1
            else:
                bucket["channel_fail"] += 1
                bucket["failures"].append(result)
            continue

        if result.get("type") == "user":
            bucket["skipped"] = False
            bucket["user_total"] += 1
            bucket["user_rows"].append(
                {
                    "Status": "🟢" if result.get("ok") else "🔴",
                    "User": result.get("name") or result.get("id") or "",
                    "Detail": result.get("action") or "",
                    "HTTP": result.get("status", ""),
                }
            )
            if result.get("ok"):
                bucket["user_ok"] += 1
            else:
                bucket["user_fail"] += 1
                bucket["failures"].append(result)
            continue

        if result.get("type") == "snooze":
            bucket["skipped"] = False
            bucket["snooze_total"] += 1
            bucket["snooze_plus"] += int(result.get("plu_count") or 0)
            bucket["snooze_rows"].append(
                {
                    "Status": "🟢" if result.get("ok") else "🔴",
                    "Detail": result.get("action") or "",
                    "PLUs": result.get("plu_count", ""),
                    "HTTP": result.get("status", ""),
                }
            )
            if result.get("ok"):
                bucket["snooze_ok"] += 1
            else:
                bucket["snooze_fail"] += 1
                bucket["failures"].append(result)
            continue

        if result.get("type") == "location":
            bucket["had_location_step"] = True
            bucket["skipped"] = False
            if not result.get("ok"):
                bucket["location_ok"] = False
                bucket["failures"].append(result)

    overview = []
    for bucket in by_location.values():
        if bucket["skipped"] and not bucket["had_location_step"]:
            status, outcome = "🟡", "Skipped"
        elif (
            bucket["location_ok"]
            and bucket["channel_fail"] == 0
            and bucket["user_fail"] == 0
            and bucket["snooze_fail"] == 0
            and bucket["busy_fail"] == 0
            and bucket["logout_fail"] == 0
        ):
            status, outcome = "🟢", success_label
        elif (
            bucket["channel_ok"] > 0
            or bucket["user_ok"] > 0
            or bucket["snooze_ok"] > 0
            or bucket["busy_ok"] > 0
            or bucket["logout_ok"] > 0
        ):
            status, outcome = "🟠", "Partial"
        else:
            status, outcome = "🔴", "Failed"

        overview.append(
            {
                "Status": status,
                "Location": bucket["original_location_name"],
                "Destination": bucket["destination_location_name"] or "",
                "Channels": (
                    f"{bucket['channel_ok']}/{bucket['channel_total']}"
                    if bucket["channel_total"]
                    else "—"
                ),
                "Users": (
                    f"{bucket['user_ok']}/{bucket['user_total']}"
                    if bucket["user_total"]
                    else "—"
                ),
                "Prep": (
                    f"busy {bucket['busy_ok']}/{bucket['busy_total']}"
                    f" · out {bucket['logout_ok']}/{bucket['logout_total']}"
                    if bucket["busy_total"] or bucket["logout_total"]
                    else "—"
                ),
                "Snoozes": (
                    str(bucket["snooze_plus"])
                    if bucket["snooze_total"]
                    else "—"
                ),
                "Outcome": outcome,
                "_bucket": bucket,
            }
        )
    return overview


def show_account_move_results(
    results: list[dict],
    title: str = "Location overview",
    success_label: str = "Fully migrated",
):
    if not results:
        return

    overview = summarize_account_move_locations(results, success_label=success_label)
    fully = sum(1 for row in overview if row["Outcome"] == success_label)
    partial = sum(1 for row in overview if row["Outcome"] == "Partial")
    failed = sum(1 for row in overview if row["Outcome"] == "Failed")
    skipped = sum(1 for row in overview if row["Outcome"] == "Skipped")

    with st.container(border=True):
        st.markdown(f"**{title}**")

        if failed == 0 and partial == 0 and fully:
            detail = f"{fully} location(s) {success_label.lower()}"
            if skipped:
                detail += f" · {skipped} skipped"
            st.markdown(
                f'<div class="match-all-good"><strong>Complete</strong>'
                f"<span>{detail}</span></div>",
                unsafe_allow_html=True,
            )
        elif failed or partial:
            st.error(
                f"{fully} {success_label.lower()} · {partial} partial · "
                f"{failed} failed · {skipped} skipped"
            )
        else:
            st.info(f"{skipped} location(s) skipped · nothing changed")

        st.dataframe(
            [
                {
                    "Status": row["Status"],
                    "Location": row["Location"],
                    "Destination": row["Destination"],
                    "Channels": row["Channels"],
                    "Users": row["Users"],
                    "Prep": row["Prep"],
                    "Snoozes": row["Snoozes"],
                    "Outcome": row["Outcome"],
                }
                for row in overview
            ],
            use_container_width=True,
            hide_index=True,
        )

        detail_rows = [
            row
            for row in overview
            if (
                row["_bucket"]["channel_rows"]
                or row["_bucket"]["user_rows"]
                or row["_bucket"]["snooze_rows"]
                or row["_bucket"]["busy_rows"]
                or row["_bucket"]["logout_rows"]
            )
        ]
        if detail_rows:
            with st.expander("Per-channel / user / prep / snooze details", expanded=False):
                for row in detail_rows:
                    st.markdown(f"**{row['Location']}**")
                    if row["_bucket"]["busy_rows"]:
                        st.caption("Busy mode")
                        st.dataframe(
                            row["_bucket"]["busy_rows"],
                            use_container_width=True,
                            hide_index=True,
                        )
                    if row["_bucket"]["logout_rows"]:
                        st.caption("Picker logout")
                        st.dataframe(
                            row["_bucket"]["logout_rows"],
                            use_container_width=True,
                            hide_index=True,
                        )
                    if row["_bucket"]["channel_rows"]:
                        st.caption("Channel links")
                        st.dataframe(
                            row["_bucket"]["channel_rows"],
                            use_container_width=True,
                            hide_index=True,
                        )
                    if row["_bucket"]["user_rows"]:
                        st.caption("Users")
                        st.dataframe(
                            row["_bucket"]["user_rows"],
                            use_container_width=True,
                            hide_index=True,
                        )
                    if row["_bucket"]["snooze_rows"]:
                        st.caption("Snoozes")
                        st.dataframe(
                            row["_bucket"]["snooze_rows"],
                            use_container_width=True,
                            hide_index=True,
                        )

        failures = [
            failure
            for row in overview
            for failure in row["_bucket"]["failures"]
        ]
        for failure in failures:
            with st.expander(
                f"Error details · {failure.get('name') or failure.get('id')}",
                expanded=False,
            ):
                if failure.get("response"):
                    st.json(failure["response"])
                else:
                    st.write(failure)


def init_migrate_session_state():
    defaults = {
        "location_id_input": "",
        "location_id": None,
        "location_name": None,
        "location_confirmed": False,
        "backup_bytes": None,
        "backup_filename": None,
        "backup_downloaded": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def reset_from_location_change():
    st.session_state.location_id = None
    st.session_state.location_name = None
    st.session_state.location_confirmed = False
    st.session_state.backup_bytes = None
    st.session_state.backup_filename = None
    st.session_state.backup_downloaded = False


def init_account_move_session_state():
    defaults = {
        "am_mode": "per_location",
        "am_old_account_id": "",
        "am_new_account_id": "",
        "am_role_group_id": "",
        "am_role_name": None,
        "am_roles": None,
        "am_roles_account_id": None,
        "am_accounts_confirmed": False,
        "am_location_id_input": "",
        "am_location_id": None,
        "am_location_name": None,
        "am_match_name": None,
        "am_channel_link_count": 0,
        "am_retained_count": 0,
        "am_user_count": 0,
        "am_destination_id": None,
        "am_destination_name": None,
        "am_status": None,
        "am_snapshot": None,
        "am_confirmed": False,
        "am_backup_bytes": None,
        "am_backup_filename": None,
        "am_backup_summary": None,
        "am_backup_downloaded": False,
        "am_rest_rows": None,
        "am_rest_loaded": False,
        "am_rest_snapshots": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def init_account_revert_session_state():
    defaults = {
        "ar_old_account_id": "",
        "ar_new_account_id": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def reset_account_move_per_location():
    st.session_state.am_location_id = None
    st.session_state.am_location_name = None
    st.session_state.am_match_name = None
    st.session_state.am_channel_link_count = 0
    st.session_state.am_retained_count = 0
    st.session_state.am_user_count = 0
    st.session_state.am_destination_id = None
    st.session_state.am_destination_name = None
    st.session_state.am_status = None
    st.session_state.am_snapshot = None
    st.session_state.am_confirmed = False
    st.session_state.am_backup_bytes = None
    st.session_state.am_backup_filename = None
    st.session_state.am_backup_summary = None
    st.session_state.am_backup_downloaded = False


def reset_account_move_rest():
    st.session_state.am_rest_rows = None
    st.session_state.am_rest_loaded = False
    st.session_state.am_rest_snapshots = None
    st.session_state.am_backup_bytes = None
    st.session_state.am_backup_filename = None
    st.session_state.am_backup_summary = None
    st.session_state.am_backup_downloaded = False


def reset_account_move_from_accounts_change():
    st.session_state.am_accounts_confirmed = False
    st.session_state.am_location_id_input = ""
    st.session_state.am_roles = None
    st.session_state.am_roles_account_id = None
    st.session_state.am_role_group_id = ""
    st.session_state.am_role_name = None
    reset_account_move_per_location()
    reset_account_move_rest()
