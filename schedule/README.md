# Daily schedule configuration

`crontab.example` is the required daily schedule example. It is configuration
only and does not need to be activated for the assessment. Adjust the absolute
paths for the host. The wrapper always uses the project directory and a persistent
SQLite database; it only fetches data and prepares proposals. Approval and CRM
writeback remain separate human actions in the app.

Copy `.env.example` to `.env` and supply the personal token locally, or inject
`BELLHAVEN_API_TOKEN` through the scheduler environment. The wrapper reads literal
settings; it does not execute shell commands or expand variables in `.env`.
Limit access to the token file on a real deployment. `.env` is ignored by Git.

For an equivalent Windows Task Scheduler configuration:

| Setting | Value |
|---|---|
| Trigger | Daily at 7:00 AM, host local timezone |
| Program/script | Absolute path to this project's `.venv\Scripts\python.exe` |
| Arguments | `scripts\run_daily.py` |
| Start in | Absolute path to the `bellhaven-reconciler` directory |
| If task is already running | Do not start a new instance |
| Credential source | Local ignored `.env` or scheduler environment |

Keep the project at a stable path before activating a task; a Downloads folder
that may be moved is unsuitable for a persistent deployment. This file describes
the configuration, not a task that has been installed on the user's computer.

Back up `data/review.sqlite3` while the app and pipeline are stopped, or use
SQLite's backup API. Keep this state outside an ephemeral CI runner. The GitHub
Actions workflow in this repository runs tests only; it is not the production
daily scheduler and does not use a CRM token.
