"""Ambiguity escalation: ask the LLM structured yes/no questions with
evidence, cache answers by evidence hash, and surface them as review
artifacts.

Why this exists
---------------
`bin/check.py` is a bank of deterministic static gates. A rule is
either pass or fail, regardless of theme intent. That is correct for
crisp defect classes (a `<!-- wp:shortcode -->` block, a missing
required WC microcopy override, a placeholder `wonders-*.png` image)
but wrong for the taste-heavy questions that the Fifty monorepo actually
ships on:

  * "Are these two product photographs *visually* distinct, or is this
    the same template with different labels?" (the within-theme image
    diversity check flags ~pHash distance <= 5, but mockups of two very
    similar crafts legitimately cluster that close.)

  * "Is this cream-on-cream bar in the hero intentional breathing
    room, or the empty-hero placeholder bug?" (the placeholder-group
    check fires on both.)

  * "Does this microcopy in functions.php's my-account dashboard read
    as 'obel's voice' or 'this theme's voice'?" (rule #14 carves
    `functions.php` out of the hard check; the team still wants to
    know when the answer is borderline.)

For questions like these, the right tool is a vision / text LLM with
the rubric (`<theme>/design-intent.md`) and the evidence (the image, the
file excerpt, the adjacent files) available. The LLM produces a bounded
JSON answer (`verdict`, `confidence`, `rationale`, `needs_human`), and
we cache that answer by a hash of the evidence so repeated runs on
unchanged inputs do not re-bill the API.

Contract
--------
Callers invoke `ask_judgment()` with:
  * `question_id`: stable identifier (e.g. `product-image-diversity`)
    that groups answers into a per-theme review artifact.
  * `system_prompt`: tells the LLM what it is deciding and what the
    response schema is.
  * `user_prompt`: the specific question + inline evidence snippets.
  * `evidence_paths`: optional list of paths (images or text files) to
    hash into the cache key; `ask_judgment` does NOT upload text
    evidence — that's the user_prompt's job — but the hashes make the
    cache key content-addressable so an unchanged file short-circuits.
  * `theme_slug`: where to write the cached answer + audit row.

Return value is a `JudgmentAnswer` dataclass with:
  * `verdict`: one of {"pass", "fail", "needs_human"}
  * `confidence`: float in [0.0, 1.0]
  * `rationale`: <=800 chars free text
  * `cache_hit`: True if the answer came from cache
  * `model`: model used; empty for cache hits older than the schema
  * `raw_json`: the full decoded model output for debugging

Confidence thresholds
---------------------
The caller is responsible for applying confidence thresholds. The
documented convention in the plan is:
  * verdict=pass + confidence >= 0.8 -> passes the check
  * verdict=pass + 0.5 <= confidence < 0.8 -> pass-with-review
    (yields an `info` level finding so reviewers can audit)
  * verdict=pass + confidence < 0.5 -> demote to needs_human
  * verdict=fail -> fails the check regardless of confidence
  * verdict=needs_human -> caller emits a review question finding

Cache layout
------------
`tmp/judgment-cache/<theme>/<question_id>/<evidence-hash>.json` holds
one answer. A fresh run with the same question + evidence short-
circuits to cache. A rubric update (editing `<theme>/design-intent.md`)
is part of the evidence hash when the caller includes it, so a deliberate
rubric rewrite invalidates the cache without having to delete files.

`tmp/judgment-audit/<theme>/<question_id>.jsonl` appends every answer
(cache-hit or fresh) with a timestamp, so a reviewer can read the
pipeline's reasoning trail.

CI / dry-run behavior
---------------------
When `ANTHROPIC_API_KEY` is unset OR `FIFTY_JUDGMENT_DRY_RUN=1`, this
module does NOT call the LLM and returns a synthetic answer with
`verdict=needs_human` and `confidence=0.0` — the caller should degrade
gracefully (e.g. emit an `info` finding instead of blocking). This
keeps the pipeline deterministic on a fork or a detached checkout
without secrets, while still surfacing the ambiguity for later review.

Daily budget
------------
Every real call uses `_vision_lib.text_completion()` / `review_image()`
under the hood, so the `tmp/vision-spend.jsonl` ledger and
`FIFTY_VISION_DAILY_BUDGET` cap apply uniformly — there is no separate
budget for judgment calls.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import MONOREPO_ROOT
from _vision_lib import (
    ApiKeyMissingError,
    BudgetExceededError,
    VisionResponse,
    text_completion,
    vision_completion,
)

# UTC alias: datetime.UTC is 3.11+; fall back for 3.9/3.10.
UTC = getattr(dt, "UTC", dt.timezone.utc)  # noqa: UP017

CACHE_ROOT = MONOREPO_ROOT / "tmp" / "judgment-cache"
AUDIT_ROOT = MONOREPO_ROOT / "tmp" / "judgment-audit"

VALID_VERDICTS = ("pass", "fail", "needs_human")

SYSTEM_PROMPT_SUFFIX = """
Return a single JSON object with this shape:

{
  "verdict": "pass" | "fail" | "needs_human",
  "confidence": number in [0.0, 1.0],
  "rationale": short human-readable explanation (<= 800 chars),
  "notes": short optional follow-up suggestion or rubric-update hint (<= 400 chars)
}

Rules:
- If the evidence alone cannot answer the question, return
  verdict="needs_human" with confidence=0.0.
- Never invent certainty. If the rubric is silent on the point, say so
  in `rationale` and lean toward needs_human over an arbitrary pass/fail.
- Do not emit any prose outside the JSON object. Response MUST start
  with `{` and end with `}`.
"""


@dataclass
class JudgmentAnswer:
    """Structured response from the judgment layer."""

    verdict: str
    confidence: float
    rationale: str
    notes: str = ""
    cache_hit: bool = False
    model: str = ""
    raw_json: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.verdict == "pass" and self.confidence >= 0.8

    @property
    def needs_human(self) -> bool:
        return self.verdict == "needs_human" or (
            self.verdict == "pass" and self.confidence < 0.5
        )


def _hash_evidence(prompt: str, evidence_paths: list[Path]) -> str:
    """Build a content-addressable cache key from the prompt + every
    evidence file's content hash.

    We hash the PROMPT bytes too so a refined question invalidates the
    cache without having to ship a schema version bump.
    """
    h = hashlib.sha256()
    h.update(b"v2\n")
    h.update(prompt.encode("utf-8"))
    for p in evidence_paths:
        h.update(b"\n")
        h.update(str(p).encode("utf-8"))
        try:
            h.update(b":")
            h.update(p.read_bytes())
        except OSError:
            h.update(b":<missing>")
    return h.hexdigest()[:32]


def _cache_path(theme_slug: str, question_id: str, key: str) -> Path:
    return CACHE_ROOT / theme_slug / question_id / f"{key}.json"


def _audit_path(theme_slug: str, question_id: str) -> Path:
    return AUDIT_ROOT / theme_slug / f"{question_id}.jsonl"


def _load_cached(path: Path) -> JudgmentAnswer | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    verdict = data.get("verdict")
    if verdict not in VALID_VERDICTS:
        return None
    try:
        conf = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        return None
    return JudgmentAnswer(
        verdict=verdict,
        confidence=max(0.0, min(1.0, conf)),
        rationale=str(data.get("rationale", ""))[:800],
        notes=str(data.get("notes", ""))[:400],
        cache_hit=True,
        model=str(data.get("model", "")),
        raw_json=data,
    )


def _save_cached(path: Path, answer: JudgmentAnswer) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "verdict": answer.verdict,
                "confidence": answer.confidence,
                "rationale": answer.rationale,
                "notes": answer.notes,
                "model": answer.model,
                "cached_at": dt.datetime.now(UTC).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _append_audit(
    theme_slug: str,
    question_id: str,
    prompt: str,
    answer: JudgmentAnswer,
    evidence_key: str,
) -> None:
    path = _audit_path(theme_slug, question_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "ts": dt.datetime.now(UTC).isoformat(),
                    "question_id": question_id,
                    "evidence_key": evidence_key,
                    "prompt_head": prompt[:200],
                    "verdict": answer.verdict,
                    "confidence": answer.confidence,
                    "rationale": answer.rationale,
                    "notes": answer.notes,
                    "cache_hit": answer.cache_hit,
                    "model": answer.model,
                }
            )
            + "\n"
        )


def _parse_response(raw_text: str) -> dict:
    """Extract the single JSON object from the model's raw text.

    The LLM sometimes wraps its JSON in ```json fences or a stray
    preamble. This helper tolerates both by scanning for the first `{`
    and the matching `}`.
    """
    text = raw_text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}


def _answer_from_dict(data: dict, model: str) -> JudgmentAnswer:
    verdict = data.get("verdict")
    if verdict not in VALID_VERDICTS:
        return JudgmentAnswer(
            verdict="needs_human",
            confidence=0.0,
            rationale="LLM response did not include a valid `verdict` field.",
            model=model,
            raw_json=data,
        )
    try:
        conf = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    return JudgmentAnswer(
        verdict=verdict,
        confidence=max(0.0, min(1.0, conf)),
        rationale=str(data.get("rationale", ""))[:800],
        notes=str(data.get("notes", ""))[:400],
        model=model,
        raw_json=data,
    )


def _dry_run_answer(reason: str) -> JudgmentAnswer:
    return JudgmentAnswer(
        verdict="needs_human",
        confidence=0.0,
        rationale=f"(no LLM call: {reason})",
        notes="Set ANTHROPIC_API_KEY and unset FIFTY_JUDGMENT_DRY_RUN to enable.",
        cache_hit=False,
        model="",
    )


def ask_judgment(
    *,
    theme_slug: str,
    question_id: str,
    system_prompt: str,
    user_prompt: str,
    evidence_paths: list[Path] | None = None,
    image_path: Path | None = None,
    image_paths: list[Path] | None = None,
    use_cache: bool = True,
    dry_run: bool | None = None,
) -> JudgmentAnswer:
    """Ask the LLM a structured judgment question with evidence caching.

    Args:
        theme_slug: theme under review; scopes the cache + audit dirs.
        question_id: stable slug that groups answers of the same class
            (e.g. `product-image-diversity`).
        system_prompt: describes the decision the model is making. The
            module appends a response-schema suffix so callers don't
            have to hand-roll it.
        user_prompt: the specific question + inline evidence excerpts.
        evidence_paths: optional files (images, text) whose bytes enter
            the cache key. Pass the paths even if they are already
            referenced in user_prompt; the cache key is what detects
            "unchanged evidence". If empty but image paths are
            provided, the image paths populate the cache key instead so
            repeated image judgments short-circuit on unchanged bytes.
        image_path: optional single PNG to attach to the API call
            (legacy). Prefer `image_paths` for new callers.
        image_paths: optional list of PNGs to attach to the API call.
            All images are sent to the vision model in order — use this
            for pairwise judgments (e.g. "are these two product photos
            distinct?") so the model actually SEES the pixels. If any
            image paths are provided, the request uses the vision
            pathway; otherwise text-only.
        use_cache: set False to force a fresh call.
        dry_run: if None, inferred from ANTHROPIC_API_KEY /
            FIFTY_JUDGMENT_DRY_RUN. If True, returns a synthetic
            needs_human answer without calling the API.

    Returns:
        A JudgmentAnswer. Caller applies the confidence thresholds
        documented at the top of this module.
    """
    # Collect every image the caller wants sent (legacy single +
    # modern list). Filter to existing files so a missing path silently
    # falls through to text-only instead of 500-ing.
    images: list[Path] = []
    if image_path is not None and image_path.is_file():
        images.append(image_path)
    for p in image_paths or []:
        if p.is_file() and p not in images:
            images.append(p)

    # Cache key incorporates the prompt AND every piece of evidence
    # (explicit paths + image paths). Without this, a caller that
    # passes only `image_paths` (no `evidence_paths`) would keep hitting
    # the API on every run even when the images are byte-identical.
    all_evidence: list[Path] = list(evidence_paths or [])
    for p in images:
        if p not in all_evidence:
            all_evidence.append(p)

    key_prompt = system_prompt + "\n\n" + user_prompt
    cache_key = _hash_evidence(key_prompt, all_evidence)

    if use_cache:
        cached = _load_cached(_cache_path(theme_slug, question_id, cache_key))
        if cached is not None:
            _append_audit(theme_slug, question_id, user_prompt, cached, cache_key)
            return cached

    if dry_run is None:
        dry_run = (
            os.environ.get("FIFTY_JUDGMENT_DRY_RUN") == "1"
            or not os.environ.get("ANTHROPIC_API_KEY")
        )
    if dry_run:
        answer = _dry_run_answer(
            "ANTHROPIC_API_KEY unset" if not os.environ.get("ANTHROPIC_API_KEY")
            else "FIFTY_JUDGMENT_DRY_RUN=1"
        )
        _append_audit(theme_slug, question_id, user_prompt, answer, cache_key)
        return answer

    full_system = system_prompt.rstrip() + "\n\n" + SYSTEM_PROMPT_SUFFIX

    try:
        resp: VisionResponse
        if images:
            # Use the low-level vision primitive directly so the
            # caller's system+user prompts reach the model. (review_image
            # would override both with the snap-review rubric.)
            resp = vision_completion(
                png_path=images[0],
                extra_png_paths=images[1:] if len(images) > 1 else None,
                system_prompt=full_system,
                user_prompt=user_prompt,
                theme=theme_slug,
                route=question_id,
            )
        else:
            resp = text_completion(
                system_prompt=full_system,
                user_prompt=user_prompt,
                label=f"judgment:{theme_slug}:{question_id}",
            )
    except (ApiKeyMissingError, BudgetExceededError) as exc:
        answer = _dry_run_answer(str(exc))
        _append_audit(theme_slug, question_id, user_prompt, answer, cache_key)
        return answer

    data = _parse_response(resp.raw_text)
    answer = _answer_from_dict(data, model=resp.model)

    if use_cache:
        _save_cached(_cache_path(theme_slug, question_id, cache_key), answer)
    _append_audit(theme_slug, question_id, user_prompt, answer, cache_key)
    return answer


def collect_audit_rows(theme_slug: str) -> list[dict]:
    """Return every audit row written for `theme_slug`, most recent
    first. Used by the review artifact builder to surface the pipeline's
    reasoning trail next to the deterministic findings."""
    root = AUDIT_ROOT / theme_slug
    if not root.is_dir():
        return []
    rows: list[dict] = []
    for path in sorted(root.glob("*.jsonl")):
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except OSError:
            continue
    rows.sort(key=lambda r: r.get("ts", ""), reverse=True)
    return rows
