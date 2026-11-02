"""Human decisions, fresh evidence checks, and recoverable approved writeback."""
from contextlib import closing
from datetime import datetime, timezone
import json

from filelock import FileLock

from .matching import (RELEVANT, account_payload, build_proposals, matching_signals,
                       normalize, proposal, protected_billing)
from .source import get, parse_location, scrape
from .store import audit, connect, load_proposal

SOURCE_FIELDS = ("name", "street", "city", "state", "zip", "care_offerings", "phone")
READ_ONLY_KINDS = {"billing_address_review", "duplicate_review"}


class StaleProposal(ValueError):
    pass


def writer_lock(path):
    return FileLock(str(path.resolve()) + ".writer.lock", timeout=0)


def verify_source(p, base):
    if p["location"]:
        fresh = parse_location(get(p["location"]["source_url"]).text, p["location"]["source_url"])
        if any(fresh.get(k) != p["location"].get(k) for k in SOURCE_FIELDS):
            raise StaleProposal("Website business facts changed. Run the pipeline and review the new proposal.")
    elif p["kind"] == "not_on_website":
        locations, _, _ = scrape(base)
        old = p["accounts"][0]
        if any((s["same_city"] and s["same_state"] and
                (s["same_street"] or s["same_phone"] or s["name_similarity"] >= 0.6))
               for s in (matching_signals(loc, old) for loc in locations)):
            raise StaleProposal("Facility now has website evidence; rerun reconciliation.")


def unchanged(actual, expected, allowed=None):
    allowed = allowed or {}
    differences = [key for key in RELEVANT
                   if actual.get(key) != expected.get(key)
                   and not (key in allowed and actual.get(key) == allowed[key])]
    if differences:
        raise StaleProposal("CRM changed since review: " + ", ".join(differences) + ". Refresh the pipeline before deciding.")


def record(db, identifier, state, journal, event, details=None):
    with db:
        db.execute("UPDATE proposals SET state=?, execution_json=? WHERE proposal_id=?",
                   (state, json.dumps(journal), identifier))
        audit(db, identifier, event, details)


def reject(path, identifier, reason):
    if not reason.strip():
        raise ValueError("Give a short reason for rejection")
    with writer_lock(path), closing(connect(path)) as db:
        row, _ = load_proposal(db, identifier)
        if row["state"] != "pending":
            raise ValueError("Only pending, unexecuted proposals may be rejected")
        with db:
            db.execute("UPDATE proposals SET state='rejected',decision_at=?,decision_note=? WHERE proposal_id=?",
                (datetime.now(timezone.utc).isoformat(), reason.strip(), identifier))
            audit(db, identifier, "rejected", {"reason": reason.strip()})


def creation(db, p, client, journal, payload):
    identifier = p["proposal_id"]
    marker = f"[bellhaven:{identifier}]"
    desired = dict(payload, note=f"{marker} Website evidence: {p['location']['source_url']}")
    inventory = client.accounts()
    recovered = [a for a in inventory if marker in a.get("note", "")]
    if len(recovered) > 1:
        raise ValueError("Multiple creation markers found; resolve manually before proceeding")
    if recovered:
        current = recovered[0]
        if any(current.get(k) != v for k, v in desired.items()):
            raise StaleProposal("Previously created account changed; inspect it before resuming")
        journal["created_account_id"] = current["account_id"]
        record(db, identifier, "applying", journal, "recovered_created_account",
               {"account_id": current["account_id"]})
        return current
    if journal.get("create_attempted"):
        raise ValueError("An earlier create may have been sent, but its marker is not visible. No second POST was sent. Inspect the CRM and audit history before manual recovery.")
    # Prevent creating over a newly added matching account since the snapshot.
    old_id = p["accounts"][0]["account_id"] if p["kind"] == "chow" else None
    for account in inventory:
        if account["name"].endswith("(Parent Account)"):
            continue
        if account["account_id"] == old_id or account.get("duplicate_of_account") or account.get("chow_current_account") or account["status"] == "Inactive":
            continue
        signals = matching_signals(p["location"], account)
        if signals["same_city"] and signals["same_state"] and (signals["same_street"] or
                (signals["same_phone"] and signals["name_similarity"] >= 0.6)):
            raise StaleProposal("A matching account now exists. Rerun the pipeline instead of creating another.")
    # Commit intent BEFORE network I/O so process interruption cannot erase it.
    journal["create_attempted"] = True
    record(db, identifier, "applying", journal, "create_started")
    created = client.create(desired)
    if not isinstance(created, dict) or not created.get("account_id"):
        raise ValueError("Create returned no account ID. Use recovery; do not send another POST.")
    journal["created_account_id"] = created["account_id"]
    record(db, identifier, "applying", journal, "created_account", {"account_id": created["account_id"]})
    current = client.account(created["account_id"])
    if any(current.get(k) != v for k, v in desired.items()):
        raise ValueError("Created account did not retain the approved values; inspect the CRM")
    return current


def approve(path, identifier, client, reason="", *, check_source=True):
    """Called only by explicit Approve/Resume UI actions, never by daily runs.

    check_source=False is for isolated unit tests only; the app always uses True.
    """
    with writer_lock(path), closing(connect(path)) as db:
        row, p = load_proposal(db, identifier)
        if row["state"] == "applied":
            return json.loads(row["execution_json"] or "{}")
        if row["state"] not in {"pending", "approved", "applying", "failed"}:
            raise ValueError("This proposal cannot be approved in its current state")
        if p["kind"] == "ambiguous_match":
            raise ValueError("Prepare and inspect an explicit match resolution first")
        if p["kind"] in READ_ONLY_KINDS and not reason.strip() and not row["decision_note"]:
            raise ValueError("Explain the review-only decision before acknowledging it")
        journal = json.loads(row["execution_json"] or "{}")
        if row["state"] == "pending":
            with db:
                db.execute("UPDATE proposals SET state='approved', decision_at=?,decision_note=? WHERE proposal_id=?",
                           (datetime.now(timezone.utc).isoformat(), reason.strip(), identifier))
                audit(db, identifier, "approved", {"reason": reason.strip()})
        try:
            if check_source:
                verify_source(p, client.base)
            kind, changes = p["kind"], p["changes"]
            record(db, identifier, "applying", journal, "execution_started")
            if kind in READ_ONLY_KINDS:
                journal["crm_writes"] = 0
                journal["result"] = "Reviewed; existing CRM fields preserved"
            elif kind in {"create", "chow"}:
                parent = client.account(changes["create"]["parent_id"])
                if parent["name"] != "Bellhaven Senior Living (Parent Account)":
                    raise StaleProposal("Target parent does not match Bellhaven")
                old = None
                if kind == "chow":
                    old = client.account(p["accounts"][0]["account_id"])
                    allowed = {"chow_current_account": journal["created_account_id"]} if journal.get("created_account_id") else {}
                    unchanged(old, p["accounts"][0], allowed)
                    if not protected_billing(old):
                        raise StaleProposal("Billing no longer requires CHOW. Rerun and review the appropriate action.")
                created = creation(db, p, client, journal, changes["create"])
                if old:
                    # Re-read after creation too. Only the link may change.
                    old = client.account(old["account_id"])
                    unchanged(old, p["accounts"][0], {"chow_current_account": created["account_id"]})
                    if old.get("chow_current_account") != created["account_id"]:
                        record(db, identifier, "applying", journal, "chow_link_started")
                        client.update(old["account_id"], {"chow_current_account": created["account_id"]})
                    after = client.account(old["account_id"])
                    unchanged(after, p["accounts"][0], {"chow_current_account": created["account_id"]})
                    if after.get("chow_current_account") != created["account_id"]:
                        raise ValueError("CHOW link not confirmed; resume to reconcile it")
                    journal["old_account_id"] = old["account_id"]
                    journal["old_fields_preserved"] = True
                journal["result_account_id"] = created["account_id"]
                journal["result"] = "CRM values verified after write"
            else:
                if kind not in {"update", "reparent", "duplicate", "not_on_website"}:
                    raise ValueError("Unsupported proposal type")
                target_id = changes.get("account_id") or p["accounts"][0]["account_id"]
                desired = {k: v for k, v in changes.items() if k != "account_id"}
                if not desired:
                    raise ValueError("No approved field updates")
                expected = next(a for a in p["accounts"] if a["account_id"] == target_id)
                current = client.account(target_id)
                unchanged(current, expected, desired)
                if "parent_id" in desired:
                    if protected_billing(current):
                        raise StaleProposal("Revenue and outstanding AR now require CHOW; parent change blocked")
                    if client.account(desired["parent_id"])["name"] != "Bellhaven Senior Living (Parent Account)":
                        raise StaleProposal("Target parent does not match Bellhaven")
                if kind == "duplicate":
                    survivor = client.account(desired["duplicate_of_account"])
                    signals = matching_signals(p["location"], survivor)
                    if survivor["status"] != "Active" or survivor.get("duplicate_of_account") or survivor.get("chow_current_account") or not (signals["same_street"] and signals["same_city"] and signals["same_state"]):
                        raise StaleProposal("Duplicate survivor is no longer a current matching account")
                    if protected_billing(current) or current["lifetime_revenue"] > 0:
                        raise StaleProposal("Duplicate now has billing history; review before retirement")
                if any(current.get(k) != v for k, v in desired.items()):
                    record(db, identifier, "applying", journal, "patch_started", {"account_id": target_id, "fields": sorted(desired)})
                    client.update(target_id, desired)
                after = client.account(target_id)
                unchanged(after, expected, desired)
                if any(after.get(k) != v for k, v in desired.items()):
                    raise ValueError("CRM values did not match approval after PATCH")
                journal["result_account_id"] = target_id
                journal["result"] = "CRM values verified after write"
            record(db, identifier, "applied", journal, "verified_complete", journal)
            return journal
        except Exception as error:
            journal["last_error"] = str(error)
            record(db, identifier, "failed", journal, "execution_failed", {"error": str(error)})
            raise


def prepare_resolution(path, identifier, survivor_id, reason, client):
    """Prepare separate proposals for a human-selected survivor; no CRM writes."""
    if not reason.strip():
        raise ValueError("Explain why this survivor was selected")
    with writer_lock(path), closing(connect(path)) as db:
        row, p = load_proposal(db, identifier)
        if row["state"] != "pending" or p["kind"] != "ambiguous_match":
            raise ValueError("Select a pending ambiguous-match proposal")
        verify_source(p, client.base)
        candidates = [client.account(a["account_id"]) for a in p["accounts"]]
        survivor = next((a for a in candidates if a["account_id"] == survivor_id), None)
        if not survivor:
            raise ValueError("Selected survivor was not a candidate")
        for a in candidates:
            s = matching_signals(p["location"], a)
            if not (s["same_street"] and s["same_city"] and s["same_state"]):
                raise ValueError("This resolution requires shared-address candidates; investigate conflicting locations separately")
        parents = [a for a in client.accounts() if a["name"] == "Bellhaven Senior Living (Parent Account)"]
        if len(parents) != 1:
            raise ValueError("Cannot identify Bellhaven parent")
        children, _ = build_proposals([p["location"]], [parents[0], survivor])
        for loser in candidates:
            if loser["account_id"] == survivor_id:
                continue
            if loser["lifetime_revenue"] > 0 or protected_billing(loser):
                raise ValueError("A candidate has billing history; resolve manually before duplicate retirement")
            children.append(proposal("duplicate", p["location"], [loser, survivor],
                {"account_id": loser["account_id"], "status": "Inactive", "duplicate_of_account": survivor_id,
                 "note": (loser.get("note", "") + "\nReviewer-selected duplicate of " + survivor_id + ". " + reason.strip()).strip()},
                "Reviewer-selected survivor. " + reason.strip(), "review", survivor_account_id=survivor_id))
        now = datetime.now(timezone.utc).isoformat()
        with db:
            for child in children:
                child["resolution_of"] = identifier
                db.execute("""INSERT INTO proposals(proposal_id,kind,payload_json,first_seen,last_seen)
                    VALUES (?,?,?,?,?) ON CONFLICT(proposal_id) DO NOTHING""",
                    (child["proposal_id"], child["kind"], json.dumps(child), now, now))
            # Persist the ambiguity decision so unchanged evidence does not ask again.
            db.execute("UPDATE proposals SET state='applied',decision_at=?,decision_note=?,execution_json=? WHERE proposal_id=?",
                (now, reason.strip(), json.dumps({"crm_writes": 0, "prepared_proposal_ids": [c["proposal_id"] for c in children]}), identifier))
            audit(db, identifier, "resolution_prepared", {"survivor_id": survivor_id, "reason": reason.strip(), "children": [c["proposal_id"] for c in children]})
        return children
