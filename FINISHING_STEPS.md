# Finish the assessment

The project code and demo are prepared. The remaining CRM review must be completed
in the app; do not submit with justified corrections left pending.

1. Install this update over the existing project, preserving `data` and `.venv`.
2. Run the tests, then open `app.py` with Streamlit.
3. Finish reviewing pending items. Approve justified name/field changes, parent
   changes, creates, duplicates, and the two CHOW cases. Acknowledge Ashtabula's
   review while preserving its PO box if you agree. Investigate errors rather than
   treating them as completed. Kettering's reasoned rejection remains documented.
4. For Marietta and Tiffin, inspect the OLD record's parent, balances, and CHOW
   link, then the NEW record's Bellhaven parent. Only the link may change on the old
   record. For duplicate retirements, check the loser is Inactive and linked to
   the intended survivor. Inspect multi-care field values after their first write.
5. Stop the app with Ctrl+C and run the following in the same project directory:

```powershell
$env:BELLHAVEN_API_TOKEN = Read-Host "Paste your personal CRM token"
.\.venv\Scripts\python.exe -m bellhaven.pipeline
.\.venv\Scripts\python.exe -m bellhaven.pipeline
.\.venv\Scripts\python.exe -m bellhaven.report
```

Do not add `--replay` to final verification. The two runs should retain decided
items without duplicate creates. The report is `data/submission_status.md`. Check
pending, approved, applying, and failed items; these represent unfinished work.
Rejected findings are deliberately unchanged and must not be described as corrected.
Keep the database. If new evidence changes a proposal, a new review is appropriate.

6. Create an empty public GitHub repository. From this project directory:

```powershell
git init
git add .
git status
git diff --cached --stat
```

Check the staged list: source, tests, docs, examples, and workflow belong there.
The personal token, `.env`, `.venv`, runtime `data`, recordings, and ZIPs do not.
If the list is right:

```powershell
git commit -m "Build Bellhaven CRM reconciliation and human review workflow"
git branch -M main
git remote add origin YOUR_REPOSITORY_URL
git push -u origin main
```

Replace `YOUR_REPOSITORY_URL` with the empty repo URL. If this folder already has
a Git remote, inspect `git remote -v` before adding one. The Actions workflow can
then run the tests on Windows and Linux; local tests passing is not a claim that
the hosted workflow has already run.

7. Upload `Bellhaven_Analyst_Demo.mp4` to an unlisted YouTube video, Loom, or a
   Drive file with anyone-with-link view access. Check playback and permissions
   in a signed-out/incognito window.
8. Review `WRITEUP.md`, accurately describe any unresolved cases and final counts,
   and enter your honest actual time spent in the form. Submit the repository
   URL, accessible video URL, time estimate, and writeup before the stated deadline.

The schedule files are examples only; no deployment or live scheduled task is
required. Be prepared to explain and modify the code in the live walkthrough.
