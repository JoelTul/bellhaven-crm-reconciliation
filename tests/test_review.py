"""Writeback tests use an in-memory fake CRM; no live HTTP mutations."""
import copy
from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bellhaven.matching import build_proposals
from bellhaven.review import StaleProposal, approve, prepare_resolution, reject
from bellhaven.store import connect, queue, save_run
from test_pipeline import account, LOCATION, PARENT


class FakeCRM:
    base = "https://example.test"

    def __init__(self, *accounts):
        self.data = {a["account_id"]: copy.deepcopy(a) for a in [PARENT, *accounts]}
        self.posts, self.patches = [], []
        self.fail_create_after_write = False
        self.fail_create_before_write = False
        self.fail_patch_after_write = False
        self.fail_patch_before_write = False

    def accounts(self):
        return copy.deepcopy(list(self.data.values()))

    def account(self, id):
        return copy.deepcopy(self.data[id])

    def create(self, payload):
        self.posts.append(copy.deepcopy(payload))
        if self.fail_create_before_write:
            self.fail_create_before_write = False
            raise ConnectionError("No response to POST")
        id = "new-" + str(len(self.posts))
        self.data[id] = account(id, **payload)
        if self.fail_create_after_write:
            self.fail_create_after_write = False
            raise ConnectionError("POST succeeded but response lost")
        return self.account(id)

    def update(self, id, payload):
        self.patches.append((id, copy.deepcopy(payload)))
        if self.fail_patch_before_write:
            self.fail_patch_before_write = False
            raise ConnectionError("PATCH not delivered")
        self.data[id].update(payload)
        if self.fail_patch_after_write:
            self.fail_patch_after_write = False
            raise ConnectionError("PATCH succeeded but response lost")
        return self.account(id)


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "review.sqlite3"

    def tearDown(self):
        self.temp.cleanup()

    def seed(self, client, kind):
        proposals, _ = build_proposals([LOCATION], client.accounts())
        with closing(connect(self.path)) as db:
            save_run(db, "first", proposals, {})
        return next(p for p in proposals if p["kind"] == kind)

    def apply(self, p, client):
        return approve(self.path, p["proposal_id"], client, check_source=False)

    def state(self, p):
        with closing(connect(self.path)) as db:
            return db.execute("SELECT state FROM proposals WHERE proposal_id=?", (p["proposal_id"],)).fetchone()[0]

    def test_reject_is_remembered_and_cannot_write(self):
        crm = FakeCRM(account(name="Old name"))
        p = self.seed(crm, "update")
        reject(self.path, p["proposal_id"], "Keep existing name pending investigation")
        with self.assertRaises(ValueError):
            self.apply(p, crm)
        self.assertEqual(crm.posts + crm.patches, [])
        with closing(connect(self.path)) as db:
            save_run(db, "second", [p], {})
            self.assertEqual(queue(db), [])

    def test_direct_reparent_only_when_billing_allows(self):
        crm = FakeCRM(account(parent_id="old", lifetime_revenue=100, outstanding_ar=0))
        p = self.seed(crm, "reparent")
        self.apply(p, crm)
        self.assertEqual(crm.patches, [("facility", {"parent_id": "parent"})])
        self.assertEqual(crm.posts, [])

    def test_changed_ar_blocks_parent_change(self):
        crm = FakeCRM(account(parent_id="old", lifetime_revenue=100, outstanding_ar=0))
        p = self.seed(crm, "reparent")
        crm.data["facility"]["outstanding_ar"] = 50
        with self.assertRaises(StaleProposal):
            self.apply(p, crm)
        self.assertEqual(crm.posts + crm.patches, [])

    def test_chow_preserves_every_old_field_except_link(self):
        old = account(parent_id="old", lifetime_revenue=100, outstanding_ar=50, note="Keep billing note")
        crm = FakeCRM(old)
        p = self.seed(crm, "chow")
        result = self.apply(p, crm)
        new_id = result["created_account_id"]
        self.assertEqual(crm.account("facility"), dict(old, chow_current_account=new_id))
        self.assertEqual(crm.patches, [("facility", {"chow_current_account": new_id})])
        self.assertEqual(crm.account(new_id)["parent_id"], "parent")
        self.assertEqual(self.state(p), "applied")

    def test_lost_post_response_recovers_without_second_create(self):
        crm = FakeCRM(account(parent_id="old", lifetime_revenue=100, outstanding_ar=50))
        p = self.seed(crm, "chow")
        crm.fail_create_after_write = True
        with self.assertRaises(ConnectionError):
            self.apply(p, crm)
        self.apply(p, crm)
        self.assertEqual(len(crm.posts), 1)
        self.assertEqual(crm.account("facility")["chow_current_account"], "new-1")

    def test_unknown_create_outcome_without_marker_never_reposts(self):
        crm = FakeCRM()
        p = self.seed(crm, "create")
        crm.fail_create_before_write = True
        with self.assertRaises(ConnectionError):
            self.apply(p, crm)
        with self.assertRaisesRegex(ValueError, "No second POST"):
            self.apply(p, crm)
        self.assertEqual(len(crm.posts), 1)

    def test_chow_link_failure_resumes_using_existing_new_account(self):
        crm = FakeCRM(account(parent_id="old", lifetime_revenue=100, outstanding_ar=50))
        p = self.seed(crm, "chow")
        crm.fail_patch_before_write = True
        with self.assertRaises(ConnectionError):
            self.apply(p, crm)
        self.apply(p, crm)
        self.assertEqual(len(crm.posts), 1)
        self.assertEqual(crm.account("facility")["chow_current_account"], "new-1")

    def test_lost_patch_response_is_verified_without_repeating_write(self):
        crm = FakeCRM(account(name="Old name"))
        p = self.seed(crm, "update")
        crm.fail_patch_after_write = True
        with self.assertRaises(ConnectionError):
            self.apply(p, crm)
        self.apply(p, crm)
        self.apply(p, crm)
        self.assertEqual(len(crm.patches), 1)

    def test_new_matching_account_blocks_stale_create(self):
        crm = FakeCRM()
        p = self.seed(crm, "create")
        crm.data["added"] = account("added")
        with self.assertRaises(StaleProposal):
            self.apply(p, crm)
        self.assertEqual(crm.posts, [])

    @patch("bellhaven.review.verify_source", side_effect=StaleProposal("Source changed"))
    def test_website_change_blocks_all_writes(self, verify):
        crm = FakeCRM(account(name="Old name"))
        p = self.seed(crm, "update")
        with self.assertRaises(StaleProposal):
            approve(self.path, p["proposal_id"], crm)
        self.assertEqual(crm.posts + crm.patches, [])

    def test_duplicate_updates_only_loser(self):
        crm = FakeCRM(account("good"), account("copy", phone="5559998888"))
        good = crm.account("good")
        p = self.seed(crm, "duplicate")
        self.apply(p, crm)
        self.assertEqual(crm.account("good"), good)
        self.assertEqual(crm.account("copy")["status"], "Inactive")
        self.assertEqual(crm.account("copy")["duplicate_of_account"], "good")

    @patch("bellhaven.review.verify_source")
    def test_manual_resolution_only_prepares_separate_approvals(self, verify):
        crm = FakeCRM(account("a", parent_id="old", phone="5550001111"),
                      account("b", parent_id="other", phone="5550002222"))
        p = self.seed(crm, "ambiguous_match")
        children = prepare_resolution(self.path, p["proposal_id"], "a", "Both refer to same address; choose a as canonical after review", crm)
        self.assertEqual(crm.posts + crm.patches, [])
        self.assertEqual({p["kind"] for p in children}, {"reparent", "duplicate"})
        with closing(connect(self.path)) as db:
            save_run(db, "daily", [p], {})
            self.assertEqual(len(queue(db)), 2)
        for child in sorted(children, key=lambda p: p["kind"] == "duplicate"):
            self.apply(child, crm)
        self.assertEqual(crm.account("a")["parent_id"], "parent")
        self.assertEqual(crm.account("b")["duplicate_of_account"], "a")


if __name__ == "__main__":
    unittest.main()
