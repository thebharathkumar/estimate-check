"""Shared machinery for the detectors.

Two things live here because every detector needs them and they are the part
most likely to be wrong: how a quantity basis is computed from the room
measurements, and how a rule condition is read off the job.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from estimate_check.model import Area, Check, Evidence, Finding, Job, LineItem
from estimate_check.rulepack import RulePack


@dataclass(frozen=True)
class DetectorResult:
    """Findings plus the per line checks that produced them."""

    findings: tuple[Finding, ...] = ()
    checks: tuple[tuple[str, Check], ...] = ()


@dataclass(frozen=True)
class Basis:
    """An expected quantity derived from measurements, or a reason there is none."""

    value: float | None
    label: str
    evidence: tuple[Evidence, ...] = ()
    skip_reason: str = ""


def areas_for_line(job: Job, line: LineItem) -> tuple[Area, ...]:
    """A line scoped to an area measures that area. A job wide line measures all of them."""
    if line.area_id is None:
        return job.areas
    area = job.area(line.area_id)
    return (area,) if area is not None else ()


def _measure(areas: tuple[Area, ...], attr: str) -> float:
    return sum(getattr(area, attr) for area in areas)


def _measurement_evidence(areas: tuple[Area, ...], attr: str) -> tuple[Evidence, ...]:
    return tuple(
        Evidence(
            kind="measurement",
            ref=f"{area.area_id}.{attr}",
            detail=f"{getattr(area, attr):.2f}",
        )
        for area in areas
    )


def resolve_basis(job: Job, pack: RulePack, line: LineItem, basis: str) -> Basis:
    """Compute the quantity the rule pack expects for this line.

    Returns a Basis with value None when the pack has no way to check the line.
    A skipped check is still reported to the operator.
    """
    areas = areas_for_line(job, line)
    if basis == "none":
        return Basis(None, basis, skip_reason="the rule pack assigns no quantity basis to this code")
    if not areas:
        return Basis(None, basis, skip_reason="no area measurements are attached to this line")

    simple = {
        "floor_sf": "floor_sf",
        "ceiling_sf": "ceiling_sf",
        "perimeter_lf": "perimeter_lf",
        "affected_floor_sf": "affected_floor_sf",
        "affected_wall_sf": "affected_wall_sf",
        "affected_ceiling_sf": "affected_ceiling_sf",
        "wall_sf": "wall_sf",
    }
    if basis in simple:
        attr = simple[basis]
        return Basis(_measure(areas, attr), basis, _measurement_evidence(areas, attr))

    if basis == "affected_floor_plus_wall_sf":
        value = _measure(areas, "affected_floor_sf") + _measure(areas, "affected_wall_sf")
        evidence = _measurement_evidence(areas, "affected_floor_sf") + _measurement_evidence(
            areas, "affected_wall_sf"
        )
        return Basis(value, basis, evidence)

    if basis in ("flood_cut_2ft_sf", "flood_cut_4ft_sf"):
        constant_name = "flood_cut_height_2ft" if basis.endswith("2ft_sf") else "flood_cut_height_4ft"
        height = pack.constant(constant_name)
        value = _measure(areas, "perimeter_lf") * height
        evidence = _measurement_evidence(areas, "perimeter_lf") + (
            Evidence(kind="rule_constant", ref=constant_name, detail=f"{height:g} ft"),
        )
        return Basis(value, basis, evidence)

    if basis == "airmover_unit_days":
        if job.planned_drying_days <= 0:
            return Basis(None, basis, skip_reason="the job package records no planned drying days")
        per_unit = pack.constant("sf_per_airmover")
        units = math.ceil(_measure(areas, "affected_floor_sf") / per_unit) if per_unit else 0
        value = float(units * job.planned_drying_days)
        evidence = _measurement_evidence(areas, "affected_floor_sf") + (
            Evidence(kind="rule_constant", ref="sf_per_airmover", detail=f"{per_unit:g} SF per unit"),
            Evidence(kind="scope", ref="loss.planned_drying_days", detail=str(job.planned_drying_days)),
        )
        return Basis(value, basis, evidence)

    if basis == "dehu_unit_days":
        if job.planned_drying_days <= 0:
            return Basis(None, basis, skip_reason="the job package records no planned drying days")
        per_unit = pack.constant("cuft_per_dehumidifier")
        volume = sum(area.affected_volume_cuft for area in areas)
        units = math.ceil(volume / per_unit) if per_unit else 0
        value = float(units * job.planned_drying_days)
        evidence = tuple(
            Evidence(
                kind="measurement",
                ref=f"{area.area_id}.affected_volume_cuft",
                detail=f"{area.affected_volume_cuft:.2f}",
            )
            for area in areas
        ) + (
            Evidence(kind="rule_constant", ref="cuft_per_dehumidifier", detail=f"{per_unit:g} cuft per unit"),
            Evidence(kind="scope", ref="loss.planned_drying_days", detail=str(job.planned_drying_days)),
        )
        return Basis(value, basis, evidence)

    if basis == "drying_days":
        if job.planned_drying_days <= 0:
            return Basis(None, basis, skip_reason="the job package records no planned drying days")
        return Basis(
            float(job.planned_drying_days),
            basis,
            (Evidence(kind="scope", ref="loss.planned_drying_days", detail=str(job.planned_drying_days)),),
        )

    if basis == "matches_removed_wall_sf":
        removed = [
            other
            for other in job.lines_in_area(line.area_id)
            if other.code.startswith("DEMO-DRY-")
        ]
        if not removed:
            return Basis(
                None,
                basis,
                skip_reason="no drywall removal is billed in this area to compare against, which the sequence rules cover instead",
            )
        value = sum(other.quantity for other in removed)
        evidence = tuple(
            Evidence(kind="line_item", ref=other.line_id, detail=f"{other.code} {other.quantity:g} {other.unit}")
            for other in removed
        )
        return Basis(value, basis, evidence)

    return Basis(None, basis, skip_reason=f"unknown quantity basis {basis!r} in the rule pack")


def condition_holds(
    when: dict, job: Job, area: Area | None = None
) -> tuple[bool, tuple[Evidence, ...]]:
    """Evaluate a required_rules condition block.

    Every supported key is listed here. An unknown key makes the condition
    false rather than silently true, so a typo in a rule pack cannot turn into
    a rule that fires on every job.
    """
    evidence: list[Evidence] = []
    area_codes = {line.code for line in job.lines_in_area(area.area_id)} if area else set()
    job_codes = {line.code for line in job.line_items}

    for key, want in when.items():
        if key == "water_category_min":
            if job.water_category is None or job.water_category < want:
                return False, ()
            evidence.append(
                Evidence(kind="scope", ref="loss.water_category", detail=str(job.water_category))
            )
        elif key == "drying_class_min":
            if job.drying_class is None or job.drying_class < want:
                return False, ()
            evidence.append(
                Evidence(kind="scope", ref="loss.drying_class", detail=str(job.drying_class))
            )
        elif key == "includes_rebuild":
            if job.includes_rebuild != want:
                return False, ()
            evidence.append(
                Evidence(kind="scope", ref="includes_rebuild", detail=str(job.includes_rebuild).lower())
            )
        elif key == "area_scope_any":
            if area is None:
                return False, ()
            hits = [tag for tag in want if tag in area.scope]
            if not hits:
                return False, ()
            evidence.append(
                Evidence(kind="scope", ref=f"{area.area_id}.scope", detail=", ".join(hits))
            )
        elif key == "area_has_code_any":
            if area is None:
                return False, ()
            hits = [code for code in want if code in area_codes]
            if not hits:
                return False, ()
            evidence.extend(_line_evidence(job, area.area_id, hits))
        elif key == "area_has_code_prefix_any":
            if area is None:
                return False, ()
            hits = sorted(c for c in area_codes if any(c.startswith(p) for p in want))
            if not hits:
                return False, ()
            evidence.extend(_line_evidence(job, area.area_id, hits))
        elif key == "job_has_code_any":
            hits = [code for code in want if code in job_codes]
            if not hits:
                return False, ()
            evidence.extend(_line_evidence(job, None, hits, any_area=True))
        elif key == "job_has_code_prefix_any":
            hits = sorted(c for c in job_codes if any(c.startswith(p) for p in want))
            if not hits:
                return False, ()
            evidence.extend(_line_evidence(job, None, hits, any_area=True))
        else:
            return False, ()
    return True, tuple(evidence)


def _line_evidence(
    job: Job, area_id: str | None, codes: list[str], any_area: bool = False
) -> list[Evidence]:
    out: list[Evidence] = []
    for line in job.line_items:
        if line.code not in codes:
            continue
        if not any_area and line.area_id != area_id:
            continue
        out.append(
            Evidence(kind="line_item", ref=line.line_id, detail=f"{line.code} in {line.area_id or 'job wide'}")
        )
    return out
