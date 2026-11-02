"""Local human review app. Run with python -m streamlit run app.py."""
from contextlib import closing
import json
import os
from pathlib import Path

from filelock import Timeout
import streamlit as st

from bellhaven.crm import CRM
from bellhaven.review import READ_ONLY_KINDS, approve, prepare_resolution, reject
from bellhaven.source import DEFAULT_BASE, get, parse_location
from bellhaven.store import connect

st.set_page_config(page_title="Bellhaven | Ownership Review", page_icon="🏡", layout="wide")
ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("BELLHAVEN_DATA_DIR", str(ROOT / "data"))).resolve()
DATABASE = DATA / "review.sqlite3"
BASE = os.environ.get("BELLHAVEN_BASE_URL", DEFAULT_BASE).rstrip("/")


def read_rows():
    with closing(connect(DATABASE)) as db:
        return [dict(row) for row in db.execute("SELECT * FROM proposals ORDER BY first_seen,kind,proposal_id")]


def title(p):
    return p["location"]["name"] if p["location"] else p["accounts"][0]["name"]


def result_links(journal, token):
    for field in ["result_account_id", "old_account_id", "created_account_id"]:
        account_id = journal.get(field)
        if account_id:
            # Token appears only in the explicit sandbox browser link required by
            # the assessment, never in a persisted file or log.
            if token:
                st.link_button(f"Open {field.replace('_', ' ')} in CRM",
                               f"{BASE}/crm/{token}/accounts/{account_id}")
            st.caption(f"{field}: {account_id}")


st.title("Bellhaven ownership review")
st.caption("Review the website evidence, inspect the proposed change, then decide.")
if not DATABASE.exists():
    st.info("No queue yet. Run the pipeline from this project folder first.")
    st.code('.\\.venv\\Scripts\\python.exe -m bellhaven.pipeline --replay examples/stage2_snapshot', language="powershell")
    st.stop()

with st.sidebar:
    st.header("Review session")
    token = st.text_input("Personal CRM token", value=os.environ.get("BELLHAVEN_API_TOKEN", ""),
                          type="password", help="Kept in this running session only.")
    st.caption("Start screen recording before your first live approval for the assessment demo.")
    if st.button("Refresh queue"):
        st.rerun()

if "flash" in st.session_state:
    st.success(st.session_state.pop("flash"))

rows = read_rows()
counts = {state: sum(row["state"] == state for row in rows)
          for state in ["pending", "applied", "rejected", "failed", "applying", "approved"]}
columns = st.columns(4)
for column, state in zip(columns, ["pending", "applied", "rejected", "failed"]):
    column.metric(state.capitalize(), counts[state])
st.caption("Applied includes acknowledged review-only findings and prepared match resolutions; see history for the actual outcome.")
queue_tab, history_tab = st.tabs(["Review queue", "Decisions & audit"])

with queue_tab:
    pending = [r for r in rows if r["state"] in {"pending", "approved", "failed", "applying"}]
    kinds = ["All"] + sorted({r["kind"] for r in pending})
    kind_filter = st.selectbox("Finding type", kinds)
    pending = [r for r in pending if kind_filter == "All" or r["kind"] == kind_filter]
    if not pending:
        st.info("No items in this view. Run the live pipeline after completing your decisions to check the CRM end state.")
    else:
        # Parent/name fixes before duplicate retirement makes dependent reviews
        # easier to follow. Failed executions remain available for recovery.
        order = {"chow": 0, "reparent": 1, "update": 2, "create": 3, "duplicate": 4}
        pending.sort(key=lambda r: (order.get(r["kind"], 5), title(json.loads(r["payload_json"]))))
        options = {r["proposal_id"]: r for r in pending}
        selected = st.selectbox("Choose proposal", list(options), format_func=lambda id:
            f"{title(json.loads(options[id]['payload_json']))} · {options[id]['kind']} · {options[id]['state']}")
        row = options[selected]
        p = json.loads(row["payload_json"])
        journal = json.loads(row["execution_json"] or "{}")
        st.subheader(title(p))
        st.write(p["reason"])
        st.caption(f"Evidence confidence: {p['confidence']} · State: {row['state']}")
        for warning in p.get("warnings", []):
            st.warning(warning)
        if journal.get("last_error"):
            st.error(journal["last_error"])
            st.caption("Recovery checks existing results first. An uncertain create is never automatically repeated.")
            result_links(journal, token)
        left, right = st.columns(2)
        with left:
            st.markdown("**Website evidence**")
            if p["location"]:
                loc = p["location"]
                st.write(f"{loc['street']}, {loc['city']}, {loc['state']} {loc['zip']}")
                st.write("Care: " + ", ".join(loc["care_offerings"]))
                st.write("Phone: " + loc.get("phone", ""))
                if loc.get("administrator"):
                    st.write("Administrator: " + loc["administrator"])
                st.link_button("Open source page", loc["source_url"])
            else:
                st.write("Facility was absent from the complete crawl. This does not establish closure or a new owner.")
                st.link_button("Open community directory", BASE + "/communities")
        with right:
            st.markdown("**Proposed change**")
            changes = p["changes"]
            if p["kind"] in {"create", "chow"}:
                st.json(changes["create"])
                if p["kind"] == "chow":
                    old = p["accounts"][0]
                    st.warning(f"Preserve old account: revenue ${old['lifetime_revenue']:,.2f}; outstanding AR ${old['outstanding_ar']:,.2f}.")
                    st.write("Create the new account, then set only chow_current_account on the old account to the new ID.")
            elif changes:
                before = p["accounts"][0]
                st.table([{"Field": k, "Before": str(before.get(k, "")), "After": str(v)}
                          for k, v in changes.items() if k != "account_id"])
            else:
                st.info("Review-only finding. No CRM field update is proposed.")

        if p["accounts"]:
            with st.expander("CRM records and matching evidence", expanded=True):
                st.dataframe([{k: a.get(k, "") for k in ["account_id", "name", "parent_name", "billing_street", "billing_city", "billing_state", "billing_zip", "phone", "care_type", "status", "lifetime_revenue", "outstanding_ar"]}
                              for a in p["accounts"]], hide_index=True, width="stretch")
                if p["evidence"]:
                    st.dataframe(p["evidence"], hide_index=True, width="stretch")
                for account in p["accounts"]:
                    if token:
                        st.link_button("CRM: " + account["name"], f"{BASE}/crm/{token}/accounts/{account['account_id']}")
        reason = st.text_area("Decision reason", key=f"reason-{selected}",
                              help="Required for rejection, review-only acknowledgment, and ambiguous-match resolution.")
        if p["kind"] == "ambiguous_match":
            st.info("Investigate these candidates, then prepare a survivor selection. Preparing creates new proposals; it does not change the CRM.")
            if st.button("Load current website and CRM contacts", disabled=not token):
                try:
                    client = CRM(token, BASE)
                    fresh = parse_location(get(p["location"]["source_url"]).text, p["location"]["source_url"])
                    st.session_state[f"investigation-{selected}"] = {
                        "website": fresh, "contacts": {a["account_id"]: client.contacts(a["account_id"]) for a in p["accounts"]}}
                except Exception as error:
                    st.error(str(error))
            investigation = st.session_state.get(f"investigation-{selected}")
            if investigation:
                st.json(investigation)
            choice = st.selectbox("Proposed survivor", [a["account_id"] for a in p["accounts"]],
                format_func=lambda id: next(a["name"] for a in p["accounts"] if a["account_id"] == id) + " · " + id,
                index=None, placeholder="Select only after reviewing evidence")
            if st.button("Prepare survivor and duplicate proposals", disabled=not token or not choice or not reason.strip()):
                try:
                    children = prepare_resolution(DATABASE, selected, choice, reason, CRM(token, BASE))
                    st.session_state["flash"] = f"Prepared {len(children)} proposals. Review and approve them separately. No CRM writes occurred."
                    st.rerun()
                except Exception as error:
                    st.error(str(error))

        if p["kind"] != "ambiguous_match":
            acknowledgment = p["kind"] in READ_ONLY_KINDS
            confirmed = st.checkbox("I reviewed the evidence and approve this action", key=f"confirm-{selected}")
            label = "Acknowledge — preserve CRM fields" if acknowledgment else "Approve and apply to CRM" if row["state"] == "pending" else "Resume approved change"
            if st.button(label, type="primary", disabled=not confirmed or not token or (acknowledgment and not reason.strip())):
                try:
                    with st.spinner("Checking fresh evidence and applying the approved action..."):
                        outcome = approve(DATABASE, selected, CRM(token, BASE), reason)
                    st.session_state["last_outcome"] = outcome
                    st.session_state["flash"] = outcome.get("result", "Decision recorded")
                    st.rerun()
                except Timeout:
                    st.error("Another review or pipeline run holds the writer lock. Refresh after it finishes.")
                except Exception as error:
                    st.error(str(error))
        if st.button("Reject proposal", disabled=row["state"] != "pending" or not reason.strip()):
            try:
                reject(DATABASE, selected, reason)
                st.session_state["flash"] = "Rejected and remembered. No CRM writes occurred."
                st.rerun()
            except Exception as error:
                st.error(str(error))
    if st.session_state.get("last_outcome"):
        st.markdown("**Last verified result**")
        result_links(st.session_state["last_outcome"], token)

with history_tab:
    decided = [r for r in rows if r["state"] != "pending"]
    st.dataframe([{"Facility": title(json.loads(r["payload_json"])), "Kind": r["kind"],
                   "State": r["state"], "Decision": r["decision_note"] or "", "At": r["decision_at"] or ""}
                  for r in decided], hide_index=True, width="stretch")
    with closing(connect(DATABASE)) as db:
        events = [dict(r) for r in db.execute("SELECT * FROM audit ORDER BY event_id DESC")]
    st.download_button("Download audit trail", json.dumps(events, indent=2), "bellhaven-audit.json", "application/json")
    if events:
        st.dataframe(events, hide_index=True, width="stretch")
    st.download_button("Download decision history", json.dumps(decided, indent=2), "bellhaven-decisions.json", "application/json")
