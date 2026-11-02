# Stage 2 verified findings

Live read-only baseline: 35 website locations, 121 CRM accounts. All 3 directory pages and the homepage-only Findlay location were read. No CRM writes occurred.

17 focused tests pass. Replaying the same inputs preserves a queue of 28 pending proposals. Review-only findings require judgment; proposed mutations remain unapproved.

| Proposed outcome | Count |
|---|---:|
| ambiguous_match | 1 |
| billing_address_review | 1 |
| chow | 2 |
| create | 4 |
| duplicate | 5 |
| not_on_website | 3 |
| reparent | 3 |
| update | 9 |

## Review queue

| Finding | Facility | Reason |
|---|---|---|
| ambiguous_match | Bellhaven of Kettering | Several accounts share the normalized address; no decisive phone/name/parent evidence selects a survivor. Reviewer must resolve. |
| billing_address_review | Bellhaven of Ashtabula | Website physical address differs from CRM billing address; preserve billing address pending review. |
| chow | Bellhaven of Marietta | Ownership change with revenue history AND outstanding AR. Preserve old fields; create replacement and link old account to new ID. |
| chow | Bellhaven of Tiffin | Ownership change with revenue history AND outstanding AR. Preserve old fields; create replacement and link old account to new ID. |
| create | Bellhaven of Batavia | No account matched address or corroborated name/phone in this city and state. Same-name accounts elsewhere are excluded. |
| create | Bellhaven of Carlisle | No account matched address or corroborated name/phone in this city and state. Same-name accounts elsewhere are excluded. |
| create | Amberly Manor | No account matched address or corroborated name/phone in this city and state. Same-name accounts elsewhere are excluded. |
| create | Bellhaven at Union Square | No account matched address or corroborated name/phone in this city and state. Same-name accounts elsewhere are excluded. |
| duplicate | Bellhaven Gardens of Monroe | Same normalized address; surviving account has stronger phone/name/parent evidence. Preserve losing account and link it to survivor. |
| duplicate | Bellhaven of Port Clinton | Same normalized address; surviving account has stronger phone/name/parent evidence. Preserve losing account and link it to survivor. |
| duplicate | Bellhaven of Owosso | Same normalized address; surviving account has stronger phone/name/parent evidence. Preserve losing account and link it to survivor. |
| duplicate | Bellhaven Shores of Erie | Same normalized address; surviving account has stronger phone/name/parent evidence. Preserve losing account and link it to survivor. |
| duplicate | Bellhaven Gardens of Monroe | Same normalized address; surviving account has stronger phone/name/parent evidence. Preserve losing account and link it to survivor. |
| not_on_website | Bellhaven Care Center of Alliance | Absent from website; insufficient evidence to infer closure or a new owner. |
| not_on_website | Bellhaven of Coldwater | Absent from website; insufficient evidence to infer closure or a new owner. |
| not_on_website | Bellhaven of Sandusky | Absent from website; insufficient evidence to infer closure or a new owner. |
| reparent | Bellhaven Crossings of Lima | Website establishes Bellhaven ownership; existing account may be re-parented because revenue history or outstanding AR is zero. |
| reparent | Bellhaven Meadows of Findlay | Website establishes Bellhaven ownership; existing account may be re-parented because revenue history or outstanding AR is zero. |
| reparent | Bellhaven of Zanesville | Website establishes Bellhaven ownership; existing account may be re-parented because revenue history or outstanding AR is zero. |
| update | The Arbors at Bellhaven - Dayton | Matched facility; normalize outdated business fields using website evidence. |
| update | Bellhaven Healthcare Centre of Ashland | Matched facility; normalize outdated business fields using website evidence. |
| update | Bellhaven of Portsmouth | Matched facility; normalize outdated business fields using website evidence. |
| update | Bellhaven at Sycamore Ridge | Matched facility; normalize outdated business fields using website evidence. |
| update | Bellhaven of Chesterton | Matched facility; normalize outdated business fields using website evidence. |
| update | Bellhaven of Chagrin Falls | Matched facility; normalize outdated business fields using website evidence. |
| update | Bellhaven Rehabilitation & Nursing of Grove City | Matched facility; normalize outdated business fields using website evidence. |
| update | Bellhaven Shores of Erie | Matched facility; normalize outdated business fields using website evidence. |
| update | Bellhaven Willow Creek | Matched facility; normalize outdated business fields using website evidence. |

## Particularly important evidence

- Marietta: lifetime revenue $51,250; outstanding AR $3,800. CHOW replacement required.
- Tiffin: lifetime revenue $84,000; outstanding AR $12,400. CHOW replacement required.
- Kettering: three CRM records share the normalized address, but none matches the website phone; survivor selection remains unresolved.
- Ashtabula: name, city/state, and phone corroborate the match despite a CRM PO box. Billing address is preserved.
- Amberly Manor: Ohio website facility must not be matched to the same-name Colorado account.
- Union Square: the similarly named CRM account is at a different street address and has a different phone. Both are visible as comparison evidence.
- Portsmouth: website ZIP 45662 differs from CRM ZIP 45626; propose correction with review confidence.
- Alliance, Coldwater, and Sandusky: absent from complete website crawl; propose Needs Review, retain parents.

This is a Stage 2 checkpoint. It has no approval UI or writeback executor yet.
