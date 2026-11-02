"""API writes are used only by the explicitly approved review action."""
import requests

from .source import DEFAULT_BASE, fetch_accounts, get


class CRM:
    def __init__(self, token, base=DEFAULT_BASE):
        if not token.strip():
            raise ValueError("A CRM token is required to apply changes")
        if not base.startswith("https://"):
            raise ValueError("CRM base must use HTTPS")
        self.token, self.base = token.strip(), base.rstrip("/")

    def accounts(self):
        return fetch_accounts(self.token, self.base)

    def account(self, account_id):
        return get(f"{self.base}/api/v1/accounts/{account_id}", self.token).json()

    def contacts(self, account_id):
        records, page = [], 1
        while True:
            body = get(self.base + "/api/v1/contacts", self.token,
                       {"account_id": account_id, "page": page, "page_size": 50}).json()
            records.extend(body["data"])
            if len(records) == body["total"]:
                return records
            if not body["data"] or len(records) > body["total"]:
                raise ValueError("Incomplete contact inventory")
            page += 1

    def _write(self, method, path, payload):
        # No automatic POST/PATCH retries. An interrupted POST must be reconciled
        # by its durable marker instead of blindly sending another create.
        response = requests.request(method, self.base + path, json=payload,
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=(10, 30), allow_redirects=False)
        if not 200 <= response.status_code < 300:
            raise RuntimeError(f"CRM {method} returned HTTP {response.status_code}; inspect before retrying")
        value = response.json()
        return value.get("data", value) if isinstance(value, dict) else value

    def create(self, payload):
        return self._write("POST", "/api/v1/accounts", payload)

    def update(self, account_id, payload):
        return self._write("PATCH", f"/api/v1/accounts/{account_id}", payload)
