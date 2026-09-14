"""unsupported_line: a billed line with nothing in the documentation behind it.

Two tiers, because they are different problems. EVID-001 is an area nobody
documented at all. EVID-002 is an area that is documented but where nothing
matches what the rule pack asks for on this code. The second tier is marked
ambiguous: photo tagging in the field is unreliable and a reviewer, not this
tool, should settle it.
"""

from __future__ import annotations

from estimate_check.detectors.base import DetectorResult
from estimate_check.model import Check, Document, Evidence, Finding, Job, LineItem, Subject
from estimate_check.rulepack import RulePack

NAME = "unsupported_line"


def matches(doc: Document, requirement: dict) -> bool:
    kind = requirement.get("kind", "any")
    if kind != "any" and doc.kind != kind:
        return False
    tags_any = requirement.get("tags_any")
    if tags_any and not set(doc.tags) & set(tags_any):
        return False
    text_any = requirement.get("text_any")
    if text_any:
        haystack = f"{doc.text} {' '.join(doc.tags)}".lower()
        if not any(needle.lower() in haystack for needle in text_any):
            return False
    return True


def describe(requirement: dict) -> str:
    kind = requirement.get("kind", "any")
    parts = [f"a {kind.replace('_', ' ')}" if kind != "any" else "any documentation"]
    if requirement.get("tags_any"):
        parts.append("tagged " + " or ".join(requirement["tags_any"]))
    if requirement.get("text_any"):
        parts.append("mentioning " + " or ".join(requirement["text_any"]))
    return " ".join(parts)


def candidate_documents(job: Job, line: LineItem) -> tuple[Document, ...]:
    if line.area_id is None:
        return job.documents
    return job.documents_for_area(line.area_id)


def run(job: Job, pack: RulePack) -> DetectorResult:
    findings: list[Finding] = []
    checks: list[tuple[str, Check]] = []
    rules = {rule["rule_id"]: rule for rule in pack.evidence_rules}

    for line in job.line_items:
        spec = pack.spec(line.code)
        where = line.area_id or "job wide"
        if spec is None:
            checks.append(
                (
                    line.line_id,
                    Check(
                        rule_id="EVID-001",
                        detector=NAME,
                        status="skipped",
                        reason=f"code {line.code} is not defined in rule pack {pack.rulepack_id}, so no evidence requirement is known",
                    ),
                )
            )
            continue

        docs = candidate_documents(job, line)
        if not docs:
            rule = rules["EVID-001"]
            evidence = (
                Evidence(
                    kind="absence",
                    ref=f"documentation for {where}",
                    detail="no photo, note, scan or moisture reading is attached to this area",
                ),
            )
            findings.append(
                Finding(
                    detector=NAME,
                    rule_id="EVID-001",
                    severity=rule["severity"],
                    subject=Subject(
                        type="line_item",
                        area_id=line.area_id,
                        line_id=line.line_id,
                        code=line.code,
                        label=spec.label,
                    ),
                    reason=f"{line.code} is billed in {where} and nothing in the job package documents that area.",
                    evidence=evidence,
                )
            )
            checks.append(
                (
                    line.line_id,
                    Check("EVID-001", NAME, "fail", "no documentation covers this area", evidence),
                )
            )
            continue

        requirements = spec.evidence_any_of or ({"kind": "any"},)
        supporting: list[tuple[Document, dict]] = []
        for requirement in requirements:
            for doc in docs:
                if matches(doc, requirement):
                    supporting.append((doc, requirement))
                    break

        if supporting:
            doc, requirement = supporting[0]
            evidence = tuple(
                Evidence(
                    kind="document",
                    ref=hit.doc_id,
                    detail=f"{hit.kind}{(' tagged ' + ', '.join(hit.tags)) if hit.tags else ''}",
                )
                for hit, _ in supporting
            )
            checks.append(
                (
                    line.line_id,
                    Check(
                        "EVID-001",
                        NAME,
                        "pass",
                        f"{doc.doc_id} satisfies the requirement for {describe(requirement)}",
                        evidence,
                    ),
                )
            )
            continue

        rule = rules["EVID-002"]
        wanted = " or ".join(describe(requirement) for requirement in requirements)
        evidence = tuple(
            Evidence(kind="document", ref=doc.doc_id, detail=f"{doc.kind}, does not match the requirement")
            for doc in docs[:4]
        ) + (
            Evidence(kind="absence", ref=f"{line.code} evidence requirement", detail=wanted),
        )
        findings.append(
            Finding(
                detector=NAME,
                rule_id="EVID-002",
                severity=rule["severity"],
                subject=Subject(
                    type="line_item",
                    area_id=line.area_id,
                    line_id=line.line_id,
                    code=line.code,
                    label=spec.label,
                ),
                reason=(
                    f"{line.code} is billed in {where}. That area has {len(docs)} document(s), "
                    f"but none of them is {wanted}."
                ),
                evidence=evidence,
                ambiguous=bool(rule.get("ambiguous", False)),
            )
        )
        checks.append(
            (
                line.line_id,
                Check("EVID-002", NAME, "fail", f"no document in this area is {wanted}", evidence),
            )
        )

    return DetectorResult(tuple(findings), tuple(checks))
