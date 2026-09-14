"""Optional LLM judge for the ambiguous subset. Off by default.

What it is for: the deterministic detectors mark a small number of findings
ambiguous, which means the rule fired but the rule is known to be unreliable
for that case. A paint line with no primer on an existing wall, a quantity
twelve percent over the measured area, a photo that documents the room but
carries no tag the pack recognises. Those are judgement calls, and a rule pack
that turns them into errors trains an operator to ignore the tool.

What it is not for: replacing the detectors. The judge never creates, edits or
removes a deterministic finding. It attaches an advisory opinion, and the JSON
output keeps the two apart so that a downstream consumer can ignore the judge
entirely.

Honesty note: this code path has never been run against the live API from this
repository. There are no accuracy numbers for the judge anywhere in this repo
because none have been produced.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from estimate_check.model import AuditResult, Finding, Job, finding_id

DEFAULT_MODEL = "claude-opus-5"

SYSTEM_PROMPT = """You are reviewing findings from a deterministic verifier that audits
restoration estimate line items against a job's documentation and room measurements.

You are only shown findings the verifier itself marked ambiguous, which means the rule
fired but the rule is known to be unreliable for this kind of case.

For each finding, decide whether a careful estimator reviewing this job would raise it
with the person who wrote the estimate.

Rules for your answer:
- uphold means a reviewer should raise it. dismiss means the line is defensible as billed.
  unsure means the job package does not contain enough to tell.
- Judge only from the job package and the finding you are given. Do not assume facts
  about the property, the carrier or the contractor that are not in front of you.
- Prefer unsure over guessing. An unsure answer is useful; a confident wrong one is not.
- The rule pack in use is synthetic and generic. Do not treat its thresholds as authoritative."""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "reviews": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "finding_id": {"type": "string"},
                    "verdict": {"type": "string", "enum": ["uphold", "dismiss", "unsure"]},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                    "rationale": {"type": "string"},
                },
                "required": ["finding_id", "verdict", "confidence", "rationale"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["reviews"],
    "additionalProperties": False,
}


class JudgeUnavailable(RuntimeError):
    """Raised when the judge was asked for and cannot run."""


@dataclass(frozen=True)
class JudgeConfig:
    model: str = DEFAULT_MODEL
    max_findings: int = 12
    timeout: float = 120.0


def select_for_review(findings: tuple[Finding, ...], limit: int) -> tuple[Finding, ...]:
    """Only findings the deterministic layer marked ambiguous, oldest rule first."""
    ambiguous = [finding for finding in findings if finding.ambiguous]
    return tuple(ambiguous[:limit])


def job_context(job: Job) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "loss": {
            "type": job.loss_type,
            "water_category": job.water_category,
            "drying_class": job.drying_class,
            "planned_drying_days": job.planned_drying_days,
        },
        "includes_rebuild": job.includes_rebuild,
        "areas": [
            {
                "area_id": area.area_id,
                "name": area.name,
                "floor_sf": area.floor_sf,
                "perimeter_lf": area.perimeter_lf,
                "height_ft": area.height_ft,
                "affected_floor_sf": area.affected_floor_sf,
                "affected_wall_sf": area.affected_wall_sf,
                "materials": area.materials,
                "scope": list(area.scope),
            }
            for area in job.areas
        ],
        "documentation": [
            {
                "doc_id": doc.doc_id,
                "kind": doc.kind,
                "area_ids": list(doc.area_ids),
                "tags": list(doc.tags),
                "text": doc.text,
            }
            for doc in job.documents
        ],
        "line_items": [
            {
                "line_id": line.line_id,
                "code": line.code,
                "area_id": line.area_id,
                "quantity": line.quantity,
                "unit": line.unit,
            }
            for line in job.line_items
        ],
    }


def build_user_message(job: Job, findings: tuple[Finding, ...]) -> str:
    payload = {
        "job": job_context(job),
        "findings_to_review": [
            {
                "finding_id": finding_id(finding),
                "detector": finding.detector,
                "rule_id": finding.rule_id,
                "severity": finding.severity,
                "subject": finding.subject.to_dict(),
                "reason": finding.reason,
                "evidence": [item.to_dict() for item in finding.evidence],
            }
            for finding in findings
        ],
    }
    return (
        "Here is the job package and the ambiguous findings to review.\n\n"
        + json.dumps(payload, indent=2, sort_keys=True)
        + "\n\nReturn one review per finding_id, and no other finding ids."
    )


def build_client(config: JudgeConfig):
    try:
        import anthropic
    except ImportError as exc:
        raise JudgeUnavailable(
            "the judge needs the anthropic package: pip install 'estimate-check[judge]'"
        ) from exc
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        raise JudgeUnavailable(
            "the judge needs ANTHROPIC_API_KEY in the environment. The deterministic "
            "detectors do not, and they are the product. Run without --with-judge."
        )
    return anthropic.Anthropic(timeout=config.timeout)


def parse_reviews(text: str, expected_ids: set[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse the model's reply, dropping anything that is not about a finding we asked about."""
    problems: list[str] = []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise JudgeUnavailable(f"the judge did not return JSON: {exc}") from exc
    reviews = payload.get("reviews")
    if not isinstance(reviews, list):
        raise JudgeUnavailable("the judge returned no reviews array")

    kept: list[dict[str, Any]] = []
    seen: set[str] = set()
    for review in reviews:
        if not isinstance(review, dict):
            problems.append("dropped a review that was not an object")
            continue
        identifier = review.get("finding_id")
        if identifier not in expected_ids:
            problems.append(f"dropped a review for an unknown finding id {identifier!r}")
            continue
        if identifier in seen:
            problems.append(f"dropped a duplicate review for {identifier!r}")
            continue
        if review.get("verdict") not in ("uphold", "dismiss", "unsure"):
            problems.append(f"dropped a review for {identifier!r} with an unrecognised verdict")
            continue
        seen.add(identifier)
        kept.append(
            {
                "finding_id": identifier,
                "verdict": review["verdict"],
                "confidence": review.get("confidence", "low"),
                "rationale": review.get("rationale", ""),
            }
        )
    for missing in sorted(expected_ids - seen):
        problems.append(f"the judge returned no review for {missing!r}")
    return kept, problems


def run(result: AuditResult, config: JudgeConfig | None = None, client: Any = None) -> dict[str, Any]:
    """Review the ambiguous findings and return an advisory block.

    The returned dict is attached to the audit result as result.judge. The
    deterministic findings are not modified.
    """
    config = config or JudgeConfig()
    selected = select_for_review(result.findings, config.max_findings)
    if not selected:
        return {
            "model": config.model,
            "status": "skipped",
            "note": "no finding was marked ambiguous, so there was nothing for the judge to review",
            "reviews": [],
            "problems": [],
        }

    client = client or build_client(config)
    message = client.messages.create(
        model=config.model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_user_message(result.job, selected)}],
        output_config={"format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}},
    )
    text = next((block.text for block in message.content if block.type == "text"), "")
    reviews, problems = parse_reviews(text, {finding_id(f) for f in selected})
    return {
        "model": config.model,
        "status": "ran",
        "note": "advisory only; the deterministic findings above are unchanged",
        "reviewed": [finding_id(f) for f in selected],
        "reviews": reviews,
        "problems": problems,
    }
