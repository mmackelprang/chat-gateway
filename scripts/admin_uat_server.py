# scripts/admin_uat_server.py
"""Local UAT gateway for the admin console (CG-90). Fake webhook adapter, a
temp registry, admin enabled. Not a deployment path. Prints the admin key."""
import os
import sys
import tempfile
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chat_gateway.admin import AdminWiring, admin_auth_posture  # noqa: E402
from chat_gateway.admin_audit import AdminAudit  # noqa: E402
from chat_gateway.envelope import DeliveryResult  # noqa: E402
from chat_gateway.inbox import Inbox  # noqa: E402
from chat_gateway.managed_secrets import ManagedSecrets  # noqa: E402
from chat_gateway.registry import load_registry  # noqa: E402
from chat_gateway.registry_holder import RegistryHolder  # noqa: E402
from chat_gateway.registry_store import RegistryStore  # noqa: E402
from chat_gateway.service import create_app  # noqa: E402


class FakeWebhook:
    def send(self, identity, message):
        print(f"[fake webhook] {identity.name}: {message.text[:60]!a}", flush=True)
        return DeliveryResult(status="delivered", channel="google_chat",
                              identity=identity.name, mode=identity.mode)


tmp = Path(tempfile.mkdtemp(prefix="cg-admin-uat-"))
reg = tmp / "registry.yaml"
reg.write_text("""# UAT registry
identities:
  ops:
    display: Ops
    webhook_url_env: UAT_W_OPS
    space: spaces/UATOPS
apps:
  trader:
    key_env: UAT_K_TRADER
    identities: [ops]
    allow_inbound: false   # hard rule #6
    inbound_locked: true
    routes: {default: ops}
""", encoding="utf-8")
os.environ.update({"CHAT_GATEWAY_ADMIN_KEY": "cgk_uat_admin", "UAT_K_TRADER": "cgk_uat_trader",
                   "UAT_W_OPS": "https://chat.googleapis.com/v1/spaces/UATOPS/messages?key=k&token=t"})
posture = admin_auth_posture(os.environ.get("GATEWAY_ADMIN_AUTH"))
holder = RegistryHolder(load_registry(reg))
secrets = ManagedSecrets(tmp / "state" / "managed.env",
                         process_env_names=frozenset({"CHAT_GATEWAY_ADMIN_KEY"}))
wiring = AdminWiring(store=RegistryStore(reg, holder, secrets), secrets=secrets,
                     audit=AdminAudit(tmp / "state" / "admin_audit.jsonl", auth=posture),
                     auth=posture)
app = create_app(holder, Inbox(), {"webhook": FakeWebhook()}, admin=wiring)
app.state.dispatcher.start()
auth_line = "admin auth: open" if posture == "open" else "admin auth: key — admin key: cgk_uat_admin"
print(f"UAT dir: {tmp}\n{auth_line}\nopen http://127.0.0.1:8099/admin", flush=True)
uvicorn.run(app, host="127.0.0.1", port=8099)
