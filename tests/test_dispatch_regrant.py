"""CG-90 Task 3. A grant withdrawn while a job is queued closes the job as
`unroutable` instead of sending it on a stale permission (hard rule #4) — the
rule `restore` already applies at boot, now applied at every send."""
from chat_gateway.delivery import DeliveryLog, Dispatcher
from chat_gateway.envelope import OutboundMessage
from chat_gateway.registry import App, Identity, Registry
from chat_gateway.registry_holder import RegistryHolder


class _Rec:
    def __init__(self):
        self.sent = []

    def send(self, identity, message):
        self.sent.append(identity.name)
        return {"status": "delivered"}


def _registry(granted: bool) -> Registry:
    ident = Identity(name="i1", display="d", webhook_url_env="W")
    apps = {"a1": App(app_id="a1", key_env="K", identities=["i1"] if granted else [])}
    return Registry(identities={"i1": ident}, apps=apps)


def test_withdrawn_grant_closes_the_job_unroutable_and_does_not_send():
    holder = RegistryHolder(_registry(True))
    log, adapter = DeliveryLog(), _Rec()
    d = Dispatcher({"webhook": adapter}, log, registry=holder)
    d.enqueue("a1", "notify", holder.identity_for("a1", "i1"),
              OutboundMessage(identity="i1", text="hi"), "t")
    holder.swap(_registry(False))
    d.process_due()
    assert adapter.sent == []
    assert d.pending() == 0
    assert d.unroutable_live == 1
    assert log.query("a1")[-1]["status"] == "unroutable"


def test_a_still_granted_job_sends_as_before():
    holder = RegistryHolder(_registry(True))
    adapter = _Rec()
    d = Dispatcher({"webhook": adapter}, DeliveryLog(), registry=holder)
    d.enqueue("a1", "notify", holder.identity_for("a1", "i1"),
              OutboundMessage(identity="i1", text="hi"), "t")
    d.process_due()
    assert adapter.sent == ["i1"]
    assert d.unroutable_live == 0


def test_no_registry_keeps_the_old_behaviour():
    adapter = _Rec()
    d = Dispatcher({"webhook": adapter}, DeliveryLog())
    reg = _registry(True)
    d.enqueue("a1", "notify", reg.identity_for("a1", "i1"),
              OutboundMessage(identity="i1", text="hi"), "t")
    d.process_due()
    assert adapter.sent == ["i1"]
