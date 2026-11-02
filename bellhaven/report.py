"""Export local decisions and latest live snapshot counts; never change CRM."""
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path

from .store import connect


def cell(value):
    return str(value or "").replace("|", "/").replace("\n", " ")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    args = parser.parse_args()
    path = args.data_dir / "review.sqlite3"
    if not path.exists():
        parser.error("No review database found; run the pipeline first")
    with closing(connect(path)) as db:
        rows = [dict(r) for r in db.execute("SELECT * FROM proposals ORDER BY kind,proposal_id")]
        events = [dict(r) for r in db.execute("SELECT * FROM audit ORDER BY event_id")]
    states = Counter(r["state"] for r in rows)
    lines = ["# Submission status", "", "Generated: " + datetime.now(timezone.utc).isoformat(), "",
             "This report describes local review state. Re-run the live pipeline immediately before exporting it.", "",
             "| State | Count |", "|---|---:|"]
    lines += [f"| {state} | {count} |" for state, count in sorted(states.items())]
    live = None
    for summary_path in sorted((args.data_dir / "runs").glob("*/summary.json"), reverse=True):
        candidate = json.loads(summary_path.read_text(encoding="utf-8"))
        if candidate.get("metadata", {}).get("mode") == "live_read_only":
            live = candidate
            break
    lines += ["", "## Latest live inventory", ""]
    if live:
        lines += [f"Captured: {live['captured_at']}",
                  f"Website locations: {live['locations']}; CRM accounts: {live['accounts']}.",
                  "Generated finding counts (includes findings suppressed by prior decisions):",
                  "", "| Finding | Count |", "|---|---:|"]
        lines += [f"| {kind} | {count} |" for kind, count in sorted(live["proposal_counts"].items())]
    else:
        lines += ["No live snapshot found. Offline replay is not a final CRM verification."]
    lines += ["", "## Decisions", "", "| Facility | Finding | State | Reason |", "|---|---|---|---|"]
    for row in rows:
        if row["state"] == "superseded":
            continue
        p = json.loads(row["payload_json"])
        facility = p["location"]["name"] if p["location"] else p["accounts"][0]["name"]
        lines.append("| " + " | ".join(cell(v) for v in [facility, row["kind"], row["state"], row["decision_note"]]) + " |")
    incomplete = sum(states[state] for state in ["pending", "approved", "applying", "failed"])
    verified = sum(e["event"] == "verified_complete" for e in events)
    lines += ["", f"Incomplete review/execution items: {incomplete}.",
              f"Verified completion events: {verified} (may include no-write review acknowledgments).",
              "Rejected findings are intentionally unchanged, not corrected. Applied also includes review-only acknowledgments and prepared resolutions.",
              "Inspect CHOW links, duplicate statuses, and multi-care values in the CRM before submission."]
    out = args.data_dir / "submission_status.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Report: {out}")
    print(f"Incomplete items: {incomplete}; rejected: {states['rejected']}; failed: {states['failed']}")
    if not live:
        print("Final live verification still required.")


if __name__ == "__main__":
    main()
