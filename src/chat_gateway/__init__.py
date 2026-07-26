"""chat-gateway — first-class chat identities for agentic applications.

One concern per module:
  envelope.py   — the channel-agnostic message envelope (the ONLY shared shape)
  registry.py   — identities + apps config, env-name indirection for secrets
  auth.py       — per-app API keys
  inbox.py      — inbound-reply queue per app (memory + JSONL audit)
  adapters/     — one delivery/eventing adapter per channel mechanism
  service.py    — the FastAPI surface
  client.py     — stdlib-only client for consuming apps
"""

__version__ = "0.1.0"
