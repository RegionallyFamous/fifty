r"""Static guards for `iter_themes()` call sites in the scripts that
`bin/design.py` invokes on freshly-cloned themes.

Background
----------
`bin/_lib.iter_themes()` defaults to yielding only themes whose
``readiness.json`` reports ``stage: shipping`` (the set
``DEFAULT_VISIBLE_STAGES``). That default is the right answer for
sweeps that should ignore incubating/retired themes (check.py's
cross-theme uniqueness passes, the gallery generator, the theme-status
dashboard).

But ``bin/clone.py`` writes the freshly-cloned theme's
``readiness.json`` with ``stage: incubating`` — so any script that
``bin/design.py`` calls on that theme BEFORE promotion (seed, sync,
redirects, …) has to iterate across every stage, not just shipping.
Otherwise the just-cloned theme is invisible to the scripts that
exist specifically to finish setting it up, and the user sees the
classic chicken-and-egg error:

    error: theme 'azulejo' not found

(from `bin/seed-playground-content.py`, the first phase in
`bin/design.py` that tries to look the theme up by slug).

These tests lock in the decision that every script `bin/design.py`
calls passes ``stages=()`` to ``iter_themes``, so stage filtering is
NOT applied during the design pipeline. A regression that flips any
of these back to the shipping-only default would silently break
``design-batch.py`` for every new theme.

Note: this is an implementation-level test on purpose. The fix is
a one-line change (``iter_themes()`` → ``iter_themes(stages=())``) so
a behavioural test that actually boots a two-theme monorepo is more
complexity than the guarded bug warrants. The grep-the-source shape
of ``tests/tools/test_ci_yaml.py`` is the right precedent.
"""

from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "bin"


# The scripts ``bin/design.py`` invokes on a freshly-cloned theme.
# Every one of these either takes a ``--theme <slug>``/positional slug
# arg AND looks it up via ``iter_themes()``, or iterates every theme
# without a slug filter and must include the new (incubating) theme
# in its pass. If you add a new phase to `bin/design.py` whose script
# iterates themes the same way, list it here.
DESIGN_PHASE_SCRIPTS = (
    "seed-playground-content.py",
    "sync-playground.py",
    "build-redirects.py",
)


def _strip_comments_and_strings(src: str) -> str:
    """Return ``src`` with all ``#`` comments blanked and all string
    literals (including triple-quoted docstrings) replaced by empty
    strings of the same length, so a regex search for a call
    expression won't false-positive on text that merely mentions
    ``iter_themes()`` in prose.
    """
    out: list[str] = []
    last_row, last_col = 1, 0
    pieces: list[tuple[int, int, int, int, str]] = []
    tokens = tokenize.generate_tokens(io.StringIO(src).readline)
    blanks: dict[tuple[int, int, int, int], str] = {}
    for tok in tokens:
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            blanks[(tok.start[0], tok.start[1], tok.end[0], tok.end[1])] = tok.string

    # Easier path: produce a flattened string from the original source
    # with the blanked ranges replaced in-place. Python's tokenize
    # gives us (line, col) so we can splice byte ranges directly on
    # the original source split into lines.
    lines = src.splitlines(keepends=True)
    for (srow, scol, erow, ecol), literal in blanks.items():
        # Blank across the range; keep newline breaks intact so line
        # numbers in test failure output still match the real file.
        if srow == erow:
            line = lines[srow - 1]
            lines[srow - 1] = line[:scol] + (" " * (ecol - scol)) + line[ecol:]
        else:
            # First line: blank from scol to end of line (keeping \n).
            first = lines[srow - 1]
            # Preserve trailing newline if present.
            nl = "\n" if first.endswith("\n") else ""
            lines[srow - 1] = first[:scol] + (" " * (len(first) - scol - len(nl))) + nl
            # Middle lines: blank entirely except newline.
            for ln in range(srow, erow - 1):
                mid = lines[ln]
                nl = "\n" if mid.endswith("\n") else ""
                lines[ln] = (" " * (len(mid) - len(nl))) + nl
            # Last line: blank from start to ecol.
            last = lines[erow - 1]
            lines[erow - 1] = (" " * ecol) + last[ecol:]
    _ = out, last_row, last_col, pieces  # lint-appeasement
    return "".join(lines)


@pytest.mark.parametrize("script_name", DESIGN_PHASE_SCRIPTS)
def test_iter_themes_is_stage_agnostic(script_name: str) -> None:
    """Every script `bin/design.py` runs during a fresh theme build
    must call ``iter_themes(stages=())`` (or pass an explicit tuple
    that includes ``incubating``).

    A bare ``iter_themes()`` call would apply the shipping-only
    default filter and silently drop the just-cloned theme from the
    iteration, resulting in either "theme '<slug>' not found" or a
    completed run that skipped the new theme entirely.
    """
    script = BIN / script_name
    assert script.is_file(), f"missing bin/{script_name}"
    src = script.read_text(encoding="utf-8")

    # Strip docstrings + comments so "iter_themes()" in prose (e.g.
    # module docstrings) doesn't confuse the scanner — we're looking
    # for call EXPRESSIONS only.
    code = _strip_comments_and_strings(src)

    calls = re.findall(r"iter_themes\s*\([^)]*\)", code, flags=re.DOTALL)
    assert calls, (
        f"bin/{script_name} does not call iter_themes() at all — "
        "this test's premise is wrong; remove the entry from "
        "DESIGN_PHASE_SCRIPTS or update the test."
    )

    for call in calls:
        stripped = re.sub(r"\s+", "", call)
        if stripped == "iter_themes()":
            pytest.fail(
                f"bin/{script_name}: bare `iter_themes()` call found.\n"
                f"This applies the shipping-only default filter and will\n"
                f"silently skip freshly-cloned themes that sit at\n"
                f"`stage: incubating` (written by `bin/clone.py`).\n"
                f"Replace with `iter_themes(stages=())` so every stage\n"
                f"is included during the design pipeline.\n\n"
                f"Example fix:\n"
                f"  - themes = list(iter_themes())\n"
                f"  + themes = list(iter_themes(stages=()))\n"
            )
