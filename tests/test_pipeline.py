import copy
from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bellhaven.matching import build_proposals, protected_billing, street_key
from bellhaven.source import fetch_accounts, parse_location, scrape
from bellhaven.store import connect, queue, save_run


def account(id="facility", **changes):
    value = dict(account_id=id, name="Bellhaven of Test", parent_id="parent",
                 billing_street="10 West Main Street", billing_city="Testville",
                 billing_state="OH", billing_zip="44000", care_type="Assisted Living",
                 status="Active", phone="(555) 111-2222", lifetime_revenue=0,
                 outstanding_ar=0, duplicate_of_account="", chow_current_account="", note="")
    value.update(changes)
    return value


PARENT = account("parent", name="Bellhaven Senior Living (Parent Account)", parent_id="")
LOCATION = dict(name="Bellhaven of Test", street="10 W Main St", city="Testville",
                state="OH", zip="44000", care_offerings=["Assisted Living"],
                phone="5551112222", source_url="https://example.test/communities/test")


class MatchingTests(unittest.TestCase):
    def reconcile(self, *accounts, location=None):
        return build_proposals([location or LOCATION], [PARENT, *accounts])[0]

    def test_equivalent_address_does_not_generate_cosmetic_updates(self):
        self.assertEqual(street_key("1250 Northwest Franklin Street"), street_key("1250 NW Franklin St"))
        self.assertEqual(self.reconcile(account()), [])

    def test_same_name_other_state_is_not_matched(self):
        proposals = self.reconcile(account(parent_id="other", billing_state="CO"))
        self.assertEqual([p["kind"] for p in proposals], ["create"])

    def test_changed_name_can_match_address(self):
        proposal = self.reconcile(account(name="Former Owner Care Centre"))[0]
        self.assertEqual(proposal["changes"], {"name": LOCATION["name"]})

    def test_billing_rule_all_branches_and_original_is_unchanged(self):
        for revenue, ar, kind in [(100, 20, "chow"), (100, 0, "reparent"), (0, 20, "reparent"), (0, 0, "reparent")]:
            original = account(parent_id="old-parent", lifetime_revenue=revenue, outstanding_ar=ar)
            before = copy.deepcopy(original)
            proposed = self.reconcile(original)[0]
            self.assertEqual(proposed["kind"], kind)
            self.assertEqual(original, before)
            if kind == "chow":
                self.assertNotIn("parent_id", proposed["changes"])
                self.assertEqual(proposed["changes"]["link_old_field"], "chow_current_account")

    def test_invalid_billing_fails_closed(self):
        for value in ["NaN", "Infinity", -1]:
            with self.assertRaises(ValueError):
                protected_billing(account(lifetime_revenue=value))

    def test_duplicate_uses_phone_corroboration(self):
        proposals = self.reconcile(account("good"), account("copy", phone="5559998888"))
        duplicate = next(p for p in proposals if p["kind"] == "duplicate")
        self.assertEqual(duplicate["changes"]["duplicate_of_account"], "good")
        self.assertEqual(duplicate["changes"]["status"], "Inactive")
        self.assertNotIn("parent_id", duplicate["changes"])

    def test_equal_duplicate_evidence_requires_resolution(self):
        self.assertEqual(self.reconcile(account("a"), account("b"))[0]["kind"], "ambiguous_match")

    def test_po_box_is_preserved(self):
        proposal = self.reconcile(account(billing_street="PO Box 517"))[0]
        self.assertEqual(proposal["kind"], "billing_address_review")
        self.assertEqual(proposal["changes"], {})

    def test_absence_does_not_reparent_or_mark_closed(self):
        proposals, _ = build_proposals([LOCATION], [PARENT, account(), account("absent", name="Gone", billing_city="Elsewhere")])
        p = next(p for p in proposals if p["kind"] == "not_on_website")
        self.assertEqual(p["changes"]["status"], "Needs Review")
        self.assertNotIn("parent_id", p["changes"])

    def test_existing_chow_link_prevents_old_account_matching(self):
        proposals = self.reconcile(account("old", parent_id="prior", chow_current_account="new", lifetime_revenue=100, outstanding_ar=50), account("new"))
        self.assertEqual(proposals, [])

    def test_applied_duplicate_does_not_reappear(self):
        proposals = self.reconcile(account("good"), account("copy", phone="5559998888", status="Inactive", duplicate_of_account="good"))
        self.assertEqual(proposals, [])


class PersistenceTests(unittest.TestCase):
    def test_rerun_retains_decisions_and_does_not_duplicate_queue(self):
        proposals, _ = build_proposals([LOCATION], [PARENT])
        with tempfile.TemporaryDirectory() as directory:
            with closing(connect(Path(directory) / "review.sqlite3")) as db:
                save_run(db, "first", proposals, {})
                save_run(db, "second", proposals, {})
                self.assertEqual(len(queue(db)), 1)
                for state in ["rejected", "applied"]:
                    db.execute("UPDATE proposals SET state=?", (state,))
                    save_run(db, state, proposals, {})
                    self.assertEqual(queue(db), [])
                self.assertEqual(db.execute("SELECT COUNT(*) FROM proposals").fetchone()[0], 1)

    def test_irrelevant_timestamp_does_not_change_fingerprint(self):
        before = account(name="Old name", updated_at="one")
        p1 = build_proposals([LOCATION], [PARENT, before])[0]
        before["updated_at"] = "two"
        p2 = build_proposals([LOCATION], [PARENT, before])[0]
        self.assertEqual(p1[0]["proposal_id"], p2[0]["proposal_id"])


class FetchTests(unittest.TestCase):
    @patch("bellhaven.source.get")
    def test_accounts_fetch_every_page(self, get):
        get.side_effect = [Response({"data": [account("a")], "total": 2, "page": 1}),
                           Response({"data": [account("b")], "total": 2, "page": 2})]
        self.assertEqual(len(fetch_accounts("token")), 2)
        self.assertEqual(get.call_count, 2)

    @patch("bellhaven.source.get")
    def test_incomplete_crm_read_aborts(self, get):
        get.side_effect = [Response({"data": [account("a")], "total": 2, "page": 1}),
                           Response({"data": [], "total": 2, "page": 2})]
        with self.assertRaises(ValueError):
            fetch_accounts("token")

    @patch("bellhaven.source.get")
    def test_scrape_discovers_homepage_only_location(self, get):
        detail = '<div class="wrap"><h1>Test</h1><dl class="detail"><dt>Address</dt><dd>10 Main St<br>Testville, OH 44000</dd><dt>Care Offerings</dt><dd><span class="badge">Assisted Living</span></dd></dl></div>'
        pages = {"/": '<a href="/communities/extra">New location</a>', "/about": "About",
                 "/communities": '1 communities listed<div class="card"><h3><a href="/communities/one">One</a></h3></div>',
                 "/communities/one": detail, "/communities/extra": detail}
        get.side_effect = lambda url: Response(text=pages[url.replace("https://example.test", "")])
        locations, _, metadata = scrape("https://example.test")
        self.assertEqual(len(locations), 2)
        self.assertEqual(metadata["extra_location_urls"], ["https://example.test/communities/extra"])

    @patch("bellhaven.source.get")
    def test_incomplete_website_aborts(self, get):
        get.return_value = Response(text="2 communities listed")
        with self.assertRaises(ValueError):
            scrape("https://example.test")


class Response:
    def __init__(self, data=None, text=""):
        self.data, self.text = data, text

    def json(self):
        return self.data


if __name__ == "__main__":
    unittest.main()
