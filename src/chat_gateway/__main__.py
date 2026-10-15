"""Runtime entrypoint + small CLI.

    python3 -m chat_gateway serve       # run the gateway (env-configured)
    python3 -m chat_gateway mint-key    # generate a new per-app API key
    python3 -m chat_gateway check       # load registry, print healthz material

Env (see .env.example): CHAT_GATEWAY_ENV_FILE, CHAT_GATEWAY_REGISTRY,
CHAT_GATEWAY_PORT, CHAT_GATEWAY_INBOX_DIR, CHAT_GATEWAY_INBOX_RETENTION_DAYS,
CHAT_GATEWAY_STATE_DIR, GATEWAY_ENABLE_PUBSUB, GATEWAY_ENABLE_MCP,
CHAT_GATEWAY_MCP_ALLOWED_ORIGINS, GATEWAY_ENABLE_ADMIN, CHAT_GATEWAY_ADMIN_KEY,
CHAT_GATEWAY_PUBSUB_SUBSCRIPTION, GOOGLE_APPLICATION_CREDENTIALS.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .auth import mint_key
from .env_file import EnvFileError
from .inbox import Inbox
from .journal import Journal
from .log_redaction import install_url_redaction
from .registry import RegistryError, load_registry
from .registry_holder import RegistryHolder
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

    # Deployment seam (hard rule #2). On the NAS every secret lives in an
    # off-repo file mode 600 that the compose document only NAMES, so nothing
    # secret is ever in the compose — see env_file.py for the capture-script
    # suffix gap that makes this structural rather than stylistic. Before
    # load_registry, which resolves env-indirected names. Unset on the dev box
    # and in tests, where this is a no-op.
    #
    # CG-90. Snapshot the REAL process environment before any file touches it:
    # a name in here beats every file at every boot, so the console must refuse
    # to manage it rather than write a value that would be ignored.
    admin_enabled = os.environ.get("GATEWAY_ENABLE_ADMIN", "0") == "1"
    process_env_names = frozenset(os.environ)
    # managed.env has to be found BEFORE the hand-written env file loads, so
    # its directory is resolved from the PROCESS env here. That is the only
    # read of CHAT_GATEWAY_STATE_DIR this early; `state_dir` itself is read
    # after the env file, below, exactly where it was before CG-90 (final
    # review I4 — reading it here changed where an admin-OFF gateway put its
    # queue journals whenever the env file was the one setting it).
    managed_dir = os.environ.get("CHAT_GATEWAY_STATE_DIR", "state")
    managed_path = Path(managed_dir) / "managed.env"
    managed = None
    # CG-90 final review I3: whenever the file EXISTS, not only when the
    # console is on. Turning the console off used to skip this load, and the
    # hand .env's older value of every console-rotated key — the key the
    # rotation was meant to kill — came back to life at the next boot. On a
    # gateway that never ran the console there is no file, so that boot is
    # unchanged. Disabling the console therefore KEEPS its keys; revoking them
    # is a rotate/delete before disabling, or removing managed.env
    # (docs/deploy/nas.md, CG-90 subsection).
    if admin_enabled or managed_path.exists():
        from .managed_secrets import ManagedSecrets

        managed = ManagedSecrets(managed_path, process_env_names=process_env_names)
        # BEFORE the hand-written env file: `load_env_file` lets a present value
        # win, so this order is what makes a console-rotated key survive a boot.
        # A count, never a name or a value.
        print(f"admin: loaded {managed.load_at_boot()} managed secret(s)"
              + ("" if admin_enabled else " (console off; managed.env still applies)"),
              flush=True)

    env_file = os.environ.get("CHAT_GATEWAY_ENV_FILE", "")
    if env_file:
        from .env_file import load_env_file, parse_env_file

        print(f"env: loaded {load_env_file(env_file)} key(s) from {env_file}", flush=True)
        if managed is not None:
            # Names only — which of the console's secrets this file also sets,
            # so /healthz and the page can say "managed.env shadows .env".
            managed.hand_env_names = frozenset(
                parse_env_file(Path(env_file).read_text(encoding="utf-8-sig")))

    # CG-90. A holder, not the bare Registry: every consumer built below keeps
    # this one reference for the life of the process, and the holder is what
    # lets the admin console swap the registry underneath all of them at once.
    registry = RegistryHolder(
        load_registry(os.environ.get("CHAT_GATEWAY_REGISTRY", "config/registry.yaml")))
    # CG-88. `allow_inbound` now defaults to DENY, and an app that inherits it
    # is named here rather than refused. The refusal was the alternative and it
    # was declined: of the three registry copies, the NAS one cannot be read
    # from here (docs/consumers/pmtrader-registration-handoff.md §6), so
    # "required, no default" would have bet the service on a file nobody can
    # read. ⚠ ONE copy, not two — corrected in pre-merge review. The dev-box
    # `config/registry.yaml` is gitignored, so it is absent from a fresh clone,
    # but it is present and readable on this machine and it WAS read. This is the half of that shape which cannot cause an outage BY
    # OMISSION ALONE — annotated 2026-08-31 in pre-merge review, because the
    # unqualified sentence is false: at `registry.py:400`, omission PLUS a
    # `callback_url` trips rule #6's validation and the gateway exits 2. Every
    # other site carrying this claim was annotated a commit earlier; this one
    # was missed, which is the two-homes defect arriving inside the fix for it.
    #
    # stderr, not stdout: `check` writes machine-readable JSON to stdout one
    # branch below, and a warning that lands in a `| jq` pipeline is a warning
    # somebody silences. Silent when the list is empty — the always-on channel
    # is `registry.health()`, which reports `inbound_defaulted: []` on every
    # `/healthz` and every `check`, so absence of this line is never the only
    # evidence.
    if registry.inbound_defaulted:
        print(
            "registry: WARNING — allow_inbound is not written for: "
            f"{', '.join(registry.inbound_defaulted)}. "
            "The default is DENY (hard rule #6); write the key explicitly so "
            "the posture is the file's rather than the loader's.",
            file=sys.stderr, flush=True,
        )
    state_dir = os.environ.get("CHAT_GATEWAY_STATE_DIR", "state")

    admin = None
    if admin_enabled:
        from .admin import AdminWiring
        from .admin_audit import AdminAudit
        from .registry import ADMIN_KEY_ENV
        from .registry_store import RegistryStore

        # Fail closed at boot, the GATEWAY_ENABLE_PUBSUB posture: an armed
        # console with no key would 401 every request, which reads as "wrong
        # key" to the operator rather than "never configured".
        if not os.environ.get(ADMIN_KEY_ENV):
            raise RegistryError(
                f"GATEWAY_ENABLE_ADMIN=1 needs {ADMIN_KEY_ENV} (mint one with "
                "`python -m chat_gateway mint-key`; docs/deploy/nas.md)")
        # CG-90 final review I4. managed.env was located before the env file
        # loaded; if that file then set (or moved) the state dir, the console
        # would write its secrets in one directory and its audit, queues and
        # quarantine in another — and the next boot would look for managed.env
        # in the wrong one. Refuse rather than pick. Paths are not secrets.
        if Path(managed_dir) != Path(state_dir):
            raise RegistryError(
                f"GATEWAY_ENABLE_ADMIN=1 but CHAT_GATEWAY_STATE_DIR is {managed_dir!r} in the "
                f"process environment and {state_dir!r} after CHAT_GATEWAY_ENV_FILE loaded; "
                "managed.env is read before that file, so set CHAT_GATEWAY_STATE_DIR in the "
                "process environment (the compose document) instead")
        store = RegistryStore(Path(os.environ.get("CHAT_GATEWAY_REGISTRY",
                                                  "config/registry.yaml")),
                              registry, managed)
        store.probe_writable()
        admin = AdminWiring(
            store=store,
            secrets=managed,
            audit=AdminAudit(Path(state_dir) / "admin_audit.jsonl"))
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

    return registry, inbox, adapters, subscriber, state_dir, sweeper, admin


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else "serve"

    if cmd == "mint-key":
        print(mint_key())
        return 0

    try:
        registry, inbox, adapters, subscriber, state_dir, sweeper, admin = build_runtime()
    except (RegistryError, EnvFileError) as exc:
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
                                journal=Journal(queue_dir / "delivery.jsonl"),
                                registry=registry)
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
            # CG-80. Default OFF, the posture GATEWAY_ENABLE_PUBSUB set for a
            # new surface. Unlike that flag this one has NO companion
            # requirement — it needs no credential, so there is nothing to fail
            # closed on and no startup check to add.
            mcp_enabled=os.environ.get("GATEWAY_ENABLE_MCP", "0") == "1",
            # CG-90. Built (or not) by build_runtime, which already refused to
            # boot an armed console with no admin key.
            admin=admin,
        )
        app.state.dispatcher.start()
        app.state.monitor.start()
        uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("CHAT_GATEWAY_PORT", "8085")))
        return 0

    print(f"unknown command {cmd!r} (serve | mint-key | check)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
