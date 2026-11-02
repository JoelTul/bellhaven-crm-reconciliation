from contextlib import closing
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from bellhaven.matching import build_proposals
from bellhaven.store import connect, save_run
from test_pipeline import account, LOCATION
from test_review import FakeCRM


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.crm = FakeCRM(account(name="Old name"))
        proposals, _ = build_proposals([LOCATION], self.crm.accounts())
        with closing(connect(self.path / "review.sqlite3")) as db:
            save_run(db, "first", proposals, {})
        self.environment = patch.dict(os.environ, {"BELLHAVEN_DATA_DIR": str(self.path), "BELLHAVEN_API_TOKEN": ""})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def button(self, app, label):
        return next(button for button in app.button if button.label == label)

    def test_rejection_persists_from_ui_without_crm_calls(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run()
        self.assertFalse(app.exception)
        self.assertTrue(self.button(app, "Approve and apply to CRM").disabled)
        app.text_area[0].set_value("Insufficient evidence; keep current record").run()
        self.button(app, "Reject proposal").click().run()
        self.assertFalse(app.exception)
        self.assertEqual([metric.value for metric in app.metric], ["0", "0", "1", "0"])
        self.assertEqual(self.crm.posts + self.crm.patches, [])

    @patch("bellhaven.review.verify_source")
    def test_approval_requires_confirmation_and_verifies_write(self, verify):
        with patch("bellhaven.crm.CRM", return_value=self.crm):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run()
            app.text_input[0].set_value("fake-test-token").run()
            self.assertTrue(self.button(app, "Approve and apply to CRM").disabled)
            app.checkbox[0].check().run()
            self.assertFalse(self.button(app, "Approve and apply to CRM").disabled)
            self.button(app, "Approve and apply to CRM").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(self.crm.account("facility")["name"], LOCATION["name"])
            self.assertEqual([metric.value for metric in app.metric], ["0", "1", "0", "0"])
            self.assertEqual(len(self.crm.patches), 1)
            verify.assert_called_once()


if __name__ == "__main__":
    unittest.main()
