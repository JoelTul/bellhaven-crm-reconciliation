# Bellhaven ownership reconciliation

A Python scraper and CRM reconciliation pipeline with a local Streamlit review app.
It discovers Bellhaven locations, matches them to accounts, explains proposed
corrections, and writes approved changes through the sandbox API.

The pipeline never approves proposals. The reviewer decides in the app. The demo
shows a real name correction and an intentionally rejected ambiguous match.

## Quick start — Windows / PowerShell

Python 3.12 is the tested version. From the project directory:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:BELLHAVEN_API_TOKEN = Read-Host "Paste your personal CRM token"
.\.venv\Scripts\python.exe -m bellhaven.pipeline
.\.venv\Scripts\python.exe -m streamlit run app.py
```

The app opens at http://localhost:8501. You can also enter the token in the app's
masked password field. The app field does not configure a separate terminal's
pipeline process. Tokens are not saved by either command. The optional scheduled
runner can read a local ignored `.env`; see `schedule/README.md`.

Use the virtual environment's Python directly to avoid PowerShell activation
policy issues. Opening the app or running the pipeline does not mutate the CRM.
An approval can create or update accounts. Keep the original local `data` folder
when installing a code update so your decisions and recovery history survive.

## Review workflow

1. Run the live pipeline and open the app.
2. Compare source evidence, candidate records, and before/after values.
3. Approve justified changes; the app rechecks current evidence and verifies the
   CRM result. Rejections require a reason and leave CRM fields unchanged.
4. Review-only acknowledgments preserve fields and record a local decision.
5. For ambiguous shared-address candidates, investigate first. A reviewer-selected
   survivor prepares separate proposals, each of which still needs approval.
6. Open the CRM result link to verify important changes. Record the demo while
   reviewing: show evidence, one approval, one rejection, and the approved CRM result.

Applied counts also include review-only acknowledgments and prepared resolutions;
inspect the decision and audit details to distinguish these from actual CRM writes.

## Matching and evidence

- Crawl the homepage, about page, and directory pagination. The observed directory
  lists 34 locations, while the homepage separately links Findlay: 35 in total.
- Parse every location's name, physical address, city, state, ZIP, care offerings,
  phone, administrator, source URL, and source-content hash.
- Validate directory completeness and the full paginated CRM inventory before
  generating absence findings. Failed/incomplete fetches abort the run.
- Match normalized street + city + state, or corroborated name + phone + city +
  state. A name alone never selects an account. Street suffixes and directions
  are normalized for comparison without cosmetic billing-address rewrites.
- Where multiple candidates match, rank phone corroboration, exact normalized
  name, existing Bellhaven parent, then revenue-history presence. Ties require
  explicit review rather than an arbitrary survivor.
- Generate updates, creates, parent changes, CHOW replacements, duplicate
  retirement, absence reviews, and billing-address reviews with their evidence.

The fictional baseline snapshot under `examples/stage2_snapshot` allows offline
reproduction. It is not a current CRM audit. Use a separate directory for experiments:

```powershell
.\.venv\Scripts\python.exe -m bellhaven.pipeline --replay examples/stage2_snapshot --data-dir data/practice
```

## Billing SOP and duplicates

| Revenue history | Outstanding AR | Approved ownership correction |
|---|---|---|
| Positive | Positive | Create replacement under Bellhaven; set only `chow_current_account` on the old record to its new ID |
| Zero | Any nonnegative amount | Re-parent existing record |
| Any nonnegative amount | Zero | Re-parent existing record |

CHOW preserves the old name, parent, status, billing fields, balances, and note.
The executor checks the old record before creation and again before linking,
and verifies that only the link changed. It never writes revenue or AR balances.
Invalid monetary values stop execution.

Duplicates are never merged or deleted. An approved losing record is marked
Inactive, linked through `duplicate_of_account`, and given an explanatory note.
Possible duplicates with billing history require further review.

Absence from the website does not prove closure or sale: propose Needs Review,
retain the parent, and explain the uncertainty. A billing PO box can legitimately
differ from a physical address; preserve it unless evidence justifies a change.

## Daily operation and safe reruns

The required daily cron example and equivalent Windows configuration are in
`schedule/`. They are configuration examples and have not been activated.
`python scripts/run_daily.py` uses a stable project path and persistent SQLite
state. It only prepares proposals; it never runs an approval action.

Proposal fingerprints include source business facts, relevant CRM before values,
and proposed changes. Identical rejected/applied decisions stay decided on reruns.
Changed evidence can legitimately require a new review. Pending machine-generated
findings that disappear are superseded. Manually prepared resolutions are retained
and freshness-checked when executed. Do not delete the database to reset a demo.

An OS-backed file lock serializes local pipeline persistence and review writeback.
SQLite connections close explicitly, including on Windows. New-account creation
intent is committed before POST. A stable marker in the new account's note and a
persisted replacement ID support recovery if a response or CHOW linking is interrupted.
Recovery reuses a matching marker rather than blindly repeating POST. If the
outcome remains uncertain and no marker is visible, it stops for manual investigation.
PATCH recovery checks whether approved values already landed. Finished approvals
return the recorded result without another write.

## Validation and final status

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m bellhaven.pipeline
.\.venv\Scripts\python.exe -m bellhaven.pipeline
.\.venv\Scripts\python.exe -m bellhaven.report
```

After reviewing the real queue, both live reruns should preserve decisions and
avoid duplicate creates. Investigate pending, failed, or partial executions.
`data/submission_status.md` summarizes local decisions and the latest live snapshot.
Rejected cases remain unchanged and should be described as unresolved, not corrected.

The test suite covers fetch completeness, matching, billing branches, duplicate
handling, decision persistence, stale approvals, interrupted writes, and UI actions.
Tests use a fake CRM and make no live API mutations. The GitHub Actions workflow
runs tests on Linux and Windows without a CRM token; it is not the daily scheduler.

## Files

| Path | Purpose |
|---|---|
| `app.py` | Human review interface |
| `bellhaven/source.py` | Website scraper and paginated read client |
| `bellhaven/matching.py` | Evidence, matching, proposals, billing rules |
| `bellhaven/store.py` | SQLite proposals, decisions, run history, audit |
| `bellhaven/review.py` | Explicit approval, rejection, recovery, resolution preparation |
| `bellhaven/crm.py` | API client with no automatic POST/PATCH retries |
| `bellhaven/pipeline.py` | Read-only CLI and snapshots |
| `bellhaven/report.py` | Local final-status report |
| `scripts/run_daily.py` | Unattended daily entry point |
| `schedule/` | Schedule configuration examples |
| `tests/` | Automated correctness and UI tests |
| `WRITEUP.md` | Submission approach, AI use, limitations, next steps |

Runtime state is in `data/` and is ignored by Git. Its SQLite database is authoritative;
`pending_proposals.json` is refreshed by pipeline runs, not every UI action. Snapshots
and raw HTML are retained under `data/runs/<run-id>/` for traceability. Back up the
database with SQLite's backup API or while all processes are stopped.

## Limitations and next improvements

The API has no documented conditional-update or transaction mechanism; an external
writer could change a record after the final preflight read. Local recovery is
conservative, not distributed exactly-once execution. Separate daily snapshots are
not atomic upstream reads. Local state must persist across runs; a fresh clone does
not contain another reviewer's decision history.

Multiple care offerings are mapped to CRM terms and proposed as a semicolon-delimited
string. The API docs omit write schemas: inspect the first actual multi-care result
and any validation error. Existing CRM phone differences are evidence for review;
this version does not automatically overwrite those phone fields.

Further work would improve colocated-facility resolution, ownership evidence beyond
the operator website, address validation, upstream conditional writes, and managed
persistent storage. No LLM is called inside the pipeline. See `WRITEUP.md` for AI use.
