#!/usr/bin/env python3
"""Build bin/wc-blocks-specificity.json from the published WC plugin CSS.

Phase 1 (`phase1-specificity`) of the closed-loop plan: the static
gate `check_wc_specificity_winnable()` in `bin/check.py` needs to
know the specificity of every selector WooCommerce Blocks ships so
it can statically prove our `bin/append-wc-overrides.py` chunks
will actually win the cascade. Without this index the gate has to
guess, which is exactly the math humans got wrong on the Selvedge
input bug (`body .wc-block-components-text-input input` (0,1,2)
losing to WC's `0,3,1`).

How
---
1. Download `woocommerce.latest-stable.zip` from downloads.wordpress.org
   (cached under tmp/wc-plugin-cache/woocommerce.zip).
2. Open every `woocommerce/assets/client/blocks/*.css` (skipping RTL
   variants) and parse the selector lists.
3. Compute (id_count, class+attr+pseudoclass count, type+pseudoelement
   count) for each selector via the standard CSS specificity rules.
4. Write `{ "_meta": ..., "selectors": {selector: [a, b, c]} }` to
   `bin/wc-blocks-specificity.json`.

Re-run when bumping WooCommerce or upgrading to a new WC Blocks
release. The output is committed to the repo so contributors don't
need to fetch the plugin to run the gate.

Usage
-----
    python3 bin/build-wc-specificity-index.py            # use cache if present
    python3 bin/build-wc-specificity-index.py --refresh  # re-download plugin
    python3 bin/build-wc-specificity-index.py --from-dir <path-to-extracted-wc>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import MONOREPO_ROOT  # noqa: E402

WC_PLUGIN_URL = "https://downloads.wordpress.org/plugin/woocommerce.latest-stable.zip"
CACHE_DIR = MONOREPO_ROOT / "tmp" / "wc-plugin-cache"
CACHE_ZIP = CACHE_DIR / "woocommerce.zip"
INDEX_PATH = MONOREPO_ROOT / "bin" / "wc-blocks-specificity.json"
CSS_GLOB = re.compile(r"^woocommerce/assets/client/blocks/[^/]+\.css$")
SKIP_RTL = re.compile(r"-rtl\.css$")


# ---------------------------------------------------------------------------
# Selector + specificity
# ---------------------------------------------------------------------------

# Strip CSS comments (single-line + block) so they don't pollute the
# selector parse.
_CSS_COMMENTS = re.compile(r"/\*[\s\S]*?\*/")


def iter_selectors(css_text: str):
    """Yield each top-level selector from a CSS text. Nested @media/
    @supports/@keyframes are descended into; anything else is skipped.
    Selector groups (`a, b`) are split per element."""
    text = _CSS_COMMENTS.sub("", css_text)
    depth = 0
    buf: list[str] = []
    in_block = False
    block_depth = 0
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "{":
            if not in_block:
                selector_blob = "".join(buf).strip()
                buf = []
                if selector_blob:
                    if selector_blob.startswith("@"):
                        # at-rule; for media/supports we want to
                        # descend and yield inner selectors. The
                        # naive depth-tracker handles nesting.
                        if not selector_blob.startswith(
                            ("@keyframes", "@-webkit-keyframes", "@font-face", "@page", "@property", "@layer ")
                        ):
                            in_block = False
                            depth += 1
                            i += 1
                            continue
                        # skip the body of keyframes/font-face/etc.
                        block_depth = 1
                        i += 1
                        while i < n and block_depth > 0:
                            if text[i] == "{":
                                block_depth += 1
                            elif text[i] == "}":
                                block_depth -= 1
                            i += 1
                        continue
                    for piece in _split_selector_group(selector_blob):
                        piece = piece.strip()
                        if piece and not piece.startswith("@"):
                            yield piece
                in_block = True
                block_depth = 1
            else:
                block_depth += 1
            i += 1
            continue
        if ch == "}":
            if in_block:
                block_depth -= 1
                if block_depth == 0:
                    in_block = False
            else:
                if depth > 0:
                    depth -= 1
            i += 1
            continue
        if not in_block:
            buf.append(ch)
        i += 1


def _split_selector_group(blob: str) -> list[str]:
    """Split `a, b:where(c, d), e[f=','] ` honoring brackets+parens."""
    out: list[str] = []
    depth_paren = 0
    depth_brack = 0
    in_str: str | None = None
    cur: list[str] = []
    for ch in blob:
        if in_str is not None:
            cur.append(ch)
            if ch == in_str:
                in_str = None
            continue
        if ch in ("'", '"'):
            in_str = ch
            cur.append(ch)
            continue
        if ch == "(":
            depth_paren += 1
        elif ch == ")":
            depth_paren -= 1
        elif ch == "[":
            depth_brack += 1
        elif ch == "]":
            depth_brack -= 1
        if ch == "," and depth_paren == 0 and depth_brack == 0:
            out.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    if cur:
        out.append("".join(cur))
    return out


_ID_RE = re.compile(r"#[A-Za-z_][A-Za-z0-9_-]*")
_CLASS_RE = re.compile(r"\.[A-Za-z_][A-Za-z0-9_-]*")
_ATTR_RE = re.compile(r"\[[^\]]+\]")
_PSEUDO_CLASS_RE = re.compile(r":(?!:)[A-Za-z][A-Za-z0-9-]*(?:\([^)]*\))?")
_PSEUDO_ELEM_RE = re.compile(r"::[A-Za-z][A-Za-z0-9-]*")
_TYPE_RE = re.compile(r"(?:^|[\s>+~()|])([a-zA-Z][a-zA-Z0-9-]*)\b")
# Pseudo-classes that don't add to specificity (per CSS Selectors 4)
_ZERO_SPEC_PCS = {":where", ":not", ":is", ":has", ":matches"}


def compute_specificity(selector: str) -> tuple[int, int, int]:
    """Return (a, b, c) specificity following CSS Selectors Level 3+.

    `a` = id selectors. `b` = class + attribute + pseudo-class
    selectors. `c` = type + pseudo-element selectors. `:where(...)`
    contributes 0; `:is/:has/:not(...)` contribute the max
    specificity inside their argument list (matches browser behavior;
    this index is for cascade-loss detection so being slightly
    pessimistic on the `:is` direction is fine)."""
    sel = selector.strip()

    # Split off nested pseudo args first so the regex passes don't
    # double-count them.
    a = b = c = 0

    pseudo_elems = _PSEUDO_ELEM_RE.findall(sel)
    c += len(pseudo_elems)
    sel_no_pe = _PSEUDO_ELEM_RE.sub(" ", sel)

    # Walk pseudo-classes manually because some contribute, some don't,
    # and some take selector-list args.
    work = sel_no_pe
    pseudo_iter = list(_PSEUDO_CLASS_RE.finditer(work))
    for m in pseudo_iter:
        pc_full = m.group(0)
        pc_name = pc_full.split("(", 1)[0]
        if pc_name in _ZERO_SPEC_PCS and "(" in pc_full:
            inner = pc_full[pc_full.index("(") + 1 : pc_full.rindex(")")]
            if pc_name == ":where":
                continue
            # :is/:has/:not -> max of contained selectors
            inner_specs = [compute_specificity(x) for x in _split_selector_group(inner) if x.strip()]
            if inner_specs:
                ia = max(s[0] for s in inner_specs)
                ib = max(s[1] for s in inner_specs)
                ic = max(s[2] for s in inner_specs)
                a += ia
                b += ib
                c += ic
        else:
            b += 1
    sel_no_pseudo = _PSEUDO_CLASS_RE.sub(" ", work)

    a += len(_ID_RE.findall(sel_no_pseudo))
    b += len(_CLASS_RE.findall(sel_no_pseudo))
    b += len(_ATTR_RE.findall(sel_no_pseudo))

    sel_strip = _ID_RE.sub(" ", sel_no_pseudo)
    sel_strip = _CLASS_RE.sub(" ", sel_strip)
    sel_strip = _ATTR_RE.sub(" ", sel_strip)
    type_count = 0
    for m in _TYPE_RE.finditer(" " + sel_strip):
        tok = m.group(1).lower()
        if tok in {"and", "or", "not", "from", "to"}:
            continue
        type_count += 1
    c += type_count

    return (a, b, c)


# ---------------------------------------------------------------------------
# Plugin fetch + extract
# ---------------------------------------------------------------------------


def fetch_zip(refresh: bool) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if refresh or not CACHE_ZIP.is_file():
        print(f"Downloading {WC_PLUGIN_URL} -> {CACHE_ZIP.relative_to(MONOREPO_ROOT)}...")
        urllib.request.urlretrieve(WC_PLUGIN_URL, CACHE_ZIP)
    return CACHE_ZIP


def extract_wc_version(zf: zipfile.ZipFile) -> str:
    """Read Version: from woocommerce/woocommerce.php."""
    try:
        with zf.open("woocommerce/woocommerce.php") as fh:
            head = fh.read(2048).decode("utf-8", errors="replace")
        m = re.search(r"^\s*\*\s*Version:\s*([^\s]+)", head, re.MULTILINE)
        return m.group(1) if m else "unknown"
    except KeyError:
        return "unknown"


def index_from_zip(zip_path: Path) -> tuple[dict[str, list[int]], str, int]:
    selectors: dict[str, tuple[int, int, int]] = {}
    files_scanned = 0
    with zipfile.ZipFile(zip_path) as zf:
        version = extract_wc_version(zf)
        for name in zf.namelist():
            if not CSS_GLOB.match(name):
                continue
            if SKIP_RTL.search(name):
                continue
            files_scanned += 1
            with zf.open(name) as fh:
                text = fh.read().decode("utf-8", errors="replace")
            for sel in iter_selectors(text):
                spec = compute_specificity(sel)
                if sel not in selectors or spec > selectors[sel]:
                    selectors[sel] = spec
    flat = {sel: list(spec) for sel, spec in selectors.items()}
    return flat, version, files_scanned


def index_from_dir(css_dir: Path) -> tuple[dict[str, list[int]], str, int]:
    selectors: dict[str, tuple[int, int, int]] = {}
    files_scanned = 0
    for css_file in sorted(css_dir.rglob("*.css")):
        if SKIP_RTL.search(css_file.name):
            continue
        files_scanned += 1
        text = css_file.read_text(encoding="utf-8", errors="replace")
        for sel in iter_selectors(text):
            spec = compute_specificity(sel)
            if sel not in selectors or spec > selectors[sel]:
                selectors[sel] = spec
    flat = {sel: list(spec) for sel, spec in selectors.items()}
    return flat, "from-dir", files_scanned


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="Re-download even if cached.")
    parser.add_argument("--from-dir", type=Path, default=None, help="Skip download, walk this directory.")
    args = parser.parse_args(argv)

    if args.from_dir:
        selectors, version, files_scanned = index_from_dir(args.from_dir)
        source = str(args.from_dir)
    else:
        zip_path = fetch_zip(args.refresh)
        selectors, version, files_scanned = index_from_zip(zip_path)
        source = WC_PLUGIN_URL

    payload = {
        "_meta": {
            "wc_version": version,
            "source": source,
            "files_scanned": files_scanned,
            "selectors_indexed": len(selectors),
            "generated_at": int(time.time()),
        },
        "selectors": dict(sorted(selectors.items())),
    }
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        f"Wrote {INDEX_PATH.relative_to(MONOREPO_ROOT)} "
        f"(WC {version}, {files_scanned} CSS files, {len(selectors)} selectors)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
