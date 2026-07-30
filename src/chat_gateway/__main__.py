"""Runtime entrypoint + small CLI.

    python3 -m chat_gateway serve       # run the gateway (env-configured)
    python3 -m chat_gateway mint-key    # generate a new per-app API key
    python3 -m chat_gateway check       # load registry, print healthz material

Env (see .env.example): CHAT_GATEWAY_REGISTRY, CHAT_GATEWAY_PORT,
CHAT_GATEWAY_INBOX_DIR, GATEWAY_ENABLE_PUBSUB,
CHAT_GATEWAY_PUBSUB_SUBSCRIPTION, GOOGLE_APPLICATION_CREDENTIALS.
"""

from __future__ import annotations

import json
import os
import sys

from .auth import mint_key
from .inbox import Inbox
from .log_redaction import install_url_redaction
from .registry import RegistryError, load_registry


def build_runtime():
    # CG-34, hard rule #2. Before anything can make an HTTP request: `httpx`
    # logs the full request URL at INFO on every request, and a tier-1 webhook
    # URL embeds key+token. Armed here as well as in `WebhookAdapter.__init__`
    # so the guard does not depend on which adapters this deployment happens to
    # build — a config with no webhook identity still POSTs to tenant callbacks
    # through the same logger. Idempotent, and it redacts rather than silencing;
    # `log_redaction` has the reasoning.
    install_url_redaction()

    registry = load_registry(os.environ.get("CHAT_GATEWAY_REGISTRY", "config/registry.yaml"))
    state_dir = os.environ.get("CHAT_GATEWAY_STATE_DIR", "state")
    inbox = Inbox(audit_dir=os.environ.get("CHAT_GATEWAY_INBOX_DIR", "inbox-data"))

    from .adapters.webhook import WebhookAdapter

    adapters = {"webhook": WebhookAdapter()}
    subscriber = None

    creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    if creds:
        from .adapters.chat_api import ChatApiAdapter, GoogleServiceAccountTokens

        adapters["app"] = ChatApiAdapter(GoogleServiceAccountTokens(creds))

    if os.environ.get("GATEWAY_ENABLE_PUBSUB", "0") == "1":
        sub = os.environ.get("CHAT_GATEWAY_PUBSUB_SUBSCRIPTION", "")
        if not sub or not creds:
            raise RegistryError(
                "GATEWAY_ENABLE_PUBSUB=1 needs CHAT_GATEWAY_PUBSUB_SUBSCRIPTION and "
                "GOOGLE_APPLICATION_CREDENTIALS (docs/google-cloud-setup.md)"
            )
        from .adapters.chat_api import GoogleServiceAccountTokens
        from .adapters.pubsub import PUBSUB_SCOPE, PubSubPuller, SubscriberLoop

        puller = PubSubPuller(sub, GoogleServiceAccountTokens(creds, scope=PUBSUB_SCOPE))
        subscriber = SubscriberLoop(puller, registry, inbox)

    return registry, inbox, adapters, subscriber, state_dir


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else "serve"

    if cmd == "mint-key":
        print(mint_key())
        return 0

    try:
        registry, inbox, adapters, subscriber, state_dir = build_runtime()
    except RegistryError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    if cmd == "check":
        print(json.dumps(registry.health(), indent=2))
        return 0

    if cmd == "serve":
        import uvicorn

        from pathlib import Path

        from .delivery import DeliveryLog
        from .heartbeat import HeartbeatStore
        from .service import create_app

        log = DeliveryLog(audit_dir=Path(state_dir) / "deliveries")
        if subscriber is not None:
            from .forwarder import CallbackForwarder

            chat_adapter = adapters.get("app")
            reply_fn = chat_adapter.send_text if chat_adapter is not None else None
            subscriber.forwarder = CallbackForwarder(log, reply_fn)
            subscriber.reply_fn = reply_fn
            subscriber.start()
        app = create_app(
            registry, inbox, adapters, subscriber,
            delivery_log=log,
            heartbeats=HeartbeatStore(Path(state_dir) / "heartbeats.json"),
        )
        app.state.dispatcher.start()
        app.state.monitor.start()
        uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("CHAT_GATEWAY_PORT", "8085")))
        return 0

    print(f"unknown command {cmd!r} (serve | mint-key | check)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
