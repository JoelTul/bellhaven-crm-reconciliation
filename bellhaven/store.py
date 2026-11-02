"""Persistent review queue. Only the later review app will record decisions."""
import json
import sqlite3
from datetime import datetime, timezone


def connect(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY, captured_at TEXT NOT NULL, summary_json TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS proposals (
        proposal_id TEXT PRIMARY KEY, kind TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'pending'
            CHECK(state IN ('pending','rejected','approved','applying','applied','failed','superseded')),
        first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
        decision_at TEXT, decision_note TEXT, execution_json TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS audit (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT, proposal_id TEXT NOT NULL,
        occurred_at TEXT NOT NULL, event TEXT NOT NULL, details_json TEXT NOT NULL)""")
    return db


def save_run(db, run_id, proposals, summary):
    now = datetime.now(timezone.utc).isoformat()
    with db:
        db.execute("INSERT INTO runs VALUES (?, ?, ?)", (run_id, now, json.dumps(summary)))
        current = {p["proposal_id"] for p in proposals}
        for row in db.execute("SELECT proposal_id,payload_json FROM proposals WHERE state='pending'").fetchall():
            if row[0] not in current and not json.loads(row[1]).get("resolution_of"):
                db.execute("UPDATE proposals SET state='superseded' WHERE proposal_id=?", (row[0],))
        for p in proposals:
            db.execute("""INSERT INTO proposals
                (proposal_id,kind,payload_json,first_seen,last_seen) VALUES (?,?,?,?,?)
                ON CONFLICT(proposal_id) DO UPDATE SET
                    last_seen=excluded.last_seen,payload_json=excluded.payload_json,
                    state=CASE WHEN proposals.state='superseded' THEN 'pending' ELSE proposals.state END""",
                (p["proposal_id"], p["kind"], json.dumps(p, sort_keys=True), now, now))


def queue(db):
    return [json.loads(row[0]) for row in db.execute(
        "SELECT payload_json FROM proposals WHERE state='pending' ORDER BY kind, proposal_id")]


def audit(db, proposal_id, event, details=None):
    db.execute("INSERT INTO audit(proposal_id,occurred_at,event,details_json) VALUES (?,?,?,?)",
               (proposal_id, datetime.now(timezone.utc).isoformat(), event, json.dumps(details or {})))


def load_proposal(db, identifier):
    row = db.execute("SELECT * FROM proposals WHERE proposal_id=?", (identifier,)).fetchone()
    if row is None:
        raise ValueError("Proposal does not exist")
    return dict(row), json.loads(row["payload_json"])
