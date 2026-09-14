"""Reading and validating a job package from JSON.

Validation is strict about the things a rule needs to cite (ids, units,
numbers) and permissive about everything else, because real job packages will
carry fields this tool has never heard of.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from estimate_check.model import Area, Document, Job, LineItem

DOCUMENT_KINDS = ("photo", "note", "scan", "moisture_reading", "voice_walkthrough")


class JobLoadError(ValueError):
    """Raised when a job package cannot be read as a job package."""


def _number(value: Any, field: str, source: str, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JobLoadError(f"{source}: {field} must be a number, got {value!r}")
    return float(value)


def _string(value: Any, field: str, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise JobLoadError(f"{source}: {field} must be a non empty string, got {value!r}")
    return value


def _parse_area(raw: dict[str, Any], source: str) -> Area:
    if not isinstance(raw, dict):
        raise JobLoadError(f"{source}: each entry in areas must be an object")
    area_id = _string(raw.get("area_id"), "area.area_id", source)
    affected = raw.get("affected", {}) or {}
    if not isinstance(affected, dict):
        raise JobLoadError(f"{source}: area {area_id} affected block must be an object")
    return Area(
        area_id=area_id,
        name=raw.get("name") or area_id,
        floor_sf=_number(raw.get("floor_sf"), f"area {area_id} floor_sf", source),
        ceiling_sf=_number(raw.get("ceiling_sf"), f"area {area_id} ceiling_sf", source),
        perimeter_lf=_number(raw.get("perimeter_lf"), f"area {area_id} perimeter_lf", source),
        height_ft=_number(raw.get("height_ft"), f"area {area_id} height_ft", source, 8.0),
        affected_floor_sf=_number(affected.get("floor_sf"), f"area {area_id} affected.floor_sf", source),
        affected_wall_sf=_number(affected.get("wall_sf"), f"area {area_id} affected.wall_sf", source),
        affected_ceiling_sf=_number(affected.get("ceiling_sf"), f"area {area_id} affected.ceiling_sf", source),
        materials=dict(raw.get("materials") or {}),
        scope=tuple(raw.get("scope") or ()),
        note=raw.get("note", ""),
    )


def _parse_document(raw: dict[str, Any], source: str, known_areas: set[str]) -> Document:
    if not isinstance(raw, dict):
        raise JobLoadError(f"{source}: each entry in documentation must be an object")
    doc_id = _string(raw.get("doc_id"), "document.doc_id", source)
    kind = raw.get("kind", "photo")
    if kind not in DOCUMENT_KINDS:
        raise JobLoadError(
            f"{source}: document {doc_id} has kind {kind!r}, expected one of {', '.join(DOCUMENT_KINDS)}"
        )
    area_ids = raw.get("area_ids")
    if area_ids is None:
        single = raw.get("area_id")
        area_ids = [single] if single else []
    if not isinstance(area_ids, list):
        raise JobLoadError(f"{source}: document {doc_id} area_ids must be a list")
    for area_id in area_ids:
        if area_id not in known_areas:
            raise JobLoadError(
                f"{source}: document {doc_id} points at unknown area {area_id!r}"
            )
    return Document(
        doc_id=doc_id,
        kind=kind,
        area_ids=tuple(area_ids),
        tags=tuple(raw.get("tags") or ()),
        text=raw.get("text", ""),
        captured_at=raw.get("captured_at"),
    )


def _parse_line(raw: dict[str, Any], source: str, known_areas: set[str]) -> LineItem:
    if not isinstance(raw, dict):
        raise JobLoadError(f"{source}: each entry in line_items must be an object")
    line_id = _string(raw.get("line_id"), "line_item.line_id", source)
    area_id = raw.get("area_id")
    if area_id is not None and area_id not in known_areas:
        raise JobLoadError(f"{source}: line {line_id} points at unknown area {area_id!r}")
    unit_price = raw.get("unit_price")
    return LineItem(
        line_id=line_id,
        code=_string(raw.get("code"), f"line {line_id} code", source),
        description=raw.get("description", ""),
        area_id=area_id,
        quantity=_number(raw.get("quantity"), f"line {line_id} quantity", source),
        unit=raw.get("unit", ""),
        unit_price=None if unit_price is None else _number(unit_price, f"line {line_id} unit_price", source),
    )


def parse_job(payload: dict[str, Any], source: str = "<memory>") -> Job:
    if not isinstance(payload, dict):
        raise JobLoadError(f"{source}: job package must be a JSON object")
    job_id = _string(payload.get("job_id"), "job_id", source)

    raw_areas = payload.get("areas") or []
    if not isinstance(raw_areas, list):
        raise JobLoadError(f"{source}: areas must be a list")
    areas = tuple(_parse_area(raw, source) for raw in raw_areas)
    seen: set[str] = set()
    for area in areas:
        if area.area_id in seen:
            raise JobLoadError(f"{source}: duplicate area_id {area.area_id!r}")
        seen.add(area.area_id)

    raw_docs = payload.get("documentation") or []
    if not isinstance(raw_docs, list):
        raise JobLoadError(f"{source}: documentation must be a list")
    documents = tuple(_parse_document(raw, source, seen) for raw in raw_docs)

    raw_lines = payload.get("line_items") or []
    if not isinstance(raw_lines, list):
        raise JobLoadError(f"{source}: line_items must be a list")
    lines = tuple(_parse_line(raw, source, seen) for raw in raw_lines)
    line_ids: set[str] = set()
    for line in lines:
        if line.line_id in line_ids:
            raise JobLoadError(f"{source}: duplicate line_id {line.line_id!r}")
        line_ids.add(line.line_id)

    loss = payload.get("loss") or {}
    if not isinstance(loss, dict):
        raise JobLoadError(f"{source}: loss must be an object")

    return Job(
        job_id=job_id,
        loss_type=loss.get("type", "water"),
        water_category=loss.get("water_category"),
        drying_class=loss.get("drying_class"),
        planned_drying_days=int(_number(loss.get("planned_drying_days"), "loss.planned_drying_days", source)),
        includes_rebuild=bool(payload.get("includes_rebuild", False)),
        areas=areas,
        documents=documents,
        line_items=lines,
        description=payload.get("description", ""),
        source=source,
    )


def load_job(path: str | Path) -> Job:
    path = Path(path)
    if not path.exists():
        raise JobLoadError(f"job package not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise JobLoadError(f"{path} is not valid JSON: {exc}") from exc
    return parse_job(payload, source=str(path))


def bundled_jobs_dir() -> Path:
    return Path(__file__).parent / "data" / "jobs"


def load_bundled_jobs() -> list[Job]:
    paths = sorted(bundled_jobs_dir().glob("*.json"))
    return [load_job(path) for path in paths]
