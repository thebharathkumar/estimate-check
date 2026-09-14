import json

import pytest

from estimate_check.detectors import DETECTOR_NAMES
from estimate_check.evaluation import (
    DetectorMetrics,
    evaluate,
    load_labels,
    truncate2,
)


def test_ratios_are_truncated_never_rounded_up():
    assert truncate2(0.666666) == 0.66
    assert truncate2(0.999) == 0.99
    assert truncate2(1.0) == 1.0
    assert truncate2(0.0) == 0.0


def test_precision_and_recall_are_undefined_rather_than_zero_when_nothing_happened():
    empty = DetectorMetrics("x", 0, 0, 0)
    assert empty.precision is None
    assert empty.recall is None
    scored = DetectorMetrics("x", 3, 1, 1)
    assert scored.precision == 0.75
    assert scored.recall == 0.75


def test_the_seed_set_is_labelled_against_known_detectors():
    payload = load_labels()
    assert payload["labels"]
    for label in payload["labels"]:
        assert label["detector"] in DETECTOR_NAMES
        assert label["job_id"]
        assert label.get("note") is not None


def test_evaluation_reports_counts_alongside_ratios():
    report = evaluate()
    assert report.job_count >= 10
    assert report.label_count == len(load_labels()["labels"])
    assert {metric.detector for metric in report.metrics} == set(DETECTOR_NAMES)
    totals = report.totals
    assert totals.true_positives + totals.false_negatives == report.label_count


def test_labels_no_rule_can_produce_are_counted_as_misses():
    report = evaluate()
    assert report.unreachable_labels > 0
    unreachable = [item for item in report.false_negatives if item["rule_id"] == "none"]
    assert len(unreachable) == report.unreachable_labels


def test_known_weaknesses_are_visible_in_the_run_not_hidden():
    report = evaluate()
    # The photos with no room assignment in JOB-1005 are documentation a reviewer
    # would count and this tool cannot. They must show up as false positives.
    jobs_with_false_positives = {item["job_id"] for item in report.false_positives}
    assert "JOB-1005" in jobs_with_false_positives
    by_detector = {metric.detector: metric for metric in report.metrics}
    assert by_detector["unsupported_line"].false_positives >= 3
    assert by_detector["undocumented_area"].false_positives >= 1


def test_a_label_that_matches_nothing_is_a_false_negative(tmp_path):
    payload = load_labels()
    payload["labels"] = [
        {
            "job_id": "JOB-1001",
            "detector": "duplicate_scope",
            "area_id": "kitchen",
            "rule_id": "DUP-001",
            "target": "L99",
            "note": "invented for this test",
        }
    ]
    path = tmp_path / "labels.json"
    path.write_text(json.dumps(payload))
    report = evaluate(labels_path=path)
    by_detector = {metric.detector: metric for metric in report.metrics}
    assert by_detector["duplicate_scope"].false_negatives == 1
    assert by_detector["duplicate_scope"].true_positives == 0


def test_an_unknown_detector_in_a_labels_file_is_rejected(tmp_path):
    path = tmp_path / "labels.json"
    path.write_text(json.dumps({"labels": [{"job_id": "JOB-1001", "detector": "vibes"}]}))
    with pytest.raises(ValueError, match="unknown detector"):
        load_labels(path)
