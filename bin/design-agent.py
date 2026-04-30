#!/usr/bin/env python3
"""Agentic design pass for concept-sensitive theme dressing.

This script is intentionally narrower than the repair agent in
``design_unblock.py``: it only runs during the design pipeline, and only for
the two phases that need actual visual judgment.

Tasks:
  frontpage  Read the concept context and rewrite templates/front-page.html.
             Each candidate is validated with the editor-parity block
             validator before it is kept.
  photos     Ask Claude for product-photo prompts and, when an image API key
             is available, generate real JPEGs. Otherwise fall back to the
             existing Pillow generator so the build keeps going.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from _lib import resolve_theme_root  # noqa: E402

DEFAULT_MODEL = "claude-sonnet-4-6"


@dataclass
class ValidationResult:
    ok: bool
    detail: str


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _load_spec_context(slug: str, theme_root: Path) -> dict[str, Any]:
    """Load the best available concept context for a theme.

    Fresh pipeline runs may still have ``tmp/specs/<slug>.json``; shipped
    themes usually only have BRIEF.md and mockups/<slug>.meta.json. Use all of
    them when present rather than requiring a single source.
    """

    context: dict[str, Any] = {
        "slug": slug,
        "name": slug.replace("-", " ").title(),
        "tagline": "",
        "voice": "",
        "layout_hints": [],
        "palette": {},
        "mockup_meta": {},
        "brief": "",
    }
    for candidate in (
        ROOT / "tmp" / "specs" / f"{slug}.json",
        ROOT / "specs" / f"{slug}.json",
    ):
        spec = _read_json(candidate)
        if spec:
            context.update({k: v for k, v in spec.items() if v not in (None, "", [], {})})
            break

    meta = _read_json(ROOT / "mockups" / f"{slug}.meta.json")
    if meta:
        context["mockup_meta"] = meta
        context.setdefault("name", meta.get("name") or context["name"])
        if not context.get("tagline"):
            context["tagline"] = meta.get("blurb", "")

    brief_path = theme_root / "BRIEF.md"
    if brief_path.is_file():
        brief = brief_path.read_text(encoding="utf-8")
        context["brief"] = brief
        if not context.get("voice"):
            match = re.search(r"## Voice\s+(.+?)(?:\n## |\Z)", brief, flags=re.S)
            if match:
                context["voice"] = " ".join(match.group(1).split())
        if not context.get("layout_hints"):
            match = re.search(r"## Layout hints\s+(.+?)(?:\n## |\Z)", brief, flags=re.S)
            if match:
                hints = []
                for line in match.group(1).splitlines():
                    line = line.strip()
                    if line.startswith("- "):
                        hints.append(line[2:].strip())
                context["layout_hints"] = hints

    theme_json = _read_json(theme_root / "theme.json")
    palette: dict[str, str] = {}
    for entry in theme_json.get("settings", {}).get("color", {}).get("palette", []):
        if isinstance(entry, dict) and entry.get("slug") and entry.get("color"):
            palette[str(entry["slug"])] = str(entry["color"])
    if palette:
        context["palette"] = palette
    return context


def _mockup_path(slug: str) -> Path | None:
    path = ROOT / "mockups" / f"mockup-{slug}.png"
    return path if path.is_file() else None


def _strip_code_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json|html)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = _strip_code_fence(raw)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("LLM response must be a JSON object")
    return data


def _block_comment_balance_ok(html: str) -> bool:
    """Cheap guard before invoking the full node validator."""

    stack: list[str] = []
    for match in re.finditer(r"<!--\s*(/)?wp:([a-z0-9/:-]+).*?(\/)?\s*-->", html, flags=re.S):
        closing = bool(match.group(1))
        name = match.group(2)
        self_closing = bool(match.group(3))
        if closing:
            if not stack or stack[-1] != name:
                return False
            stack.pop()
        elif not self_closing:
            stack.append(name)
    return not stack


def _run_block_validator(theme_root: Path) -> ValidationResult:
    validator = ROOT / "bin" / "blocks-validator" / "check-blocks.mjs"
    validator_dir = validator.parent
    if shutil.which("node") is None:
        return ValidationResult(False, "node is not on PATH; block validator cannot run")
    if not (validator_dir / "node_modules").is_dir():
        return ValidationResult(
            False,
            "bin/blocks-validator/node_modules is missing; run npm --prefix bin/blocks-validator ci",
        )
    proc = subprocess.run(
        ["node", str(validator), str(theme_root)],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    detail = (proc.stdout + "\n" + proc.stderr).strip()
    return ValidationResult(proc.returncode == 0, detail or f"validator exited {proc.returncode}")


def _write_candidate_if_valid(theme_root: Path, candidate: str) -> ValidationResult:
    front_page = theme_root / "templates" / "front-page.html"
    original = front_page.read_text(encoding="utf-8")
    if not _block_comment_balance_ok(candidate):
        return ValidationResult(False, "candidate has unbalanced WordPress block comments")
    front_page.write_text(candidate, encoding="utf-8")
    result = _run_block_validator(theme_root)
    if not result.ok:
        front_page.write_text(original, encoding="utf-8")
    return result


def _completion(
    *,
    prompt: str,
    system_prompt: str,
    mockup: Path | None,
    model: str,
    max_output_tokens: int,
) -> str:
    try:
        if mockup is not None:
            from _vision_lib import vision_completion

            return vision_completion(
                png_path=mockup,
                system_prompt=system_prompt,
                user_prompt=prompt,
                theme="",
                route="design-agent",
                viewport="mockup",
                model=model,
                max_output_tokens=max_output_tokens,
            ).raw_text

        from _vision_lib import text_completion

        return text_completion(
            system_prompt=system_prompt,
            user_prompt=prompt,
            model=model,
            label="design-agent",
            max_output_tokens=max_output_tokens,
        ).raw_text
    except Exception as exc:
        raise RuntimeError(f"LLM call failed: {exc}") from exc


def _frontpage_prompt(
    slug: str,
    context: dict[str, Any],
    html: str,
    previous_error: str = "",
) -> tuple[str, str]:
    system = (
        "You are a senior WordPress block-theme designer. Return only JSON. "
        "You rewrite valid block markup, not prose. Preserve dynamic commerce "
        "blocks and keep styling token-based."
    )
    prompt = f"""\
Rewrite `{slug}/templates/front-page.html` so the home page matches the concept.

Theme context:
{json.dumps(context, indent=2)[:12000]}

Current front-page.html:
```html
{html}
```

Rules:
- Return a JSON object with keys `rationale` and `front_page_html`.
- `front_page_html` must be the full replacement file.
- Preserve existing `wp:woocommerce/*`, `wp:query`, `wp:post-template`, and
  `wp:terms-query` blocks unless moving them is necessary for the layout.
- Use only core and WooCommerce blocks.
- Use theme tokens such as `var:preset|color|accent`; do not introduce raw hex.
- Do not use `core/html`, shortcodes, external scripts, or fake forms.
- Make the composition match the layout hints, not merely the colors.
"""
    if previous_error:
        prompt += f"\nPrevious candidate failed validation:\n{previous_error[:6000]}\n"
    return system, prompt


def run_frontpage(theme_root: Path, *, dry_run: bool, max_rounds: int, model: str) -> int:
    slug = theme_root.name
    front_page = theme_root / "templates" / "front-page.html"
    if not front_page.is_file():
        print(f"design-agent frontpage: {front_page.relative_to(ROOT)} missing", file=sys.stderr)
        return 1

    context = _load_spec_context(slug, theme_root)
    mockup = _mockup_path(slug)
    original = front_page.read_text(encoding="utf-8")
    system, prompt = _frontpage_prompt(slug, context, original)
    if dry_run:
        print("---- DESIGN AGENT FRONTPAGE PROMPT (dry-run) ----")
        print(f"mockup: {mockup.relative_to(ROOT) if mockup else '(missing; text-only mode)'}")
        print(prompt)
        print("---- END PROMPT ----")
        return 0

    error = ""
    for attempt in range(1, max_rounds + 1):
        system, prompt = _frontpage_prompt(slug, context, front_page.read_text(encoding="utf-8"), error)
        try:
            raw = _completion(
                prompt=prompt,
                system_prompt=system,
                mockup=mockup,
                model=model,
                max_output_tokens=12000,
            )
        except RuntimeError as exc:
            error = f"attempt {attempt}: {exc}"
            print(f"  [design-agent/frontpage] {error}", file=sys.stderr)
            continue
        try:
            parsed = _parse_json_object(raw)
        except Exception as exc:
            error = f"attempt {attempt}: response was not parseable JSON: {exc}"
            print(f"  [design-agent/frontpage] {error}", file=sys.stderr)
            continue
        candidate = str(parsed.get("front_page_html") or parsed.get("html") or "").strip()
        if not candidate:
            error = f"attempt {attempt}: response omitted `front_page_html`"
            print(f"  [design-agent/frontpage] {error}", file=sys.stderr)
            continue
        result = _write_candidate_if_valid(theme_root, candidate)
        if result.ok:
            rationale = str(parsed.get("rationale") or "").strip()
            print(f"  [design-agent/frontpage] accepted attempt {attempt}")
            if rationale:
                print(f"  [design-agent/frontpage] {rationale[:500]}")
            return 0
        error = result.detail
        print(f"  [design-agent/frontpage] attempt {attempt} failed validation", file=sys.stderr)

    # Safe fallback: restore original, then apply the layout-class-only guard.
    front_page.write_text(original, encoding="utf-8")
    fallback = ROOT / "bin" / "diversify-front-page.py"
    subprocess.call([sys.executable, str(fallback), "--theme", slug], cwd=str(ROOT))
    print("  [design-agent/frontpage] exhausted attempts; kept fallback layout class", file=sys.stderr)
    return 1


def _product_map(theme_root: Path) -> dict[str, str]:
    path = theme_root / "playground" / "content" / "product-images.json"
    data = _read_json(path)
    return {str(k): str(v) for k, v in data.items()}


def _product_name_from_filename(filename: str) -> str:
    stem = Path(filename).stem.removeprefix("product-wo-")
    return " ".join(part.capitalize() for part in stem.split("-"))


def _photo_prompt(slug: str, context: dict[str, Any], products: dict[str, str]) -> tuple[str, str]:
    system = (
        "You are an art director for product photography. Return only JSON. "
        "Write concrete, photorealistic image prompts that match the brand."
    )
    product_rows = [
        {"sku": sku, "filename": filename, "name": _product_name_from_filename(filename)}
        for sku, filename in sorted(products.items())
    ]
    prompt = f"""\
Write product-photo generation prompts for `{slug}`.

Theme context:
{json.dumps(context, indent=2)[:12000]}

Products:
{json.dumps(product_rows, indent=2)}

Return JSON with this shape:
{{
  "rationale": "...",
  "prompts": {{
    "WO-SKU": "photorealistic square product photograph prompt..."
  }}
}}

Prompt rules:
- Each prompt must describe a real photographic product setup, not a poster,
  illustration, UI card, or flat graphic.
- Match the concept's era, palette, lighting, props, and composition.
- Square product photo, no readable text, no logos, no watermarks.
- Keep each prompt under 900 characters.
"""
    return system, prompt


def _request_json(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={**headers, "content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{url} returned HTTP {exc.code}: {detail[:800]}") from exc


def _download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=180) as resp:
        return resp.read()


def _generate_openai(prompt: str) -> bytes:
    key = os.environ["OPENAI_API_KEY"]
    data = _request_json(
        "https://api.openai.com/v1/images/generations",
        {"authorization": f"Bearer {key}"},
        {"model": "gpt-image-1", "prompt": prompt, "size": "1024x1024", "n": 1},
    )
    item = (data.get("data") or [{}])[0]
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    if item.get("url"):
        return _download(str(item["url"]))
    raise RuntimeError("OpenAI image response did not include b64_json or url")


def _generate_fal(prompt: str) -> bytes:
    key = os.environ["FAL_KEY"]
    data = _request_json(
        "https://fal.run/fal-ai/flux/dev",
        {"authorization": f"Key {key}"},
        {
            "prompt": prompt,
            "image_size": "square_hd",
            "num_images": 1,
            "output_format": "jpeg",
        },
    )
    image = (data.get("images") or [{}])[0]
    if image.get("url"):
        return _download(str(image["url"]))
    if image.get("content"):
        return base64.b64decode(str(image["content"]))
    raise RuntimeError("fal image response did not include an image URL")


def _write_image_bytes(dest: Path, raw: bytes) -> None:
    # Normalize whatever the provider returned to a JPEG file.
    try:
        from PIL import Image

        with tempfile.NamedTemporaryFile(suffix=".img") as tmp:
            tmp.write(raw)
            tmp.flush()
            img = Image.open(tmp.name).convert("RGB")
            dest.parent.mkdir(parents=True, exist_ok=True)
            img.save(dest, "JPEG", quality=88)
    except Exception:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)


def _fallback_photos(slug: str, *, force: bool = False) -> int:
    script = ROOT / "bin" / "generate-product-photos.py"
    cmd = [sys.executable, str(script), "--theme", slug]
    if force:
        cmd.append("--force")
    return subprocess.call(cmd, cwd=str(ROOT))


def run_photos(theme_root: Path, *, dry_run: bool, model: str) -> int:
    slug = theme_root.name
    products = _product_map(theme_root)
    if not products:
        print(f"design-agent photos: no product-images.json entries for {slug}", file=sys.stderr)
        return 1

    context = _load_spec_context(slug, theme_root)
    mockup = _mockup_path(slug)
    system, prompt = _photo_prompt(slug, context, products)
    if dry_run:
        print("---- DESIGN AGENT PHOTOS PROMPT (dry-run) ----")
        print(f"mockup: {mockup.relative_to(ROOT) if mockup else '(missing; text-only mode)'}")
        print(prompt)
        print("---- END PROMPT ----")
        return 0

    try:
        raw = _completion(
            prompt=prompt,
            system_prompt=system,
            mockup=mockup,
            model=model,
            max_output_tokens=10000,
        )
    except RuntimeError as exc:
        print(f"  [design-agent/photos] {exc}; falling back", file=sys.stderr)
        return _fallback_photos(slug, force=True)
    try:
        parsed = _parse_json_object(raw)
    except Exception as exc:
        print(f"  [design-agent/photos] prompt JSON parse failed: {exc}", file=sys.stderr)
        return _fallback_photos(slug, force=True)

    prompt_map_raw = parsed.get("prompts") or {}
    if not isinstance(prompt_map_raw, dict):
        print("  [design-agent/photos] prompt response omitted `prompts`; falling back", file=sys.stderr)
        return _fallback_photos(slug, force=True)
    prompt_map = {str(k): str(v) for k, v in prompt_map_raw.items() if str(v).strip()}

    prompt_manifest = theme_root / "playground" / "content" / "product-photo-prompts.json"
    prompt_manifest.write_text(
        json.dumps({"schema": 1, "theme": slug, "prompts": prompt_map}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"  [design-agent/photos] wrote {prompt_manifest.relative_to(ROOT)}")

    generator = None
    if os.environ.get("FAL_KEY"):
        generator = _generate_fal
    elif os.environ.get("OPENAI_API_KEY"):
        generator = _generate_openai

    if generator is None:
        print("  [design-agent/photos] no FAL_KEY or OPENAI_API_KEY; using Pillow fallback")
        return _fallback_photos(slug, force=True)

    written = 0
    images_dir = theme_root / "playground" / "images"
    for sku, filename in sorted(products.items()):
        image_prompt = prompt_map.get(sku)
        if not image_prompt:
            continue
        dest = images_dir / filename
        try:
            _write_image_bytes(dest, generator(image_prompt))
            written += 1
            print(f"  [design-agent/photos] generated {dest.relative_to(ROOT)}")
        except Exception as exc:
            print(f"  [design-agent/photos] {sku} failed: {exc}", file=sys.stderr)

    # Fill any missing category/hero/product images with the existing generator,
    # but do not overwrite real API-generated product photos.
    fallback_rc = _fallback_photos(slug, force=False)
    if written == 0 and fallback_rc != 0:
        return fallback_rc
    seed = ROOT / "bin" / "seed-playground-content.py"
    subprocess.call([sys.executable, str(seed), "--theme", slug], cwd=str(ROOT))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--theme", required=True, metavar="SLUG")
    parser.add_argument("--task", choices=("frontpage", "photos"), required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument(
        "--model",
        default=os.environ.get("FIFTY_DESIGN_AGENT_MODEL") or DEFAULT_MODEL,
    )
    args = parser.parse_args(argv)

    try:
        theme_root = resolve_theme_root(args.theme)
    except Exception as exc:
        print(f"design-agent: {exc}", file=sys.stderr)
        return 1

    if args.task == "frontpage":
        return run_frontpage(
            theme_root,
            dry_run=args.dry_run,
            max_rounds=max(1, args.max_rounds),
            model=args.model,
        )
    return run_photos(theme_root, dry_run=args.dry_run, model=args.model)


if __name__ == "__main__":
    raise SystemExit(main())
