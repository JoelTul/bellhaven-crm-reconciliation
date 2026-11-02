"""Explainable matching and proposed actions; no network writes."""
import hashlib
import json
import re
from difflib import SequenceMatcher
from decimal import Decimal

ALIASES = dict(street="st", road="rd", avenue="ave", boulevard="blvd", drive="dr",
               lane="ln", court="ct", place="pl", parkway="pkwy", pike="pk",
               north="n", south="s", east="e", west="w", northwest="nw",
               northeast="ne", southwest="sw", southeast="se")
CARE_MAP = {"Assisted Living": "Assisted Living", "Memory Support": "Memory Care",
            "Short-Term Rehabilitation & Nursing": "Skilled Nursing"}
RELEVANT = ("account_id", "name", "parent_id", "billing_street", "billing_city",
            "billing_state", "billing_zip", "care_type", "status", "phone",
            "lifetime_revenue", "outstanding_ar", "chow_current_account",
            "duplicate_of_account", "note")


def normalize(value):
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def street_key(value):
    return " ".join(ALIASES.get(word, word) for word in normalize(value).split())


def phone_key(value):
    digits = re.sub(r"\D", "", value or "")
    return digits[1:] if len(digits) == 11 and digits.startswith("1") else digits


def protected_billing(account):
    # Unknown/invalid monetary values fail closed instead of treating as zero.
    revenue, ar = (Decimal(str(account[key])) for key in ("lifetime_revenue", "outstanding_ar"))
    if not revenue.is_finite() or not ar.is_finite() or revenue < 0 or ar < 0:
        raise ValueError("Invalid billing values")
    return revenue > 0 and ar > 0


def care_value(location):
    return "; ".join(sorted({CARE_MAP[value] for value in location["care_offerings"]}))


def account_payload(location, parent_id):
    # Physical address is appropriate for NEW records. Existing billing addresses
    # are not replaced merely because they differ from a website address.
    return dict(name=location["name"], parent_id=parent_id,
                billing_street=location["street"], billing_city=location["city"],
                billing_state=location["state"], billing_zip=location["zip"],
                care_type=care_value(location), status="Active", phone=location.get("phone", ""))


def matching_signals(location, account):
    same_city = normalize(location["city"]) == normalize(account["billing_city"])
    same_state = location["state"] == account["billing_state"]
    same_street = street_key(location["street"]) == street_key(account["billing_street"])
    same_phone = bool(phone_key(location.get("phone"))) and phone_key(location.get("phone")) == phone_key(account.get("phone"))
    similarity = SequenceMatcher(None, normalize(location["name"]), normalize(account["name"])).ratio()
    return dict(same_city=same_city, same_state=same_state, same_street=same_street,
                same_zip=location["zip"][:5] == account["billing_zip"][:5],
                same_phone=same_phone, name_similarity=round(similarity, 3))


def proposal(kind, location, accounts, changes, reason, confidence="high", **extra):
    identity = {
        "kind": kind, "source_url": location["source_url"] if location else None,
        "accounts": sorted([{key: a.get(key) for key in RELEVANT} for a in accounts],
                           key=lambda a: a["account_id"]),
        "changes": changes,
        # Ignore volatile scrape timestamps and HTML formatting. Source business
        # facts changing constitute a new proposal; identical decisions persist.
        "source": {key: location.get(key) for key in ("name", "street", "city", "state", "zip", "care_offerings", "phone")} if location else None,
    }
    identifier = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return dict(proposal_id=identifier, kind=kind, confidence=confidence, reason=reason,
                location=location, accounts=accounts, changes=changes,
                evidence=[dict(account_id=a["account_id"], **matching_signals(location, a))
                          for a in accounts] if location else [], **extra)


def build_proposals(locations, accounts):
    parents = [a for a in accounts if a["name"] == "Bellhaven Senior Living (Parent Account)"]
    if len(parents) != 1:
        raise ValueError("Expected one unambiguous Bellhaven parent account")
    parent_id = parents[0]["account_id"]
    facilities = [a for a in accounts if not a["name"].endswith("(Parent Account)")]
    by_id = {a["account_id"]: a for a in accounts}
    active = [a for a in facilities if a["status"] != "Inactive"
              and not a.get("duplicate_of_account") and not a.get("chow_current_account")]
    consumed, results, proposals = set(), [], []

    for location in locations:
        exact, fallback, weak = [], [], []
        for account in active:
            s = matching_signals(location, account)
            if s["same_city"] and s["same_state"] and s["same_street"]:
                exact.append(account)
            elif s["same_city"] and s["same_state"] and s["same_phone"] and s["name_similarity"] >= 0.6:
                fallback.append(account)
            elif s["name_similarity"] >= 0.6 and s["same_city"] and s["same_state"]:
                weak.append(account)
        candidates = exact or fallback
        if not candidates:
            if weak:
                consumed.update(a["account_id"] for a in weak)
                proposals.append(proposal("ambiguous_match", location, weak, {},
                    "Similar name and locality but conflicting address/phone. Resolve identity before creating or updating.", "review"))
                results.append(dict(location=location["name"], classification="ambiguous_match"))
            else:
                # Include same-name distractors as evidence, never as a match.
                distractors = [a for a in active if normalize(a["name"]) == normalize(location["name"])
                    or (a["billing_state"] == location["state"]
                        and normalize(a["billing_city"]) == normalize(location["city"])
                        and matching_signals(location, a)["name_similarity"] >= 0.35)]
                proposals.append(proposal("create", location, distractors,
                    {"create": account_payload(location, parent_id)},
                    "No account matched address or corroborated name/phone in this city and state. Same-name accounts elsewhere are excluded."))
                results.append(dict(location=location["name"], classification="missing_account"))
            continue

        consumed.update(a["account_id"] for a in candidates)
        def rank(account):
            signals = matching_signals(location, account)
            return (signals["same_phone"], normalize(location["name"]) == normalize(account["name"]),
                    account["parent_id"] == parent_id, account.get("lifetime_revenue", 0) > 0)

        candidates = sorted(candidates, key=lambda a: a["account_id"])
        candidates.sort(key=rank, reverse=True)
        if len(candidates) > 1 and rank(candidates[0]) == rank(candidates[1]):
            proposals.append(proposal("ambiguous_match", location, candidates, {},
                "Several accounts share the normalized address; no decisive phone/name/parent evidence selects a survivor. Reviewer must resolve.", "review"))
            results.append(dict(location=location["name"], classification="ambiguous_match"))
            continue

        survivor = candidates[0]
        changes, flags = {}, []
        if normalize(survivor["name"]) != normalize(location["name"]):
            changes["name"] = location["name"]
        mapped_care = care_value(location)
        existing_care = {s.strip() for s in re.split(r"[;,]", survivor.get("care_type", "")) if s.strip()}
        if existing_care != set(mapped_care.split("; ")):
            changes["care_type"] = mapped_care
        signals = matching_signals(location, survivor)
        if not signals["same_street"]:
            flags.append("Website physical address differs from CRM billing address; preserve billing address pending review.")
        if not signals["same_zip"]:
            flags.append("ZIP differs; proposed ZIP correction requires review.")
            changes["billing_zip"] = location["zip"]

        kind = "update"
        if survivor["parent_id"] != parent_id:
            if protected_billing(survivor):
                kind = "chow"
                changes = {"create": account_payload(location, parent_id),
                           "link_old_field": "chow_current_account"}
                reason = "Ownership change with revenue history AND outstanding AR. Preserve old fields; create replacement and link old account to new ID."
            else:
                changes["parent_id"] = parent_id
                kind = "reparent"
                reason = "Website establishes Bellhaven ownership; existing account may be re-parented because revenue history or outstanding AR is zero."
        else:
            reason = "Matched facility; normalize outdated business fields using website evidence."
        if changes:
            proposals.append(proposal(kind, location, [survivor], changes, reason,
                                      "review" if flags else "high", warnings=flags))
        if flags and not changes:
            proposals.append(proposal("billing_address_review", location, [survivor], {},
                                      " ".join(flags), "review"))
        for loser in candidates[1:]:
            # Duplicate resolution does not re-parent or merge financial history.
            billing = protected_billing(loser)
            if billing or loser.get("lifetime_revenue", 0) > 0:
                proposals.append(proposal("duplicate_review", location, [loser, survivor], {},
                    "Possible duplicate with billing history; review before retiring. No merge/delete and no parent change proposed.", "review",
                    survivor_account_id=survivor["account_id"]))
            else:
                proposals.append(proposal("duplicate", location, [loser, survivor],
                    {"account_id": loser["account_id"], "status": "Inactive",
                     "duplicate_of_account": survivor["account_id"],
                     "note": (loser.get("note", "") + "\nDuplicate of " + survivor["account_id"] +
                              "; same normalized facility address. Evidence: " + location["source_url"]).strip()},
                    "Same normalized address; surviving account has stronger phone/name/parent evidence. Preserve losing account and link it to survivor.",
                    survivor_account_id=survivor["account_id"]))
        results.append(dict(location=location["name"], account_id=survivor["account_id"],
                            classification=kind if changes else "billing_address_review" if flags else "confident_match"))

    for account in facilities:
        if account["parent_id"] != parent_id or account["account_id"] in consumed or account["status"] == "Inactive":
            continue
        if account.get("duplicate_of_account"):
            continue
        if account.get("chow_current_account") in by_id:
            # Historic billing accounts are expected to remain after CHOW.
            continue
        note = "Not found on the complete Bellhaven website crawl. Ownership/closure unverified; investigate before re-parenting."
        if account["status"] == "Needs Review" and note in account.get("note", ""):
            continue
        proposals.append(proposal("not_on_website", None, [account],
            {"status": "Needs Review", "note": (account.get("note", "") + "\n" + note).strip()},
            "Absent from website; insufficient evidence to infer closure or a new owner.", "review"))
    return proposals, results
