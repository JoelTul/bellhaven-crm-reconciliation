"""CLI: scrape, reconcile, persist proposals. Never mutate the CRM."""
import argparse
from contextlib import closing
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import uuid
from filelock import FileLock

from .matching import build_proposals
from .source import DEFAULT_BASE, fetch_accounts, scrape
from .store import connect, queue, save_run


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--replay", type=Path, help="Offline snapshot directory containing locations.json and accounts.json")
    args = parser.parse_args()
    base = os.environ.get("BELLHAVEN_BASE_URL", DEFAULT_BASE).rstrip("/")
    if not base.startswith("https://"):
        parser.error("BELLHAVEN_BASE_URL must use HTTPS")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    if args.replay:
        locations = json.loads((args.replay / "locations.json").read_text(encoding="utf-8"))
        accounts = json.loads((args.replay / "accounts.json").read_text(encoding="utf-8"))
        metadata = {"mode": "offline_replay", "note": "Replay requires a previously validated complete snapshot."}
        pages = {}
    else:
        token = os.environ.get("BELLHAVEN_API_TOKEN", "").strip()
        if not token:
            parser.error("Set BELLHAVEN_API_TOKEN in your environment first")
        print("Scraping website and validating directory completeness...", flush=True)
        locations, pages, metadata = scrape(base)
        print(f"Found {len(locations)} locations. Reading all CRM account pages...", flush=True)
        accounts = fetch_accounts(token, base)
        metadata["mode"] = "live_read_only"
    if not locations or not accounts:
        raise ValueError("Empty input; refusing reconciliation")
    proposals, results = build_proposals(locations, accounts)
    summary = dict(run_id=run_id, captured_at=datetime.now(timezone.utc).isoformat(),
                   locations=len(locations), accounts=len(accounts),
                   proposal_counts=dict(Counter(p["kind"] for p in proposals)),
                   classifications=dict(Counter(r["classification"] for r in results)),
                   metadata=metadata, crm_writes=0)
    # Do not touch the prior queue until both sources and proposal generation
    # succeed. Every run has its own evidence snapshot for later review.
    output = args.data_dir / "runs" / run_id
    output.mkdir(parents=True)
    for name, value in [("locations", locations), ("accounts", accounts),
                        ("proposals", proposals), ("results", results), ("summary", summary)]:
        write_json(output / f"{name}.json", value)
    write_json(output / "website_pages.json", pages)
    database = args.data_dir / "review.sqlite3"
    with FileLock(str(database.resolve()) + ".writer.lock", timeout=0), closing(connect(database)) as db:
        save_run(db, run_id, proposals, summary)
        pending = queue(db)
    write_json(args.data_dir / "pending_proposals.json", pending)
    print(json.dumps(summary, indent=2))
    print(f"Pending proposals: {len(pending)}. Queue: {args.data_dir / 'review.sqlite3'}")
    print("Read-only complete. No approvals or CRM writes occurred.")


if __name__ == "__main__":
    main()
