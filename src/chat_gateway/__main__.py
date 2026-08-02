"""Runtime entrypoint + small CLI.

    python3 -m chat_gateway serve       # run the gateway (env-configured)
    python3 -m chat_gateway mint-key    # generate a new per-app API key
    python3 -m chat_gateway check       # load registry, print healthz material

Env (see .env.example): CHAT_GATEWAY_REGISTRY, CHAT_GATEWAY_PORT,
CHAT_GATEWAY_INBOX_DIR, CHAT_GATEWAY_INBOX_RETENTION_DAYS,
GATEWAY_ENABLE_PUBSUB, CHAT_GATEWAY_PUBSUB_SUBSCRIPTION,
GOOGLE_APPLICATION_CREDENTIALS.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .auth import mint_key
from .inbox import Inbox
from .journal import Journal
from .log_redaction import install_url_redaction
from .registry import RegistryError, load_registry
from .retention import (RetentionConfigError, RetentionSweeper,
                        retention_days_from_env)


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
    # ONE home for each of these two paths, deliberately: the Inbox WRITES the
    # audit dir and the quarantine dir, and the RetentionSweeper below is
    # constructed against both — one to sweep, one to refuse to sweep. Written
    # twice they could drift apart in a way whose only symptom is a deletion,
    # which is this repo's own recorded lesson about a moving fact with two
    # homes (CLAUDE.md's test count).
    audit_dir = os.environ.get("CHAT_GATEWAY_INBOX_DIR", "inbox-data")
    quarantine_dir = Path(state_dir) / "quarantine"
    # CG-54: the inbox's PENDING QUEUE is journalled here, at
    # construction, rather than attached afterwards — `_journal` is
    # private and assigning it from outside reaches through the class.
    # This is not the audit trail beside it: the audit says what
    # ARRIVED, the journal says what is still UNPOLLED, and passive
    # polling is the only inbound path an opted-out tenant has.
    inbox = Inbox(audit_dir=audit_dir,
                  journal=Journal(Path(state_dir) / "queue" / "inbox.jsonl"),
                  # CG-65: unrevivable replies are preserved here rather than
                  # only pointed at in another file. Under the state dir, beside
                  # the journals, because it is queue-recovery material — not an
                  # audit record of what arrived.
                  quarantine_dir=quarantine_dir)

    # CG-68 / ADR-0002 D5. Sweeps the per-app inbound AUDIT trail only — never
    # the quarantine dir, never the delivery log, never the queue journals.
    #
    # `quarantine_dir` and `state_dir` are passed for ONE reason: so the sweeper
    # can refuse to run if the sweep dir overlaps either (audit F2). Before this,
    # "never the quarantine dir" was true only because these two env vars happen
    # to point at sibling directories, and nothing in the process compared them —
    # one `.env` edit away from deleting the only copy of replies that were never
    # delivered.
    #
    # BOTH, not just the quarantine (pre-merge review, 2026-08-02):
    # `CHAT_GATEWAY_INBOX_DIR=state/deliveries` is a SIBLING of the quarantine,
    # so the narrower check passed and the sweeper pruned the delivery log —
    # a directory the module docstring lists under "what this never touches".
    try:
        sweeper = RetentionSweeper(
            audit_dir,
            days=retention_days_from_env(),
            quarantine_dir=quarantine_dir,
            state_dir=state_dir,
        )
    except RetentionConfigError as exc:
        # Re-raised as the type `main` already handles, so a misconfiguration
        # prints `config error: ...` and exits 2 — the same treatment
        # GATEWAY_ENABLE_PUBSUB's missing-companion check gets, rather than a
        # traceback. Refusing to boot is the SAFE direction here; see the class.
        raise RegistryError(str(exc)) from exc

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

    return registry, inbox, adapters, subscriber, state_dir, sweeper


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else "serve"

    if cmd == "mint-key":
        print(mint_key())
        return 0

    try:
        registry, inbox, adapters, subscriber, state_dir, sweeper = build_runtime()
    except RegistryError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    if cmd == "check":
        print(json.dumps(registry.health(), indent=2))
        return 0

    if cmd == "serve":
        import uvicorn

        from .delivery import DeliveryLog, Dispatcher
        from .heartbeat import HeartbeatStore
        from .service import create_app

        log = DeliveryLog(audit_dir=Path(state_dir) / "deliveries")
        # CG-54: replay BEFORE anything serves or dispatches. `restore`
        # re-resolves every identity through the registry, so a grant
        # withdrawn while the gateway was down closes the job as
        # unroutable instead of sending it on a stale permission
        # (hard rule #4). The counts are echoed at /healthz too — a
        # boot that quietly dropped work is the failure rule #5 exists
        # for, so it must be legible in both places.
        queue_dir = Path(state_dir) / "queue"
        dispatcher = Dispatcher(adapters, log,
                                journal=Journal(queue_dir / "delivery.jsonl"))
        restored, not_restored = dispatcher.restore(registry)
        inbound_restored = inbox.restore()
        print(f"queue: restored {restored} outbound job(s), {not_restored} expired or unroutable; "
              f"{inbound_restored} inbound reply(ies)", flush=True)
        # CG-68. AFTER `inbox.restore()`, never before: restore is what writes
        # the quarantine copy of an unrevivable reply, and a boot line claiming
        # a retention window while that copy is still unwritten would be the
        # tense defect this row exists to close, in the other direction.
        #
        # The boot sweep is the one an operator can see. It is not the whole
        # mechanism — `start()` below is — because a host running
        # `restart: unless-stopped` may not reboot for months, which is the same
        # reasoning journal.py gives for not relying on boot compaction.
        swept = sweeper.sweep()
        print(f"retention: inbox audit window is {sweeper.days} day(s) "
              f"({'pruning DISABLED' if sweeper.days == 0 else 'enabled'}); "
              f"removed {swept} expired day-file(s) at boot", flush=True)
        sweeper.start()
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
            dispatcher=dispatcher,
            heartbeats=HeartbeatStore(Path(state_dir) / "heartbeats.json"),
            sweeper=sweeper,
        )
        app.state.dispatcher.start()
        app.state.monitor.start()
        uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("CHAT_GATEWAY_PORT", "8085")))
        return 0

    print(f"unknown command {cmd!r} (serve | mint-key | check)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
