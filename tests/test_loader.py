import json

import pytest

from estimate_check.loader import JobLoadError, bundled_jobs_dir, load_bundled_jobs, load_job, parse_job

GOOD = {
    "job_id": "JOB-X",
    "loss": {"type": "water", "water_category": 2, "drying_class": 2, "planned_drying_days": 3},
    "areas": [
        {
            "area_id": "kitchen",
            "name": "Kitchen",
            "floor_sf": 180,
            "perimeter_lf": 54,
            "height_ft": 8,
            "affected": {"floor_sf": 180, "wall_sf": 108},
            "scope": ["water_extraction"],
        }
    ],
    "documentation": [{"doc_id": "IMG-1", "kind": "photo", "area_ids": ["kitchen"], "tags": ["wet_floor"]}],
    "line_items": [
        {"line_id": "L01", "code": "MIT-EXT-STD", "area_id": "kitchen", "quantity": 180, "unit": "SF"}
    ],
}


def test_parses_a_well_formed_package():
    job = parse_job(GOOD)
    assert job.job_id == "JOB-X"
    assert job.areas[0].wall_sf == 54 * 8
    assert job.line_items[0].extended_price is None
    assert job.documents_for_area("kitchen")[0].doc_id == "IMG-1"


def test_area_id_is_required():
    payload = json.loads(json.dumps(GOOD))
    del payload["areas"][0]["area_id"]
    with pytest.raises(JobLoadError, match="area_id"):
        parse_job(payload)


def test_line_pointing_at_an_unknown_area_is_rejected():
    payload = json.loads(json.dumps(GOOD))
    payload["line_items"][0]["area_id"] = "attic"
    with pytest.raises(JobLoadError, match="unknown area"):
        parse_job(payload)


def test_document_kind_must_be_known():
    payload = json.loads(json.dumps(GOOD))
    payload["documentation"][0]["kind"] = "hologram"
    with pytest.raises(JobLoadError, match="hologram"):
        parse_job(payload)


def test_duplicate_line_ids_are_rejected():
    payload = json.loads(json.dumps(GOOD))
    payload["line_items"].append(dict(payload["line_items"][0]))
    with pytest.raises(JobLoadError, match="duplicate line_id"):
        parse_job(payload)


def test_quantity_must_be_a_number():
    payload = json.loads(json.dumps(GOOD))
    payload["line_items"][0]["quantity"] = "lots"
    with pytest.raises(JobLoadError, match="must be a number"):
        parse_job(payload)


def test_a_document_may_carry_no_area_which_is_normal_in_the_field():
    payload = json.loads(json.dumps(GOOD))
    payload["documentation"].append({"doc_id": "IMG-2", "kind": "photo", "tags": ["floor"]})
    job = parse_job(payload)
    assert job.documents[1].area_ids == ()


def test_every_bundled_job_loads():
    jobs = load_bundled_jobs()
    assert len(jobs) >= 10
    assert len({job.job_id for job in jobs}) == len(jobs)


def test_missing_file_is_a_clear_error():
    with pytest.raises(JobLoadError, match="not found"):
        load_job(bundled_jobs_dir() / "nope.json")
