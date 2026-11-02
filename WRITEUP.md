# Matching approach, AI use, and next steps

## Approach

I treated the operator website as evidence of the current Bellhaven portfolio and
compared it with the full CRM account inventory, including accounts under other
parents. I followed directory pagination and homepage links rather than relying
on a name search. This found the homepage-only Findlay location as well as the
34 directory listings.

Matching prioritizes normalized address and locality, with phone and name evidence
used for corroboration and survivor ranking. A name-only match is insufficient:
the Ohio Amberly Manor should not be linked to the same-name Colorado account.
Rebrands can still match when address and phone support identity. Conflicting or
equally supported records become review items rather than forced matches.

Each proposed change shows source facts, CRM records, matching signals, before/after
values, and a reason. Human approval triggers fresh checks and API writeback;
rejection leaves the CRM unchanged and persists the decision. No daily-run command
approves its own proposals.

## Billing and record retention

When re-parenting requires both revenue history and positive outstanding AR, I use
the required CHOW workflow: preserve the old account, create a replacement under
the correct parent, and update only the old account's `chow_current_account` link.
Otherwise, direct re-parenting is permitted. The code checks current balances
before execution and verifies the resulting records.

Duplicate proposals retain both records, mark the losing copy Inactive, set
`duplicate_of_account`, and explain the choice in the note. Records with billing
history need additional review. Absence from the website produces Needs Review
rather than an unsupported closure or sale inference. Physical and billing
addresses may legitimately differ, so a PO box is not automatically overwritten.

## AI use

I used ChatGPT/Codex for API and website exploration, implementation, automated
tests, and debugging. I directed the work in stages and reviewed the evidence and
proposals through the app. A Windows SQLite cleanup issue was found during local
testing and fixed by explicitly closing connections. The pipeline itself uses
deterministic Python matching and requires no LLM API or paid model key.

The demo includes my approval of the Chesterton name correction and rejection of
Kettering's ambiguous match. For Kettering, the shared address suggests related
records, but competing names and phone numbers do not establish a clear survivor.
I left those records unchanged pending further investigation. That is an unresolved
case, not a completed correction. The final status report should accompany any
claims about the remaining review outcomes.

## Reruns, recovery, and daily execution

SQLite stores stable proposal fingerprints, decisions, execution state, and audit
events. Identical decided proposals stay decided across reruns. Approved creations
have durable markers so an interrupted POST can be reconciled without blindly
creating another account. If creation remains uncertain, execution stops for manual
investigation. Daily scheduling uses a persistent local database; the included
cron/Windows configuration is not activated. CI only runs fake-CRM tests.

## What I would build next

- Better evidence for colocated facilities and ambiguous survivor decisions,
  including contact verification and acquisition announcements.
- More complete address validation while separating physical and billing fields.
- Conditional updates or upstream idempotency support to reduce concurrent-write
  risk, if the CRM API exposes those capabilities.
- Managed persistent review state, monitoring, and snapshot retention policies for
  a team deployment.

## Final submission fields

Enter the public repository link, accessible demo link, and actual time spent in
the assessment form. The time estimate should include implementation, reviewing,
debugging, and demo preparation; it has not been filled with an invented estimate.
Finish reviewing justified corrections and export a fresh live status report before
describing the CRM end state as complete.
