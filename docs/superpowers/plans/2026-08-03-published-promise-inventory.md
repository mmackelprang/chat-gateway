# CG-69 — a published-promise inventory: implementation plan

**Spec:** [`2026-08-03-published-promise-inventory-design.md`](../specs/2026-08-03-published-promise-inventory-design.md)
**Baseline:** `main` at `d09a07c`, suite **345 passing** (re-measured, not copied).
**Branch:** `docs/cg-69-promise-inventory` → implementation branch is Builder's choice.

**No ⚠ verification-ledger flag is cleared, added or reworded by any task here.**
Nothing touches a Google seam. `docs/architecture/` is **not edited** — and per
spec §6 it is also not guarded.

**One property holds across every task: no published promise is amended.** Task 1
changes *pointers*; Tasks 2-6 add tests and a template field. If a task finds
itself rewording a claim, it has gone wrong — stop and file a row.

**Task order is load-bearing.** Task 1 before Task 2: Task 2 goes red on the
current tree by design, and a guard that lands red is a guard someone deletes.

**Every helper below was executed against `d09a07c` before this plan was
written** — in the session scratchpad, not in the repo — and the results are the
numbers quoted in each task:

| Helper | Result on the real tree |
|---|---|
| `LINE_CITE` over the guarded set | **15** hits — the 14 `.py` citations of spec §2.2 plus `CLAUDE.md:118`'s `.md` one. Task 1's table is exactly this list |
| `_qualnames` against all 15 proposed anchors | **15/15 resolve**, 0 failures |
| `ANCHOR` round-trip on the proposed replacement text | parses, including the nested `create_app.list_heartbeats` form |
| `_removal_sites()` | `{'retention.py': {'RetentionSweeper._sweep_dir'}}` — exactly the pinned value |
| `_env_dir_defaults()` | `{'CHAT_GATEWAY_STATE_DIR': 'state', 'CHAT_GATEWAY_INBOX_DIR': 'inbox-data'}`, both `.gitignore`-covered |

**Task 6's helpers were NOT executed** — they need a fixture that does not exist
yet. That asymmetry is why Task 6 is droppable and why its numbers carry a
re-measure warning and the others do not.

---

## Task 1 — repair the 14 code citations in the live contract documents

**Files:** `docs/consumers/aitrader.md`, `CLAUDE.md`. (`jobhunt.md`,
`jobhunt-handoff.md` and `integration-guide.md` carry **zero** `.py:LINE`
citations — verified; do not go looking.)

Replace each line-number citation with the symbol anchor. **Every qualified name
below was resolved by `ast` against `d09a07c`, not read by eye.** Spec §2.2 has
the audit that produced the "wrong" column.

| # | Site | Current text | Replace with | Status |
|---|---|---|---|---|
| 1 | `aitrader.md:37` | `` `auth.py:22-38` `` | `` `auth.py::authenticate` `` | was correct |
| 2 | `aitrader.md:42` | `` `notifications.py:35-52` `` | `` `notifications.py::Notification` `` | **was wrong** |
| 3 | `aitrader.md:93` | `` `service.py:215-216, 227-228` `` | `` `service.py::create_app.list_heartbeats` / `create_app.delete_heartbeat` `` | **was wrong** |
| 4 | `aitrader.md:106` | `` `registry.py:148-159` `` | `` `registry.py::Registry.route_for` `` | was correct |
| 5 | `aitrader.md:125` | `` `notifications.py:55-78` `` | `` `notifications.py::render` `` | **was wrong** |
| 6 | `aitrader.md:154` | `` `notifications.py:81-108` `` | `` `notifications.py::Deduper` `` | **was wrong** |
| 7 | `aitrader.md:210` | `` `delivery.py:78-100` `` | `` `delivery.py::DeliveryLog.record` `` | marginal |
| 8 | `aitrader.md:276` | `` `heartbeat.py:75-85` `` | `` `heartbeat.py::Check.next_due` `` | was correct |
| 9 | `aitrader.md:334` | `` `service.py:242-247` `` | `` `service.py::create_app.poll_inbox` `` | **was wrong** |
| 10 | `aitrader.md:335` | `` `registry.py:272-276` `` | `` `registry.py::load_registry` `` | was correct |
| 11 | `aitrader.md:336` | `` `adapters/pubsub.py:648-660` `` | `` `adapters/pubsub.py::dispatch` `` | **was wrong** |
| 12 | `aitrader.md:337` | `` `service.py:85-88` `` | `` `service.py::_interaction_config` `` | **was wrong** |
| 13 | `aitrader.md:371` | `` `registry.py:161-172` `` | `` `registry.py::Registry.apps_for_space` `` | was correct |
| 14 | `CLAUDE.md:328` | `` `adapters/pubsub.py:376` `` | `` `adapters/pubsub.py::_resolve_action_id` `` | **was wrong** |

**One markdown citation, and it is also stale:**

| 15 | `CLAUDE.md:118` | `` `docs/integration-guide.md:366` `` | `` [`docs/integration-guide.md` § *A gateway restart no longer drops your unpolled replies*](docs/integration-guide.md#a-gateway-restart-no-longer-drops-your-unpolled-replies) `` |

`:366` is a blank line at `d09a07c`; the amended retention sentence is at `:375`,
under that heading.

⚠ **Rows 9, 11 and 12 are three of the four enforcement points in
`aitrader.md` §8's hard-rule-#6 table.** Read the surrounding sentence before
editing each: the anchor must name the code that performs *that* enforcement,
not merely code that is nearby. Row 3 needs **two** anchors because the sentence
cites two endpoints.

⚠ **Do not touch the prose.** Only the backticked citation changes.

⚠ **The bare test-name citations stay bare, and that is a decision.**
`integration-guide.md`, `jobhunt-handoff.md` and `CLAUDE.md` cite four test
functions by name — `test_card_parameters_are_an_array_in_the_real_captured_card`
and three others — in eight places. Converting them to
`` `tests/test_adapters.py::…` `` would bring them under Task 2's guard, and it
is **not** done here: measured across the same window that rotted 8 of 14 line
citations, those eight are **0 for 8 wrong**, so there is no defect to fix and
the change would cost eight edits to prose that reads well. If a test rename
ever breaks one, that is the moment to convert — not before.

**Verify:**

```bash
grep -rnoE "[a-z_]+(/[a-z_]+)?\.py:[0-9]+" docs/consumers/ docs/integration-guide.md CLAUDE.md
grep -rnoE "[A-Za-z0-9._-]+\.md:[0-9]+" docs/consumers/ docs/integration-guide.md CLAUDE.md
```

Both must print **nothing**.

---

## Task 2 — the anchor guard

**New file: `tests/test_published_promises.py`.**

```python
"""The promises this repo publishes, and the code that is supposed to keep them.

CG-69. Three different claims are pinned here and they are three different
kinds:

1. **every code reference in a live contract document resolves to a real
   symbol** — a structural check over `ast`, because the line-number form these
   documents used until this row was measurably 8/14 wrong;
2. **the set of filesystem paths this package can DELETE** — because
   *"never pruned"* and *"the only copy"* are claims about that set, and it has
   had exactly one member in this repo's history;
3. **every tenant-data directory the runtime defaults to is `.gitignore`d** —
   because #45 moved message bodies into `state/` while the ignore rule still
   tracked where they used to be, and nothing noticed.

**What this file deliberately does NOT do: read a claim for meaning.** Nothing
here parses English, nothing greps for `never`, and no assertion is about the
text of a promise. A sentence may be rewritten, softened, moved or deleted
without turning any of this red. That is not a limitation, it is the design:
the same promise family (*"never pruned"* / *"the only copy"*) has **93**
occurrences across this repo and only **7** of them are live tenant contract —
the rest are ADR-0002, the retention plan, and shipped queue rows, all of which
this repo keeps verbatim on purpose. A text-keyed guard could not tell those
apart and would be deleted within a week, which is the failure mode
`tests/test_fixtures_scrubbed.py` already names in its own scope note.

The prose obligation therefore lives in the **assertion messages**, exactly as
`tests/test_error_surfaces.py` puts *"confirm the new expression carries a NAME
or an HTTP STATUS"* in its. That file is the idiom this one borrows: read the
source, pin a small set, and say in the failure what a human now has to go read.
"""

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "chat_gateway"


# ---------------------------------------------------------------------------
# 1. Code references in the live contract documents
# ---------------------------------------------------------------------------

# The guarded set, and the absences are decisions (spec §6). `docs/consumers/`
# is a glob so a fifth tenant is covered the day its file appears.
#
# NOT guarded, on purpose: `docs/superpowers/specs/**` and `plans/**` are dated
# design records whose wording this repo leaves standing after it stops being
# true — a false sentence found in a spec at CG-74's review was deliberately not
# edited, recorded as "Planner's artifact", and is still there. A guard on that
# tree would demand editing history to go green. `docs/architecture/` is the
# same, one degree stronger. `docs/BUILDER_QUEUE.md` is shipped rows.
# `docs/google-cloud-setup.md` holds console facts no in-repo test can verify.
GUARDED_FILES = ("docs/integration-guide.md", "CLAUDE.md")
GUARDED_GLOBS = (("docs/consumers", "*.md"),)


def _guarded() -> list[Path]:
    paths = [REPO / name for name in GUARDED_FILES]
    for directory, pattern in GUARDED_GLOBS:
        paths.extend((REPO / directory).glob(pattern))
    return sorted(paths)


# `module.py::Qualified.Name`. The module path is relative to
# `src/chat_gateway/`, except under `tests/`, which resolves from the repo root
# — both forms already appear in this repo's working documents.
ANCHOR = re.compile(
    r"`((?:[a-z_][a-z0-9_]*/)*[a-z_][a-z0-9_]*\.py)::"
    r"([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)`")

# The form this row retires. Deliberately NOT requiring a backtick: `CLAUDE.md`
# cites one in running prose, and a rule that only saw the fenced form would
# have missed it.
LINE_CITE = re.compile(r"\b([A-Za-z0-9._/-]+\.(?:py|md)):(\d+)")

_PARSED: dict[Path, ast.Module] = {}


def _tree(py: Path) -> ast.Module:
    if py not in _PARSED:
        _PARSED[py] = ast.parse(py.read_text(encoding="utf-8"))
    return _PARSED[py]


def _qualnames(py: Path) -> set[str]:
    """Every dotted name a reader could legitimately anchor to in `py`.

    Nested scopes included — `service.py`'s route handlers are all closures
    inside `create_app`, so `create_app.poll_inbox` is the ONLY honest anchor
    for the `/v1/inbox` 403 and a top-level-only walker could not express it.

    Module-level assignments are names too (`notifications.py::SEVERITY_EMOJI`),
    because a doc quoting a constant is making a claim about that constant.
    """
    names: set[str] = set()

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef)):
                qual = prefix + child.name
                names.add(qual)
                walk(child, qual + ".")
                continue
            if prefix == "":
                targets = ([child.target] if isinstance(child, ast.AnnAssign)
                           else child.targets if isinstance(child, ast.Assign)
                           else [])
                names.update(t.id for t in targets if isinstance(t, ast.Name))
            # Keep descending at the SAME prefix through everything that is not
            # a def: a class or function inside an `if`/`try` block is still
            # reachable by its plain dotted name, and a walker that only ever
            # recursed through defs would silently fail to resolve it — which
            # this guard would report as "the doc is wrong" about code that is
            # right, the one failure direction it must not have.
            walk(child, prefix)

    walk(_tree(py), "")
    return names


def _module_for(rel: str) -> Path:
    return REPO / rel if rel.startswith("tests/") else SRC / rel


def _anchors() -> list[tuple[Path, int, str, str]]:
    out = []
    for doc in _guarded():
        for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            for match in ANCHOR.finditer(line):
                out.append((doc, lineno, match.group(1), match.group(2)))
    return out


def test_every_code_reference_in_a_published_contract_resolves():
    """A pointer into code that points at the wrong code is worse than none.

    Measured before this guard existed: of the 14 `file.py:LINE` citations in
    these documents, **8 pointed at unrelated code** — including three of the
    four enforcement points `aitrader.md` lists under hard rule #6, which is the
    contract clause a real-money tenant treats as a security guarantee. The
    name-anchored citations in the same files, over the same window, were 0/8
    wrong. The form is the whole difference, and this test is what keeps it.
    """
    complaints = []
    for doc, lineno, rel, qual in _anchors():
        module = _module_for(rel)
        where = f"{doc.relative_to(REPO).as_posix()}:{lineno}"
        if not module.exists():
            complaints.append(f"{where}: no module {rel!r}")
            continue
        if qual not in _qualnames(module):
            complaints.append(f"{where}: {rel}::{qual} does not exist")

    assert not complaints, (
        "A published document points at code that is not there.\n\n"
        + "\n".join(f"  - {c}" for c in complaints)
        + "\n\nThis is a TENANT-FACING pointer, so the fix is never to delete "
          "the anchor. Find where the symbol went, read the sentence that "
          "cites it, and confirm the sentence is still true of the new "
          "location — a rename is exactly the moment a promise about that code "
          "needs re-reading. Then update the anchor.")


def test_no_line_number_citation_survives_in_a_published_contract():
    """The retired form, kept retired.

    Without this the old form creeps straight back and the guard above reports
    the converted subset as though it were the whole set — green, and blind to
    however many citations arrived last week.

    A line number is not banned because it is imprecise. It is banned because it
    is SILENTLY imprecise: `service.py:242-247` still resolves to real, readable
    code after the thing it described moved 141 lines away, so nothing — not a
    reader, not a reviewer, not a test — can tell it has stopped being true.
    """
    # finditer, not search. On the tree this landed against it makes no
    # difference — every one of the 15 sites is alone on its line, and
    # `aitrader.md:93`'s `service.py:215-216, 227-228` is ONE match because the
    # second range carries no filename. Used anyway because a first-match rule
    # fails in the direction that goes quiet: it reports one citation, sees it
    # fixed, and turns green with a second still standing on the same line.
    complaints = [
        f"{doc.relative_to(REPO).as_posix()}:{lineno}: {m.group(0)!r}"
        for doc in _guarded()
        for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1)
        for m in LINE_CITE.finditer(line)
    ]
    assert not complaints, (
        "A published document cites a line number.\n\n"
        + "\n".join(f"  - {c}" for c in complaints)
        + "\n\nUse `module.py::Qualified.Name` instead — the convention this "
          "repo already uses 45 times in its working documents. For a markdown "
          "target use a heading link. If what you need to point at genuinely "
          "has no name, that is worth knowing: give it one, or point at the "
          "enclosing scope and say which part you mean in words.")


def test_the_anchor_guard_is_actually_reading_something():
    """A guard that inspects nothing passes everything.

    Pinned per file rather than as a total, so that deleting every anchor from
    one document cannot be hidden by adding anchors to another. Same reason
    `test_error_surfaces.py` pins its construction-site count.

    These numbers are expected to CHANGE — every row that adds a citation moves
    one. Updating them is a one-line edit and is not a failure; what is a
    failure is a count going DOWN without anybody deciding it should.
    """
    per_doc: dict[str, int] = {}
    for doc, _, _, _ in _anchors():
        key = doc.relative_to(REPO).as_posix()
        per_doc[key] = per_doc.get(key, 0) + 1
    assert per_doc == {
        "CLAUDE.md": 1,
        "docs/consumers/aitrader.md": 14,
    }
```

⚠ **The count in `test_the_anchor_guard_is_actually_reading_something` is a
prediction, not a measurement** — it assumes Task 1 lands exactly the 15
replacements in its table, with row 3 producing two anchors on one line and
row 15 producing a markdown link rather than a `::` anchor. **Builder must run
the guard and pin what it actually finds**, then check the number against Task
1's table and reconcile any difference before moving on. A count taken from this
plan rather than from the tree is the defect this whole row is about.

**Verify:** `python3 -m pytest tests/test_published_promises.py -q` — 3 passing.

---

## Task 3 — the delete-site pin

Append to `tests/test_published_promises.py`:

```python
# ---------------------------------------------------------------------------
# 2. What this package can DELETE
# ---------------------------------------------------------------------------

# Matched as attribute calls, because that is what the real sites are and
# because a bare-name rule is unsafe here: `remove` alone also matches
# `self._jobs.remove(job)` at `delivery.py:401` and `forwarder.py:120`, two
# list operations with nothing to do with the filesystem. `os.remove` is
# therefore admitted only through its `os.` receiver.
REMOVAL_ATTRS = {"unlink", "rmdir", "rmtree", "removedirs"}
OS_ONLY_ATTRS = {"remove"}

# NOT counted, and this is a decision rather than an oversight: `os.replace`
# (`journal.py:284`) and `Path.replace` (`heartbeat.py:127`) destroy the
# previous contents of a file. They are the atomic-rewrite primitive that
# journal compaction and heartbeat persistence are BUILT ON — CG-65's whole
# retention improvement is a compaction — so they run constantly and would make
# this pin fire on every durability change. A set that fires every week is a set
# nobody reads. What covers that ground instead is ADR-0002's decisions plus
# `tests/test_journal.py`; what this pin covers is the thing that had never
# happened before CG-68 and has happened once since: deleting a tenant's file.

#: module -> the qualified scopes that can remove a path. Pinned by NAME, so a
#: refactor that moves the sweep into a helper shows up here as a changed set
#: rather than as silence.
REMOVAL_SITES = {"retention.py": {"RetentionSweeper._sweep_dir"}}


def _def_spans(tree: ast.Module) -> list[tuple[str, int, int]]:
    spans: list[tuple[str, int, int]] = []

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef)):
                qual = prefix + child.name
                spans.append((qual, child.lineno,
                              getattr(child, "end_lineno", child.lineno)))
                walk(child, qual + ".")
            else:
                walk(child, prefix)

    walk(tree, "")
    return spans


def _scope_at(spans: list[tuple[str, int, int]], lineno: int) -> str:
    """The innermost def enclosing `lineno`, or `<module>`."""
    best = ("<module>", -1, -1)
    for qual, start, end in spans:
        if start <= lineno <= end and start > best[1]:
            best = (qual, start, end)
    return best[0]


def _removal_sites() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for py in sorted(SRC.rglob("*.py")):
        tree = _tree(py)
        spans = _def_spans(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)):
                continue
            attr = node.func.attr
            hit = attr in REMOVAL_ATTRS or (
                attr in OS_ONLY_ATTRS and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "os")
            if hit:
                rel = py.relative_to(SRC).as_posix()
                found.setdefault(rel, set()).add(_scope_at(spans, node.lineno))
    return found


def test_the_set_of_places_this_package_can_delete_a_file():
    """*"never pruned"* and *"the only copy"* are claims about THIS set.

    They are absence claims, so there is no symbol to anchor them to — an
    absence has no definition site. What it has is a set that is supposed to
    stay the size it is, and until CG-68 that size was zero. It is one now, and
    that one change falsified published sentences in two tenant contracts and a
    string on the unauthenticated `/healthz`, none of which were in the diff
    that broke them.

    So this is the trigger those sentences never had. It does not check that any
    of them is true; it makes the next person to add a delete read them.
    """
    assert _removal_sites() == REMOVAL_SITES, (
        "The set of places this package can delete a file has changed.\n\n"
        f"  found:    {_removal_sites()}\n"
        f"  expected: {REMOVAL_SITES}\n\n"
        "Before updating this dict, go and read what is currently published "
        "about deletion, and amend anything the new site makes false:\n"
        "  - docs/integration-guide.md, the inbound-replies section and the "
        "durability-counters table — the retention window is quoted to every "
        "consumer there;\n"
        "  - docs/consumers/jobhunt.md, the retention section;\n"
        "  - docs/consumers/aitrader.md, the env-var table's "
        "CHAT_GATEWAY_INBOX_RETENTION_DAYS row, which states that nothing of "
        "aitrader's is reachable by a sweeper;\n"
        "  - src/chat_gateway/service.py's /healthz `reasons` strings, which "
        "tell an operator in words whether their last copy is on a delete "
        "timer. That endpoint is UNAUTHENTICATED and hard rule #5 does not "
        "permit it to say something false.\n\n"
        "Locations, not quotations, deliberately: a quoted sentence in this "
        "message would go stale exactly the way the citations CG-69 was filed "
        "about did.\n\n"
        "If the new site deletes something a consumer was promised would "
        "persist, that is a contract amendment and needs the user's sign-off "
        "(the precedent is CG-68's A4), not a dict edit.")
```

**Verify:** the pin passes on a clean tree; then confirm it actually fires —

```bash
python3 - <<'PY'
import pathlib, re
p = pathlib.Path("src/chat_gateway/journal.py")
s = p.read_text(encoding="utf-8")
p.write_text(s.replace("os.replace(tmp, self._path)",
                       "self._path.unlink(missing_ok=True)\n        os.replace(tmp, self._path)"),
             encoding="utf-8")
PY
python3 -m pytest tests/test_published_promises.py -q   # must FAIL, naming journal.py
git checkout -- src/chat_gateway/journal.py
```

⚠ **Revert the probe.** `git status` must be clean under `src/` before Task 4.

---

## Task 4 — the tenant-data root pin

Append to `tests/test_published_promises.py`:

```python
# ---------------------------------------------------------------------------
# 3. Where tenant content lands, and whether git can see it
# ---------------------------------------------------------------------------

#: The env vars whose DEFAULT is a directory this process writes tenant content
#: into. Read out of `__main__.py` rather than restated, because `__main__.py`
#: is where the default actually lives and a second copy of it here is the
#: two-homes defect this repo keeps correcting.
TENANT_DIR_ENVS = ("CHAT_GATEWAY_STATE_DIR", "CHAT_GATEWAY_INBOX_DIR")


def _env_dir_defaults() -> dict[str, str]:
    """`CHAT_GATEWAY_*_DIR` -> the literal default `__main__.py` falls back to."""
    out: dict[str, str] = {}
    for node in ast.walk(_tree(SRC / "__main__.py")):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and len(node.args) == 2):
            continue
        name, default = node.args
        if (isinstance(name, ast.Constant) and name.value in TENANT_DIR_ENVS
                and isinstance(default, ast.Constant)
                and isinstance(default.value, str)):
            out[name.value] = default.value
    return out


def test_every_default_tenant_data_directory_is_gitignored():
    """#45 put outbound message bodies in `state/` while `.gitignore` still
    listed only `inbox-data/` — where they used to be.

    Nothing caught it in that PR. `state/` was untracked-but-not-ignored, so the
    README's own documented `python3 -m chat_gateway serve`, run from a
    checkout, left a `git add -A` between a local test and committing another
    tenant's `text`, `sender_email` and whole raw event. It took a separate
    residue sweep a PR later (CG-67) to find.

    The promise this keeps is not a sentence anybody wrote — it is `.gitignore`
    itself, whose comment says these patterns "are the whole guard, not a
    backstop to one". A guard whose coverage is stated in a comment and checked
    by nobody is how the first one failed.

    That comment's stated REASON was "nothing is deployed yet", and that reason
    expired on 2026-08-05 when the gateway went onto the NAS. The guard did not
    expire with it — it got MORE load-bearing, not less. The hazard it names is a
    developer checkout running `serve`, and every deployed instance is one more
    place a body can be produced before somebody clones the repo to reproduce
    something. Do not let a dead justification retire a live guard.
    """
    defaults = _env_dir_defaults()
    assert set(defaults) == set(TENANT_DIR_ENVS), (
        f"__main__.py no longer defaults all of {TENANT_DIR_ENVS} to a literal "
        f"— found {sorted(defaults)}. If a directory moved behind a helper, "
        "this guard stopped being able to see it; teach it the new shape rather "
        "than shrinking the list.")

    ignored = {
        line.strip().rstrip("/")
        for line in (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    missing = {env: d for env, d in defaults.items() if d.rstrip("/") not in ignored}
    assert not missing, (
        f"A default tenant-data directory is not in .gitignore: {missing}.\n\n"
        "This directory receives message bodies. Unanchored patterns are "
        "deliberate (.gitignore explains why), so add `<dir>/` and nothing "
        "else. Do not fix this by anchoring the pattern to the repo root: the "
        "working directory is not knowable from here and a `state/` one level "
        "down leaks exactly as much as one at the root.")
```

**Verify:** passes; then delete `state/` from `.gitignore` in the working tree,
confirm the test fails naming `CHAT_GATEWAY_STATE_DIR`, and restore.

---

## Task 5 — the `Falsifies` field in the queue-row shape

**File:** `docs/BUILDER_QUEUE.md`.

Add to the conventions text that introduces `## Queue` a required row field:

```markdown
| **Falsifies** | Which published sentences this row makes false, and where
they live — `docs/consumers/*`, `docs/integration-guide.md`, `CLAUDE.md`, or a
`/healthz` string in `src/`. **`none` is a valid answer; absent is not.**
A row that falsifies a published sentence corrects it **in its own PR** — rule
#5 does not permit leaving a false statement standing for the duration of a
second PR (the precedent is CG-75). |
```

**Why this is a task and not a nicety.** Across the **41** measured instances of
a published claim going false (spec §3, with the four-way split — **19** are the
category-(a) ones a test could see, and **11** were wrong when written), the
mechanism with the best record is not a test
and not code review — it is a falsification bullet written into the queue row
*before the code existed*. CG-75's row carried one and shipped with zero
residue; CG-74's plan carried the same as step B4, likewise. It is also the
**only** mechanism in the record that can catch a claim that was wrong the day
it was written, which no test in Tasks 2-4 can see (spec §8).

Do **not** retrofit the field onto shipped rows. It applies to rows written from
here on; back-filling history is the edit-the-record trap spec §6 excludes
whole trees for.

---

## Task 6 — `/healthz`'s table keeps its own count honest ⚠ **droppable**

**Ship Tasks 1-5 first.** This task is the only one needing a fully-configured
runtime fixture, and the only one automating a category humans are currently
catching. **If it does not fit the PR, file it as its own row rather than
rushing it** — a wrong exemption list is worse than no test.

Append to `tests/test_published_promises.py`:

```python
# ---------------------------------------------------------------------------
# 4. The /healthz table vs the /healthz body
# ---------------------------------------------------------------------------

# Present in the response and deliberately NOT rows in a table titled
# "Durability counters". Each needs a reason, in the shape of
# `test_error_surfaces.py`'s APPROVED_INTERPOLATIONS: a set whose membership is
# an act, not an accident.
NOT_DURABILITY_COUNTERS = {
    "status": "the verdict the table explains, not a row in it",
    "version": "build identity",
    "reasons": "the words behind `status`; every degrade path is already a row",
    "registry.apps": "config shape, documented under Identities + health",
    "registry.identities": "config shape, same",
    "inbox.pending": "the poll-queue depth, documented at GET /v1/inbox",
    "inbox.dropped": "pre-durability counter, documented at GET /v1/inbox",
    "heartbeats.checks": "the dead-man list, documented under POST /v1/heartbeat",
    "heartbeats.missed": "dead-man state, same",
    "subscriber.enabled": "tier-2 on/off, documented under Which Google runtime",
    "subscriber.note": "prose attached to the line above",
    "retention.enabled": "sweeper on/off",
    "retention.note": "prose attached to the line above",
}


def test_every_healthz_field_is_either_documented_or_deliberately_not():
    """This table has been wrong about its own field counts five times.

    Not about the *fields* — about the COUNTS: "forty-three rows", "eighteen
    carry yes", "twenty-one participate", "eleven additions, not twelve". Five
    successive rows recomputed those by hand and five successive rows got a
    number wrong, which is what a hand-maintained tally over a moving set always
    does. `/healthz` is unauthenticated and hard rule #5 makes it a promise to
    an operator, so the tally is not decoration.

    Deliberately asserts COVERAGE, not wording: a row may be rewritten freely,
    and only a field appearing or vanishing fires.
    """
    body = _fully_configured_healthz()      # see the fixture note below
    live = set(_leaf_keys(body))
    documented = set(_documented_rows())

    undocumented = live - documented - set(NOT_DURABILITY_COUNTERS)
    orphaned = documented - live

    assert not undocumented and not orphaned, (
        f"/healthz and its published table disagree.\n\n"
        f"  in the response, in no table row: {sorted(undocumented)}\n"
        f"  documented, absent from the response: {sorted(orphaned)}\n\n"
        "A new field is a new promise to an operator: add a row to "
        "docs/integration-guide.md's durability-counters table saying what it "
        "means and whether it degrades `status` — the per-counter degrade "
        "verdict is a standing requirement, decided one counter at a time "
        "(CLAUDE.md, the CG-12 bullet). If it genuinely belongs to another "
        "section, add it to NOT_DURABILITY_COUNTERS with the reason.\n\n"
        "A field documented but absent usually means the fixture is not fully "
        "configured, NOT that the docs are wrong: with no sweeper, 14 real "
        "`retention.*` rows vanish from the body. Check the fixture before "
        "touching the guide.")
```

**Fixture note — the measurement that makes or breaks this task.** A default
`create_app(...)` produces **42** leaf keys and the table documents **43** rows,
but the overlap is not 42: **14 documented `retention.*` rows are absent**
because no sweeper is configured, and **13 present keys** are the
`NOT_DURABILITY_COUNTERS` above. `_fully_configured_healthz()` must build the
app with a sweeper, a dispatcher, a subscriber and a heartbeat store — see
`tests/test_retention.py` and `tests/test_service.py::_loop_with` for the
existing shapes. **Re-measure all three numbers on the branch; do not carry them
from this plan.**

The two readers are short enough to be literal; only the fixture is assembly:

```python
BLOCKS = ("inbox", "delivery", "subscriber", "retention", "heartbeats", "registry")

DOC_ROW = re.compile(r"^\|\s*`([a-z_]+\.[a-z_]+)`\s*\|")


def _documented_rows() -> list[str]:
    """The first cell of every durability-counters row, in file order.

    A LIST, not a set: the table's own prose states a row count, and a
    duplicated row would keep a set the right size while making that sentence
    false — which is the exact defect class this task exists for.
    """
    guide = (REPO / "docs" / "integration-guide.md").read_text(encoding="utf-8")
    return [m.group(1) for line in guide.splitlines()
            for m in [DOC_ROW.match(line)] if m]


def _leaf_keys(body: dict) -> list[str]:
    """`block.field` for the documented blocks; bare keys for everything else.

    One level only, and only for `BLOCKS`, because that is precisely how the
    table names its rows — `heartbeats.checks` is one row even though its value
    is a list of dicts, and descending into it would invent fields nobody
    published.
    """
    keys = []
    for name, value in body.items():
        if name in BLOCKS and isinstance(value, dict):
            keys.extend(f"{name}.{k}" for k in value)
        else:
            keys.append(name)
    return keys
```

**Also assert the stated totals**, since they are the thing that has actually
been wrong: the table's *"forty-three rows"* must equal `len(_documented_rows())`,
and its *"eighteen carry `**yes**`"* must equal the count of rows whose
Degrades? cell starts with `**yes**`. Both numbers are written as English words
in the prose above the table — read them from there, so the prose and the table
cannot drift apart.

---

## Docs impact

| File | Change |
|---|---|
| `docs/consumers/aitrader.md` | 13 citations → symbol anchors (Task 1). No prose change |
| `CLAUDE.md` | 1 code citation + 1 markdown citation → anchors (Task 1). No prose change |
| `docs/BUILDER_QUEUE.md` | CG-69 row → ✅ decided, plan linked; new `Falsifies` field in the row shape (Task 5) |
| `tests/test_published_promises.py` | new |
| `docs/integration-guide.md` | **only if Task 6 finds a genuine gap.** Task 1 touches it not at all |

**Not touched:** `src/` (no production code changes in this row at all),
`docs/architecture/`, `docs/superpowers/specs/**` other than this row's own,
`docs/google-cloud-setup.md`.

---

## Test plan

1. `python3 -m pytest -q` — **345 + the new tests**, all passing. Re-measure the
   total; do not assert this plan's arithmetic.
2. The two `grep`s at the end of Task 1 print nothing.
3. Each new guard is shown to FIRE, not merely to pass: the `unlink` probe in
   Task 3, the `.gitignore` deletion in Task 4, and for Task 2, temporarily
   rename any anchored symbol in `src/` and confirm the failure names the doc
   and line. **Revert every probe**; `git status` clean under `src/`.
4. `git diff main -- src/ | grep -c "LIVE-UNVERIFIED\|SHAPE-VERIFIED"` → `0`.
5. No `/healthz` string changes in this row, so no UAT against a running app is
   required. If Task 6 changes the guide's table, re-read the two counter
   sentences above it.
