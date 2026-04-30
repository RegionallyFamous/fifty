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
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from _lib import resolve_theme_root  # noqa: E402

DEFAULT_MODEL = "claude-sonnet-4-6"
LAYOUTS_DIR = ROOT / "bin" / "design-layouts"
FRONTPAGE_SCORE_THRESHOLD = 70
OPENAI_IMAGE_MODEL = "gpt-image-2"


@dataclass
class ValidationResult:
    ok: bool
    detail: str


@dataclass
class LayoutChoice:
    layout_id: str
    confidence: float
    rationale: str
    evidence_quality: str
    slot_copy: dict[str, str]
    style_directives: list[str]
    source: str


@dataclass
class RepairProblem:
    problem: str
    confidence: float
    source_files: list[str]
    snapshots: list[str]
    next_actions: list[str]


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
    if not _block_comment_balance_ok(candidate):
        return ValidationResult(False, "candidate has unbalanced WordPress block comments")

    try:
        with tempfile.TemporaryDirectory(prefix="design-agent-theme-") as tmp:
            temp_theme = Path(tmp) / theme_root.name
            temp_theme.mkdir(parents=True)
            for file_name in ("theme.json", "style.css", "functions.php"):
                src = theme_root / file_name
                if src.is_file():
                    shutil.copy2(src, temp_theme / file_name)
            for dir_name in ("templates", "parts", "patterns"):
                src_dir = theme_root / dir_name
                if src_dir.is_dir():
                    shutil.copytree(src_dir, temp_theme / dir_name)
            temp_front_page = temp_theme / "templates" / "front-page.html"
            temp_front_page.parent.mkdir(parents=True, exist_ok=True)
            temp_front_page.write_text(candidate, encoding="utf-8")
            result = _run_block_validator(temp_theme)
    except Exception as exc:
        return ValidationResult(False, f"temporary validation failed: {exc}")

    if result.ok:
        staged = front_page.with_suffix(".html.tmp")
        staged.write_text(candidate, encoding="utf-8")
        staged.replace(front_page)
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


def _agent_dir(slug: str) -> Path:
    path = ROOT / "tmp" / "design-agent" / slug
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _load_layout_manifest() -> dict[str, dict[str, Any]]:
    manifest = _read_json(LAYOUTS_DIR / "manifest.json")
    layouts: dict[str, dict[str, Any]] = {}
    for entry in manifest.get("layouts") or []:
        if not isinstance(entry, dict):
            continue
        layout_id = str(entry.get("id") or "").strip()
        layout_file = LAYOUTS_DIR / str(entry.get("file") or "")
        if layout_id and layout_file.is_file():
            layouts[layout_id] = entry
    if not layouts:
        raise RuntimeError("no design layouts registered under bin/design-layouts")
    return layouts


def _layout_ids() -> list[str]:
    return sorted(_load_layout_manifest())


def _context_blob(context: dict[str, Any]) -> str:
    parts = [
        str(context.get("name") or ""),
        str(context.get("tagline") or ""),
        str(context.get("voice") or ""),
        " ".join(str(item) for item in context.get("layout_hints") or []),
        json.dumps(context.get("mockup_meta") or {}, sort_keys=True),
        str(context.get("brief") or ""),
    ]
    return " ".join(parts).lower()


def _default_slot_copy(slug: str, context: dict[str, Any]) -> dict[str, str]:
    name = str(context.get("name") or slug.replace("-", " ").title())
    tagline = str(context.get("tagline") or "").strip()
    voice = str(context.get("voice") or "").strip()
    dek = tagline or voice or f"{name} gathers strange goods into a shop with a point of view."
    return {
        "eyebrow": f"{name} dispatch",
        "headline": name,
        "dek": dek,
        "cta_label": "Shop the collection",
        "section_heading": "Featured oddities",
        "category_heading": "Browse the departments",
        "story_heading": "A shop with a sharper brief",
        "story_body": dek,
        "journal_heading": "Notes from the counter",
    }


def _heuristic_layout_choice(
    slug: str,
    context: dict[str, Any],
    *,
    evidence_quality: str,
    source: str = "heuristic",
) -> LayoutChoice:
    text = _context_blob(context)
    layout_id = "split-hero-category-strip"
    confidence = 0.58 if evidence_quality == "mockup" else 0.46
    rationale = "Defaulted to a balanced split commerce layout from available concept text."
    if any(token in text for token in ("poster", "brutalist", "bold", "zine", "campaign")):
        layout_id = "poster-cta-commerce-stack"
        rationale = "Concept language points to a poster-like, type-led commerce stack."
    elif any(
        token in text for token in ("magazine", "journal", "editorial", "publishing", "index")
    ):
        layout_id = "magazine-index-commerce"
        rationale = "Concept language emphasizes editorial or journal surfaces."
    elif any(token in text for token in ("center", "masthead", "fashion", "gallery", "luxury")):
        layout_id = "centered-masthead-editorial-grid"
        rationale = "Concept language favors a centered masthead and editorial product grid."
    elif any(
        token in text for token in ("photo", "cinematic", "hero image", "lookbook", "still life")
    ):
        layout_id = "photo-hero-product-grid"
        rationale = "Concept language calls for a photo-led hero and product-first follow-through."
    return LayoutChoice(
        layout_id=layout_id,
        confidence=confidence,
        rationale=rationale,
        evidence_quality=evidence_quality,
        slot_copy=_default_slot_copy(slug, context),
        style_directives=[],
        source=source,
    )


def _mockup_requirement(
    slug: str, *, keep_going: bool
) -> tuple[Path | None, str, list[RepairProblem]]:
    mockup = _mockup_path(slug)
    if mockup is not None:
        return mockup, "mockup", []

    repairs: list[RepairProblem] = []
    meta = ROOT / "mockups" / f"{slug}.meta.json"
    paint = ROOT / "bin" / "paint-mockup.py"
    if meta.is_file() and paint.is_file():
        prompt_out = _agent_dir(slug) / "mockup-prompt.json"
        proc = subprocess.run(
            [sys.executable, str(paint), slug, "--json"],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
        if proc.returncode == 0:
            prompt_out.write_text(proc.stdout, encoding="utf-8")
            source_files = [_safe_rel(meta), _safe_rel(prompt_out)]
        else:
            source_files = [_safe_rel(meta)]
    else:
        source_files = [_safe_rel(meta)] if meta.is_file() else []

    repairs.append(
        RepairProblem(
            problem="missing-mockup",
            confidence=0.4,
            source_files=source_files,
            snapshots=[],
            next_actions=[
                f"Generate mockups/mockup-{slug}.png from the concept card prompt before judging concept fit."
            ],
        )
    )
    if keep_going:
        return None, "meta-only", repairs
    return None, "missing", repairs


def _classifier_prompt(
    slug: str,
    context: dict[str, Any],
    layouts: dict[str, dict[str, Any]],
    evidence_quality: str,
) -> tuple[str, str]:
    system = (
        "You are a design director choosing from a constrained WordPress front-page "
        "layout system. Return only JSON. Do not write HTML."
    )
    prompt = f"""\
Choose the best validated front-page skeleton for `{slug}`.

Evidence quality: {evidence_quality}

Concept context:
{json.dumps(context, indent=2)[:12000]}

Available skeletons:
{json.dumps(list(layouts.values()), indent=2)[:12000]}

Return JSON with exactly these keys:
{{
  "layout_id": "one registered id",
  "confidence": 0.0,
  "rationale": "why this layout matches the concept",
  "slot_copy": {{
    "eyebrow": "...",
    "headline": "...",
    "dek": "...",
    "cta_label": "...",
    "section_heading": "...",
    "category_heading": "...",
    "story_heading": "...",
    "story_body": "...",
    "journal_heading": "..."
  }},
  "style_directives": ["short directive", "..."]
}}

Rules:
- Pick one of the registered `layout_id` values only.
- Slot copy must be shopper-facing and brand-specific, but concise.
- Do not invent forms, scripts, custom blocks, shortcodes, or raw CSS.
"""
    return system, prompt


def _parse_layout_choice(
    raw: dict[str, Any],
    *,
    slug: str,
    context: dict[str, Any],
    layouts: dict[str, dict[str, Any]],
    evidence_quality: str,
    source: str,
) -> LayoutChoice:
    layout_id = str(raw.get("layout_id") or "").strip()
    if layout_id not in layouts:
        raise ValueError(
            f"invalid layout_id {layout_id!r}; expected one of {', '.join(sorted(layouts))}"
        )
    confidence_raw = raw.get("confidence", 0.5)
    try:
        confidence = (
            float(confidence_raw)
            if isinstance(confidence_raw, (int, float))
            else float(str(confidence_raw))
        )
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))
    defaults = _default_slot_copy(slug, context)
    slot_raw = raw.get("slot_copy") or {}
    slot_copy = dict(defaults)
    if isinstance(slot_raw, dict):
        for slot in layouts[layout_id].get("slots") or []:
            value = str(slot_raw.get(slot) or "").strip()
            if value:
                slot_copy[str(slot)] = value
    directives_raw = raw.get("style_directives") or []
    directives = [str(item).strip() for item in directives_raw if str(item).strip()]
    return LayoutChoice(
        layout_id=layout_id,
        confidence=confidence,
        rationale=str(raw.get("rationale") or "").strip(),
        evidence_quality=evidence_quality,
        slot_copy=slot_copy,
        style_directives=directives,
        source=source,
    )


def _classify_layout(
    slug: str,
    context: dict[str, Any],
    *,
    mockup: Path | None,
    evidence_quality: str,
    model: str,
) -> LayoutChoice:
    layouts = _load_layout_manifest()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return _heuristic_layout_choice(slug, context, evidence_quality=evidence_quality)

    system, prompt = _classifier_prompt(slug, context, layouts, evidence_quality)
    raw = _completion(
        prompt=prompt,
        system_prompt=system,
        mockup=mockup,
        model=model,
        max_output_tokens=5000,
    )
    parsed = _parse_json_object(raw)
    return _parse_layout_choice(
        parsed,
        slug=slug,
        context=context,
        layouts=layouts,
        evidence_quality=evidence_quality,
        source="llm",
    )


def _render_layout(slug: str, choice: LayoutChoice) -> str:
    layouts = _load_layout_manifest()
    layout = layouts[choice.layout_id]
    template = (LAYOUTS_DIR / str(layout["file"])).read_text(encoding="utf-8")
    values = {slot: choice.slot_copy.get(slot, "") for slot in layout.get("slots") or []}
    values["slug"] = slug

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        value = str(values.get(key, ""))
        if key == "slug":
            return re.sub(r"[^a-z0-9-]", "-", value.lower()).strip("-") or slug
        return html.escape(value, quote=False)

    return re.sub(r"\{\{([a-z0-9_]+)\}\}", repl, template).rstrip() + "\n"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_repair_packet(slug: str, problems: list[RepairProblem]) -> Path | None:
    if not problems:
        return None
    path = _agent_dir(slug) / "repair.json"
    _write_json(
        path,
        {
            "schema": 1,
            "theme": slug,
            "generated_at": time.time(),
            "problems": [asdict(problem) for problem in problems],
        },
    )
    return path


def _run_frontpage_evidence(
    slug: str, *, keep_going: bool, threshold: int
) -> tuple[dict[str, Any], list[RepairProblem], bool]:
    result: dict[str, Any] = {
        "snapshots": [],
        "scorecard": None,
        "status": "skipped",
    }
    repairs: list[RepairProblem] = []
    if os.environ.get("FIFTY_DESIGN_AGENT_SKIP_EVIDENCE") == "1":
        result["reason"] = "FIFTY_DESIGN_AGENT_SKIP_EVIDENCE=1"
        return result, repairs, True

    snap_cmd = [
        sys.executable,
        str(ROOT / "bin" / "snap.py"),
        "shoot",
        slug,
        "--routes",
        "home",
        "--viewports",
        "mobile,desktop",
    ]
    try:
        snap = subprocess.run(
            snap_cmd,
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=900,
            check=False,
        )
    except Exception as exc:
        repairs.append(
            RepairProblem(
                problem="low-layout-score",
                confidence=0.0,
                source_files=[],
                snapshots=result["snapshots"],
                next_actions=[
                    f"Home snap could not run ({exc}); inspect Playground before shipping."
                ],
            )
        )
        result["status"] = "snap-failed"
        result["snap_error"] = str(exc)
        return result, repairs, keep_going
    result["snap_returncode"] = snap.returncode
    result["snapshots"] = [
        f"tmp/snaps/{slug}/mobile/home.png",
        f"tmp/snaps/{slug}/desktop/home.png",
    ]
    if snap.returncode != 0:
        repairs.append(
            RepairProblem(
                problem="low-layout-score",
                confidence=0.0,
                source_files=[],
                snapshots=result["snapshots"],
                next_actions=["Re-run the home snap and inspect the snap output before shipping."],
            )
        )
        result["status"] = "snap-failed"
        return result, repairs, keep_going

    score_out = _agent_dir(slug) / "frontpage-score.json"
    score_cmd = [
        sys.executable,
        str(ROOT / "bin" / "design-scorecard.py"),
        slug,
        "--run-id",
        f"design-agent-{slug}",
        "--threshold",
        str(threshold),
        "--out",
        str(score_out),
        "--no-fail",
    ]
    try:
        score = subprocess.run(
            score_cmd,
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
    except Exception as exc:
        repairs.append(
            RepairProblem(
                problem="low-layout-score",
                confidence=0.0,
                source_files=[],
                snapshots=result["snapshots"],
                next_actions=[
                    f"Design scorecard could not run ({exc}); inspect snap evidence manually."
                ],
            )
        )
        result["status"] = "score-failed"
        result["score_error"] = str(exc)
        return result, repairs, keep_going
    result["score_returncode"] = score.returncode
    result["scorecard"] = _safe_rel(score_out)
    score_data = _read_json(score_out)
    result["score_overall"] = score_data.get("overall")
    result["score_verdict"] = score_data.get("verdict")
    result["status"] = "pass" if score_data.get("verdict") == "pass" else "fail"
    if score_data.get("verdict") != "pass":
        repairs.append(
            RepairProblem(
                problem="low-layout-score",
                confidence=0.45,
                source_files=[_safe_rel(score_out)],
                snapshots=result["snapshots"],
                next_actions=[
                    str(score_data.get("next_action") or "Inspect the scorecard weak findings.")
                ],
            )
        )
    return result, repairs, keep_going or score_data.get("verdict") == "pass"


def run_frontpage(
    theme_root: Path,
    *,
    dry_run: bool,
    max_rounds: int,
    model: str,
    keep_going: bool,
    score_threshold: int,
) -> int:
    del (
        max_rounds
    )  # Skeleton rendering is deterministic; retry loops are for the old freehand path.
    slug = theme_root.name
    front_page = theme_root / "templates" / "front-page.html"
    if not front_page.is_file():
        print(f"design-agent frontpage: {front_page.relative_to(ROOT)} missing", file=sys.stderr)
        return 1

    context = _load_spec_context(slug, theme_root)
    mockup, evidence_quality, repairs = _mockup_requirement(slug, keep_going=keep_going)
    if evidence_quality == "missing":
        repair_path = _write_repair_packet(slug, repairs)
        if repair_path:
            print(f"  [design-agent/frontpage] wrote {_safe_rel(repair_path)}", file=sys.stderr)
        print(f"design-agent frontpage: missing mockups/mockup-{slug}.png", file=sys.stderr)
        return 1

    if dry_run:
        layouts = _load_layout_manifest()
        choice = _heuristic_layout_choice(
            slug, context, evidence_quality=evidence_quality, source="dry-run"
        )
        print("---- DESIGN AGENT FRONTPAGE CLASSIFIER (dry-run) ----")
        print(f"mockup: {_safe_rel(mockup) if mockup else '(missing; meta-only mode)'}")
        print(f"available_layouts: {', '.join(sorted(layouts))}")
        print(json.dumps(asdict(choice), indent=2))
        print("---- END CLASSIFIER ----")
        return 0

    try:
        choice = _classify_layout(
            slug,
            context,
            mockup=mockup,
            evidence_quality=evidence_quality,
            model=model,
        )
    except Exception as exc:
        fallback_choice = _heuristic_layout_choice(
            slug, context, evidence_quality=evidence_quality, source="heuristic-fallback"
        )
        repairs.append(
            RepairProblem(
                problem="validator-fallback",
                confidence=fallback_choice.confidence,
                source_files=[],
                snapshots=[],
                next_actions=[
                    f"LLM layout classifier failed ({exc}); inspect heuristic layout choice."
                ],
            )
        )
        choice = fallback_choice

    candidate = _render_layout(slug, choice)
    validation = _write_candidate_if_valid(theme_root, candidate)
    if not validation.ok:
        fallback_script = ROOT / "bin" / "diversify-front-page.py"
        subprocess.call([sys.executable, str(fallback_script), "--theme", slug], cwd=str(ROOT))
        repairs.append(
            RepairProblem(
                problem="validator-fallback",
                confidence=choice.confidence,
                source_files=[_safe_rel(front_page)],
                snapshots=[],
                next_actions=[
                    "Selected skeleton failed block validation; inspect validator details in frontpage-result.json."
                ],
            )
        )
        result_payload = {
            "schema": 1,
            "theme": slug,
            "selected_skeleton": choice.layout_id,
            "choice": asdict(choice),
            "validator": asdict(validation),
            "snap_paths": [],
            "scorecard": None,
            "status": "validator-fallback",
        }
        _write_json(_agent_dir(slug) / "frontpage-result.json", result_payload)
        repair_path = _write_repair_packet(slug, repairs)
        if repair_path:
            print(f"  [design-agent/frontpage] wrote {_safe_rel(repair_path)}", file=sys.stderr)
        return 0 if keep_going else 1

    evidence, evidence_repairs, evidence_ok = _run_frontpage_evidence(
        slug,
        keep_going=keep_going,
        threshold=score_threshold,
    )
    repairs.extend(evidence_repairs)
    result_payload = {
        "schema": 1,
        "theme": slug,
        "selected_skeleton": choice.layout_id,
        "choice": asdict(choice),
        "validator": asdict(validation),
        "snap_paths": evidence.get("snapshots", []),
        "scorecard": evidence.get("scorecard"),
        "score": {
            "overall": evidence.get("score_overall"),
            "verdict": evidence.get("score_verdict"),
            "threshold": score_threshold,
            "status": evidence.get("status"),
        },
        "status": "pass" if evidence_ok and not repairs else "needs-repair",
    }
    out = _agent_dir(slug) / "frontpage-result.json"
    _write_json(out, result_payload)
    repair_path = _write_repair_packet(slug, repairs)
    print(f"  [design-agent/frontpage] selected {choice.layout_id} ({choice.confidence:.2f})")
    print(f"  [design-agent/frontpage] wrote {_safe_rel(out)}")
    if repair_path:
        print(f"  [design-agent/frontpage] wrote {_safe_rel(repair_path)}", file=sys.stderr)
    return 0 if evidence_ok else 1


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
        {"model": OPENAI_IMAGE_MODEL, "prompt": prompt, "size": "1024x1024", "n": 1},
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
    except Exception as exc:
        raise RuntimeError("provider output could not be normalized to JPEG") from exc


def _fallback_photos(slug: str, *, force: bool = False) -> int:
    script = ROOT / "bin" / "generate-product-photos.py"
    cmd = [sys.executable, str(script), "--theme", slug]
    if force:
        cmd.append("--force")
    return subprocess.call(cmd, cwd=str(ROOT))


def _write_photo_manifest(
    theme_root: Path,
    *,
    prompts: dict[str, str],
    provider: str,
    model: str,
    status: str,
    records: list[dict[str, Any]] | None = None,
) -> None:
    slug = theme_root.name
    prompt_manifest = theme_root / "playground" / "content" / "product-photo-prompts.json"
    _write_json(
        prompt_manifest,
        {
            "schema": 2,
            "theme": slug,
            "status": status,
            "provider": provider,
            "model": model,
            "prompts": prompts,
            "records": records or [],
        },
    )
    print(f"  [design-agent/photos] wrote {_safe_rel(prompt_manifest)}")


def run_photos(theme_root: Path, *, dry_run: bool, model: str, keep_going: bool) -> int:
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
        _write_photo_manifest(
            theme_root,
            prompts={},
            provider="pillow",
            model="generate-product-photos.py",
            status="placeholder-fallback",
            records=[{"error": str(exc)}],
        )
        repair_path = _write_repair_packet(
            slug,
            [
                RepairProblem(
                    problem="photo-fallback",
                    confidence=0.35,
                    source_files=[
                        _safe_rel(
                            theme_root / "playground" / "content" / "product-photo-prompts.json"
                        )
                    ],
                    snapshots=[],
                    next_actions=[
                        "Retry photo generation with ANTHROPIC_API_KEY and OPENAI_API_KEY or FAL_KEY available."
                    ],
                )
            ],
        )
        if repair_path:
            print(f"  [design-agent/photos] wrote {_safe_rel(repair_path)}", file=sys.stderr)
        rc = _fallback_photos(slug, force=True)
        return 0 if keep_going else rc
    try:
        parsed = _parse_json_object(raw)
    except Exception as exc:
        print(f"  [design-agent/photos] prompt JSON parse failed: {exc}", file=sys.stderr)
        _write_photo_manifest(
            theme_root,
            prompts={},
            provider="pillow",
            model="generate-product-photos.py",
            status="placeholder-fallback",
            records=[{"error": f"prompt JSON parse failed: {exc}"}],
        )
        rc = _fallback_photos(slug, force=True)
        return 0 if keep_going else rc

    prompt_map_raw = parsed.get("prompts") or {}
    if not isinstance(prompt_map_raw, dict):
        print(
            "  [design-agent/photos] prompt response omitted `prompts`; falling back",
            file=sys.stderr,
        )
        _write_photo_manifest(
            theme_root,
            prompts={},
            provider="pillow",
            model="generate-product-photos.py",
            status="placeholder-fallback",
            records=[{"error": "prompt response omitted prompts"}],
        )
        rc = _fallback_photos(slug, force=True)
        return 0 if keep_going else rc
    prompt_map = {str(k): str(v) for k, v in prompt_map_raw.items() if str(v).strip()}

    generator = None
    provider = "pillow"
    provider_model = "generate-product-photos.py"
    if os.environ.get("FAL_KEY"):
        generator = _generate_fal
        provider = "fal"
        provider_model = "fal-ai/flux/dev"
    elif os.environ.get("OPENAI_API_KEY"):
        generator = _generate_openai
        provider = "openai"
        provider_model = OPENAI_IMAGE_MODEL

    if generator is None:
        print("  [design-agent/photos] no FAL_KEY or OPENAI_API_KEY; using Pillow fallback")
        _write_photo_manifest(
            theme_root,
            prompts=prompt_map,
            provider=provider,
            model=provider_model,
            status="placeholder-fallback",
        )
        repair_path = _write_repair_packet(
            slug,
            [
                RepairProblem(
                    problem="photo-fallback",
                    confidence=0.45,
                    source_files=[
                        _safe_rel(
                            theme_root / "playground" / "content" / "product-photo-prompts.json"
                        )
                    ],
                    snapshots=[],
                    next_actions=[
                        "Set OPENAI_API_KEY or FAL_KEY for generated product photography."
                    ],
                )
            ],
        )
        if repair_path:
            print(f"  [design-agent/photos] wrote {_safe_rel(repair_path)}", file=sys.stderr)
        rc = _fallback_photos(slug, force=True)
        return 0 if keep_going else rc

    written = 0
    records: list[dict[str, Any]] = []
    images_dir = theme_root / "playground" / "images"
    for sku, filename in sorted(products.items()):
        image_prompt = prompt_map.get(sku)
        if not image_prompt:
            continue
        dest = images_dir / filename
        try:
            _write_image_bytes(dest, generator(image_prompt))
            written += 1
            records.append(
                {
                    "sku": sku,
                    "filename": filename,
                    "provider": provider,
                    "model": provider_model,
                    "prompt": image_prompt,
                    "status": "generated",
                }
            )
            print(f"  [design-agent/photos] generated {dest.relative_to(ROOT)}")
        except Exception as exc:
            records.append(
                {
                    "sku": sku,
                    "filename": filename,
                    "provider": provider,
                    "model": provider_model,
                    "prompt": image_prompt,
                    "status": "failed",
                    "error": str(exc),
                }
            )
            print(f"  [design-agent/photos] {sku} failed: {exc}", file=sys.stderr)

    status = "generated" if written else "placeholder-fallback"
    _write_photo_manifest(
        theme_root,
        prompts=prompt_map,
        provider=provider,
        model=provider_model,
        status=status,
        records=records,
    )
    if written == 0:
        repair_path = _write_repair_packet(
            slug,
            [
                RepairProblem(
                    problem="photo-fallback",
                    confidence=0.45,
                    source_files=[
                        _safe_rel(
                            theme_root / "playground" / "content" / "product-photo-prompts.json"
                        )
                    ],
                    snapshots=[],
                    next_actions=[
                        "Inspect provider errors and retry photo generation before shipping."
                    ],
                )
            ],
        )
        if repair_path:
            print(f"  [design-agent/photos] wrote {_safe_rel(repair_path)}", file=sys.stderr)

    # Fill any missing category/hero/product images with the existing generator,
    # but do not overwrite real API-generated product photos.
    fallback_rc = _fallback_photos(slug, force=False)
    if written == 0 and fallback_rc != 0:
        return 0 if keep_going else fallback_rc
    seed = ROOT / "bin" / "seed-playground-content.py"
    subprocess.call([sys.executable, str(seed), "--theme", slug], cwd=str(ROOT))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--theme", required=True, metavar="SLUG")
    parser.add_argument("--task", choices=("frontpage", "photos"), required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-rounds", type=int, default=3)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--strict", action="store_true", help="Fail hard when required evidence is missing."
    )
    mode.add_argument(
        "--keep-going", action="store_true", help="Emit repair packets and continue when possible."
    )
    parser.add_argument("--score-threshold", type=int, default=FRONTPAGE_SCORE_THRESHOLD)
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
            keep_going=args.keep_going or not args.strict,
            score_threshold=args.score_threshold,
        )
    return run_photos(
        theme_root,
        dry_run=args.dry_run,
        model=args.model,
        keep_going=args.keep_going or not args.strict,
    )


if __name__ == "__main__":
    raise SystemExit(main())
