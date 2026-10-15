"""The live registry, swappable at runtime (CG-90).

Every consumer — `create_app`'s routes, the MCP router, `SubscriberLoop`,
`Dispatcher` — was handed ONE `Registry` at boot and keeps that reference for
the life of the process. Passing this holder in its place makes all of them
observe a swap without a signature change: attribute access delegates to
`.current`, which `swap()` replaces with one reference assignment.

The cost, stated (plan deviation 1): a request that makes two registry calls
may see two snapshots if a swap lands between them. Each `Registry` method is
internally consistent and every lookup re-validates, so the worst case is the
request failing as if it had arrived after the swap.

That sentence was NOT true until CG-90 C1: four handlers authenticated against
one snapshot and then subscripted `registry.apps[app_id]` against the next, so
an app deleted in between was a KeyError → 500 rather than the 401 a later
request gets. Each now re-reads with `.get` and answers 401 (`service.live_app`,
`mcp.send_message_schema` / `call_tool`); pinned in tests/test_registry_holder.py.
A new handler that subscripts by the authenticated id re-opens it.
"""

from __future__ import annotations

import threading

from .registry import Registry


class RegistryHolder:
    def __init__(self, registry: Registry):
        self._current = registry
        self._lock = threading.Lock()

    @property
    def current(self) -> Registry:
        return self._current

    def swap(self, new: Registry) -> Registry:
        """Replace the live registry. Returns the one it replaced."""
        with self._lock:
            old, self._current = self._current, new
        return old

    def __getattr__(self, name: str):
        # Only reached for names NOT found on the holder itself. Private and
        # dunder names are refused rather than delegated, so a half-built
        # instance (no `_current` yet) cannot recurse, and protocol probes
        # (`__deepcopy__`, `__len__`) do not silently answer for the Registry.
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._current, name)
