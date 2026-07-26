"""Stdlib-only client for consuming applications — vendor this single file or
pip-install the package; either way, no dependencies beyond Python 3.10+.

    from chat_gateway.client import GatewayClient

    gw = GatewayClient("http://appserver:8085", api_key=os.environ["CHAT_GATEWAY_API_KEY"])
    gw.send("pm-familyworkspace",
            text="Review needed: deploy gate for v2.4",
            thread_key="review-PC-12")
    for reply in gw.poll_inbox():
        handle(reply)   # dicts with app/space/thread_key/sender_display/text/raw
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class GatewayError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


class GatewayClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self._key = api_key
        self._timeout = timeout

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers={
                "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("detail", "")
            except Exception:  # noqa: BLE001
                detail = exc.reason or ""
            raise GatewayError(exc.code, str(detail)) from exc

    def send(self, identity: str, text: str, cards: list[dict[str, Any]] | None = None,
             thread_key: str | None = None) -> dict:
        return self._request("POST", "/v1/messages", {
            "identity": identity,
            "text": text,
            "cards": cards or [],
            "thread_key": thread_key,
        })

    def poll_inbox(self) -> list[dict]:
        return self._request("GET", "/v1/inbox").get("replies", [])

    def identities(self) -> list[dict]:
        return self._request("GET", "/v1/identities").get("identities", [])

    # -- notifications + dead-man checks (accept-fast; see integration guide) --

    def notify(self, severity: str, title: str, body: str = "", action: str = "",
               dedupe_key: str | None = None, thread_key: str | None = None) -> dict:
        return self._request("POST", "/v1/notify", {
            "severity": severity, "title": title, "body": body, "action": action,
            "dedupe_key": dedupe_key, "thread_key": thread_key,
        })

    def heartbeat(self, check_id: str, schedule: str, grace: str,
                  tz: str | None = None) -> dict:
        body: dict[str, Any] = {"check_id": check_id, "schedule": schedule, "grace": grace}
        if tz:
            body["tz"] = tz
        return self._request("POST", "/v1/heartbeat", body)

    def heartbeat_status(self, source: str) -> dict:
        return self._request("GET", f"/v1/heartbeat/{source}")

    def delete_heartbeat(self, source: str, check_id: str) -> dict:
        return self._request("DELETE", f"/v1/heartbeat/{source}/{check_id}")

    def deliveries(self, limit: int = 50) -> list[dict]:
        return self._request("GET", f"/v1/deliveries?limit={limit}").get("deliveries", [])
