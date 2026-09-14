"""Small builders so each test can state exactly the job it is about."""

from __future__ import annotations

import pytest

from estimate_check.model import Area, Document, Job, LineItem
from estimate_check.rulepack import load_rulepack


@pytest.fixture(scope="session")
def pack():
    return load_rulepack()


def make_area(area_id="kitchen", **kwargs):
    defaults = dict(
        name=area_id.title(),
        floor_sf=180.0,
        ceiling_sf=180.0,
        perimeter_lf=54.0,
        height_ft=8.0,
        affected_floor_sf=180.0,
        affected_wall_sf=108.0,
        scope=("standing_water", "water_extraction", "dry_structure"),
    )
    defaults.update(kwargs)
    return Area(area_id=area_id, **defaults)


def make_doc(doc_id="IMG-1", kind="photo", area_ids=("kitchen",), tags=(), text=""):
    return Document(doc_id=doc_id, kind=kind, area_ids=tuple(area_ids), tags=tuple(tags), text=text)


def make_line(line_id, code, area_id="kitchen", quantity=180.0, unit="SF"):
    return LineItem(line_id=line_id, code=code, area_id=area_id, quantity=quantity, unit=unit)


def make_job(areas=None, documents=None, lines=None, **kwargs):
    defaults = dict(
        job_id="JOB-TEST",
        loss_type="water",
        water_category=1,
        drying_class=1,
        planned_drying_days=3,
        includes_rebuild=False,
    )
    defaults.update(kwargs)
    return Job(
        areas=tuple(areas if areas is not None else (make_area(),)),
        documents=tuple(documents if documents is not None else ()),
        line_items=tuple(lines if lines is not None else ()),
        **defaults,
    )
