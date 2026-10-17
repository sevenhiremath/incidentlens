import uuid
from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st

from ui.api import APIError, call, page

st.set_page_config(page_title="IncidentLens", page_icon="◉", layout="wide")


def request(method, path, **kwargs):
    return call(method, path, token=st.session_state.get("token"), **kwargs)


def short_time(value):
    return datetime.fromisoformat(value).strftime("%d %b %Y · %H:%M:%S UTC") if value else "—"


def service_label(service):
    return f"{service['name']} / {service['environment']}"


def show_login():
    st.title("IncidentLens")
    st.markdown("### Understand the outage. Keep the evidence.")
    st.write("Track service failures, review the timeline, and write down what fixed the issue.")
    st.caption("Version 0.1 · Python learning project · Reports use templates; AI is planned.")
    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in", type="primary")
    if submitted:
        result = call("POST", "auth/login/", json={"username": username, "password": password})
        st.session_state.token = result["token"]
        st.session_state.username = result["username"]
        st.rerun()
    st.info(
        "Create your local account with `python manage.py createuser`. No account is preloaded."
    )


def show_service_table(services):
    if not services:
        st.info("Register a service on the Services page to start monitoring.")
        return
    st.dataframe(
        [
            {
                "Service": s["name"],
                "Environment": s["environment"],
                "Health": s["health"].upper(),
                "Last check": short_time(s["last_checked_at"]),
                "Response (ms)": s["last_latency_ms"],
            }
            for s in services
        ],
        hide_index=True,
        use_container_width=True,
    )


def show_dashboard(services):
    st.title("Service overview")
    st.caption("Recorded health checks and incidents · All timestamps are UTC")
    recent = page("incidents/", st.session_state.token)
    active = page("incidents/", st.session_state.token, params={"status": "open"})
    columns = st.columns(3)
    columns[0].metric("Registered services", st.session_state.service_count)
    columns[1].metric("Open incidents", active["count"])
    columns[2].metric("Recorded incidents", recent["count"])
    st.subheader("Service health")
    show_service_table(services)
    st.subheader("Recent incidents")
    show_incident_table(recent["results"])
    if services:
        selected = st.selectbox("Response history", services, format_func=service_label)
        history = page(f"services/{selected['id']}/history/", st.session_state.token)["results"]
        checks = [
            {"Time (UTC)": e["occurred_at"], "Response time (ms)": e["latency_ms"]}
            for e in reversed(history)
            if e["kind"] == "check"
        ]
        if checks:
            frame = pd.DataFrame(checks)
            frame["Time (UTC)"] = pd.to_datetime(frame["Time (UTC)"], utc=True)
            frame["Checked at (UTC)"] = frame["Time (UTC)"].dt.strftime("%Y-%m-%d %H:%M:%S UTC")
            chart = (
                alt.Chart(frame)
                .mark_line(point=True)
                .encode(
                    x=alt.X("Time (UTC):T", scale=alt.Scale(type="utc")),
                    y=alt.Y("Response time (ms):Q"),
                    tooltip=["Checked at (UTC):N", "Response time (ms):Q"],
                )
            )
            st.altair_chart(chart, width="stretch")
        else:
            st.caption("No health checks yet. Start the separate monitor process.")
    st.caption("Refresh to fetch current data. A missing monitor becomes STALE after 90 seconds.")


def show_services(services):
    st.title("Services")
    st.write("Register a health endpoint, then run the monitor independently of this dashboard.")
    with st.form("register_service", clear_on_submit=True):
        name = st.text_input("Service name", placeholder="Checkout API", max_chars=80)
        environment = st.text_input("Environment", value="development", max_chars=30)
        health_url = st.text_input("Health URL", placeholder="http://127.0.0.1:5055/health")
        submitted = st.form_submit_button("Register service", type="primary")
    if submitted:
        request(
            "POST",
            "services/",
            json={
                "name": name,
                "environment": environment,
                "health_url": health_url,
            },
        )
        st.rerun()
    st.caption(
        "Hosts are limited by MONITOR_ALLOWED_HOSTS. Register a new service to change its URL."
    )
    show_service_table(services)
    if not services:
        return
    selected = st.selectbox("Manage a service", services, format_func=service_label)
    st.code(str(selected["id"]), language=None)
    with st.form("service_settings"):
        enabled = st.checkbox("Monitoring enabled", value=selected["enabled"])
        if st.form_submit_button("Save settings"):
            request("PATCH", f"services/{selected['id']}/", json={"enabled": enabled})
            st.rerun()
    if st.button("Create / rotate event key"):
        result = request("POST", f"services/{selected['id']}/key/")
        st.warning("Copy the key now. Rotating it invalidates the previous key.")
        st.code(result["service_key"], language=None)
        st.caption("Use X-Service-Key when posting error events. Do not put this key in Git.")


def show_incident_table(incidents):
    if not incidents:
        st.info("No incidents match these filters.")
        return
    st.dataframe(
        [
            {
                "Service": i["service_name"],
                "Status": i["status"].upper(),
                "Detected": short_time(i["detected_at"]),
                "Events": i["event_count"],
                "Observed window (s)": i["duration_seconds"],
            }
            for i in incidents
        ],
        hide_index=True,
        use_container_width=True,
    )


def report_editor(incident_id):
    reports = page(f"incidents/{incident_id}/reports/", st.session_state.token)["results"]
    current = reports[0] if reports else None
    st.caption("Drafts are assembled from recorded events. AI generation is not implemented yet.")
    if st.button("Build evidence draft"):
        request(
            "POST",
            f"incidents/{incident_id}/reports/",
            json={
                "request_id": str(uuid.uuid4()),
                "expected_revision": current["number"] if current else 0,
            },
        )
        st.rerun()
    if current:
        st.caption(
            f"Revision {current['number']} · {current['source']} · "
            f"{short_time(current['created_at'])}"
        )
        with st.form(f"report_{incident_id}_{current['number']}"):
            content = st.text_area("Report (Markdown)", value=current["content"], height=420)
            submitted = st.form_submit_button("Save new revision", type="primary")
        if submitted:
            request(
                "POST",
                f"incidents/{incident_id}/reports/",
                json={
                    "request_id": str(uuid.uuid4()),
                    "expected_revision": current["number"],
                    "content": content,
                },
            )
            st.rerun()
        st.download_button(
            "Download latest report",
            current["content"],
            file_name=f"incident-{incident_id}-v{current['number']}.md",
            mime="text/markdown",
        )
        with st.expander("Earlier revisions"):
            for report in reports[1:]:
                st.download_button(
                    f"Revision {report['number']} ({report['source']})",
                    report["content"],
                    file_name=f"incident-{incident_id}-v{report['number']}.md",
                    key=report["id"],
                )


def show_incidents(services):
    st.title("Incident workspace")
    columns = st.columns(3)
    selected_status = columns[0].selectbox("Status", ["all", "open", "recovered", "closed"])
    selected_service = columns[1].selectbox(
        "Service",
        [None, *services],
        format_func=lambda s: service_label(s) if s else "All services",
    )
    search = columns[2].text_input("Search service or confirmed cause")
    params = {"search": search}
    if selected_status != "all":
        params["status"] = selected_status
    if selected_service:
        params["service"] = selected_service["id"]
    page_number = st.number_input("Results page", min_value=1, value=1, step=1)
    params["page"] = page_number
    result = page("incidents/", st.session_state.token, params=params)
    incidents = result["results"]
    st.caption(f"{result['count']} incident(s) found · 25 per page")
    show_incident_table(incidents)
    if not incidents:
        return
    chosen = st.selectbox(
        "Open incident",
        incidents,
        format_func=lambda i: (
            f"{i['service_name']} · {short_time(i['detected_at'])} · {i['id'][:8]}"
        ),
    )
    detail = request("GET", f"incidents/{chosen['id']}/")
    st.divider()
    st.subheader(detail["service_name"])
    st.caption(
        f"{detail['status'].upper()} · First observed failure: {short_time(detail['started_at'])}"
    )
    timeline, investigation, report = st.tabs(["Timeline", "Investigation", "Report"])
    with timeline:
        event_page = st.number_input("Timeline page", min_value=1, value=1, step=1)
        events = page(
            f"incidents/{detail['id']}/events/",
            st.session_state.token,
            params={"page": event_page},
        )
        st.caption(f"{events['count']} linked events · Times show observations, not a proven cause")
        for event in events["results"]:
            label = "OK" if event["healthy"] else "FAIL"
            if event["kind"] == "error":
                label = "APP ERROR"
            with st.expander(f"{short_time(event['occurred_at'])} · {label}"):
                st.text(event["message"])
                st.caption(f"Evidence ID: {event['id']}")
                if event["metadata"]:
                    st.json(event["metadata"])
    with investigation:
        with st.form(f"investigation_{detail['id']}"):
            cause = st.text_area("Confirmed cause", value=detail["confirmed_cause"])
            resolution = st.text_area("What fixed it", value=detail["resolution"])
            if st.form_submit_button("Save investigation"):
                request(
                    "PATCH",
                    f"incidents/{detail['id']}/",
                    json={
                        "confirmed_cause": cause,
                        "resolution": resolution,
                    },
                )
                st.rerun()
        if detail["status"] == "recovered" and st.button("Mark reviewed and close"):
            request("PATCH", f"incidents/{detail['id']}/", json={"status": "closed"})
            st.rerun()
    with report:
        report_editor(detail["id"])


def main():
    if not st.session_state.get("token"):
        show_login()
        return
    with st.sidebar:
        st.title("IncidentLens")
        st.caption("Service incidents, with context.")
        st.write(f"Signed in as **{st.session_state.get('username', 'developer')}**")
        screen = st.radio("Workspace", ["Overview", "Services", "Incidents"])
        st.button("Refresh data")
        st.divider()
        st.caption("v0.1 · Template reports\n\nAI and task queues are planned.")
        if st.button("Log out"):
            try:
                request("POST", "auth/logout/")
            finally:
                st.session_state.clear()
            st.rerun()
    service_page = page("services/", st.session_state.token)
    services = service_page["results"]
    st.session_state.service_count = service_page["count"]
    if service_page["count"] > 25:
        # Small project, but service selection still needs all of the user's services.
        for number in range(2, (service_page["count"] + 24) // 25 + 1):
            services.extend(
                page("services/", st.session_state.token, params={"page": number})["results"]
            )
    {"Overview": show_dashboard, "Services": show_services, "Incidents": show_incidents}[screen](
        services
    )


try:
    main()
except APIError as exc:
    st.error(str(exc))
