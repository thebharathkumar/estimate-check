"""One test per detector for the case it is supposed to catch, plus the case it
is supposed to leave alone. The negative half matters more than the positive
half: a verifier that flags everything is useless on a real estimate.
"""

from __future__ import annotations

from conftest import make_area, make_doc, make_job, make_line

from estimate_check.detectors import (
    duplicate_scope,
    missing_required,
    quantity_mismatch,
    sequence_violation,
    undocumented_area,
    unsupported_line,
)
from estimate_check.engine import audit


def rules_fired(result, detector=None):
    return sorted(
        f.rule_id for f in result.findings if detector is None or f.detector == detector
    )


# ------------------------------------------------------------ unsupported_line


def test_unsupported_line_fires_when_the_area_has_no_documentation(pack):
    job = make_job(documents=(), lines=(make_line("L01", "MIT-EXT-STD"),))
    result = unsupported_line.run(job, pack)
    assert [f.rule_id for f in result.findings] == ["EVID-001"]
    assert result.findings[0].severity == "high"
    assert result.findings[0].evidence[0].kind == "absence"


def test_unsupported_line_fires_softly_when_the_area_is_documented_but_not_for_this_code(pack):
    job = make_job(
        documents=(make_doc("IMG-1", tags=("wet_floor",)),),
        lines=(make_line("L01", "DEMO-INSUL", quantity=108.0),),
    )
    result = unsupported_line.run(job, pack)
    finding = result.findings[0]
    assert finding.rule_id == "EVID-002"
    assert finding.severity == "medium"
    assert finding.ambiguous is True


def test_unsupported_line_passes_and_names_the_document_it_relied_on(pack):
    job = make_job(
        documents=(make_doc("IMG-1", tags=("standing_water",)),),
        lines=(make_line("L01", "MIT-EXT-STD"),),
    )
    result = unsupported_line.run(job, pack)
    assert result.findings == ()
    check = result.checks[0][1]
    assert check.status == "pass"
    assert check.evidence[0].ref == "IMG-1"


def test_a_job_wide_line_may_lean_on_documentation_from_any_area(pack):
    job = make_job(
        documents=(make_doc("IMG-1", tags=("equipment",)),),
        lines=(make_line("L01", "MIT-AIRMOVER-DAY", area_id=None, quantity=9.0, unit="EA-DAY"),),
    )
    assert unsupported_line.run(job, pack).findings == ()


# ------------------------------------------------------------ missing_required


def test_missing_required_fires_for_a_category_two_loss_with_no_antimicrobial(pack):
    job = make_job(
        water_category=2,
        documents=(make_doc("IMG-1", tags=("wet_drywall",)),),
        lines=(make_line("L01", "DEMO-DRY-2FT", quantity=108.0),),
    )
    result = missing_required.run(job, pack)
    assert "REQ-002" in [f.rule_id for f in result.findings]
    finding = next(f for f in result.findings if f.rule_id == "REQ-002")
    assert finding.subject.type == "expected_line"
    assert finding.subject.code == "TRT-ANTIMICRO"
    assert finding.subject.line_id is None


def test_missing_required_stays_quiet_once_the_expected_line_is_present(pack):
    job = make_job(
        water_category=2,
        lines=(
            make_line("L01", "DEMO-DRY-2FT", quantity=108.0),
            make_line("L02", "TRT-ANTIMICRO", quantity=288.0),
        ),
    )
    assert "REQ-002" not in [f.rule_id for f in missing_required.run(job, pack).findings]


def test_rebuild_rules_do_not_fire_on_a_mitigation_only_job(pack):
    lines = (make_line("L01", "DEMO-DRY-2FT", quantity=108.0),)
    mitigation = make_job(includes_rebuild=False, lines=lines)
    rebuild = make_job(includes_rebuild=True, lines=lines)
    assert "REQ-007" not in [f.rule_id for f in missing_required.run(mitigation, pack).findings]
    assert "REQ-007" in [f.rule_id for f in missing_required.run(rebuild, pack).findings]


def test_an_unknown_condition_key_makes_a_rule_silent_not_universal(pack):
    from estimate_check.detectors.base import condition_holds

    job = make_job()
    holds, _ = condition_holds({"there_is_no_such_key": True}, job, job.areas[0])
    assert holds is False


# ------------------------------------------------------------ quantity_mismatch


def test_quantity_mismatch_fires_on_a_two_foot_cut_billed_at_four_foot_quantity(pack):
    job = make_job(
        documents=(make_doc("IMG-1", tags=("flood_cut",)),),
        lines=(make_line("L01", "DEMO-DRY-2FT", quantity=216.0),),
    )
    findings = quantity_mismatch.run(job, pack).findings
    assert [f.rule_id for f in findings] == ["QTY-001"]
    assert findings[0].severity == "high"
    assert "flood_cut_2ft_sf" in findings[0].reason


def test_quantity_mismatch_passes_inside_the_tolerance_band(pack):
    job = make_job(lines=(make_line("L01", "DEMO-DRY-2FT", quantity=113.0),))
    assert quantity_mismatch.run(job, pack).findings == ()


def test_a_small_overage_is_flagged_low_and_ambiguous(pack):
    job = make_job(
        includes_rebuild=True,
        lines=(make_line("L01", "RBD-FLR-LAM", quantity=180.0 * 1.12),),
    )
    finding = quantity_mismatch.run(job, pack).findings[0]
    assert finding.severity == "low"
    assert finding.ambiguous is True


def test_the_wrong_unit_is_its_own_finding_and_stops_the_number_comparison(pack):
    job = make_job(lines=(make_line("L01", "MIT-EXT-STD", unit="LF"),))
    result = quantity_mismatch.run(job, pack)
    assert [f.rule_id for f in result.findings] == ["QTY-002"]
    statuses = {check.rule_id: check.status for _, check in result.checks}
    assert statuses["QTY-001"] == "skipped"


def test_a_code_with_no_basis_is_skipped_and_says_so(pack):
    job = make_job(lines=(make_line("L01", "GEN-CONTAIN-BARRIER", quantity=9999.0),))
    result = quantity_mismatch.run(job, pack)
    assert result.findings == ()
    check = next(check for _, check in result.checks if check.rule_id == "QTY-001")
    assert check.status == "skipped"
    assert "no quantity basis" in check.reason


def test_equipment_quantities_come_from_measurements_and_planned_days(pack):
    # 180 affected SF over a 60 SF per unit constant is 3 units, over 3 days is 9 unit days.
    job = make_job(lines=(make_line("L01", "MIT-AIRMOVER-DAY", area_id=None, quantity=9.0, unit="EA-DAY"),))
    assert quantity_mismatch.run(job, pack).findings == ()
    job = make_job(lines=(make_line("L01", "MIT-AIRMOVER-DAY", area_id=None, quantity=30.0, unit="EA-DAY"),))
    assert [f.rule_id for f in quantity_mismatch.run(job, pack).findings] == ["QTY-001"]


def test_billing_against_a_zero_measurement_is_high_severity(pack):
    area = make_area(affected_wall_sf=0.0)
    job = make_job(areas=(area,), lines=(make_line("L01", "DEMO-DRY-FULL", quantity=64.0),))
    finding = quantity_mismatch.run(job, pack).findings[0]
    assert finding.severity == "high"
    assert "zero" in finding.reason


# ------------------------------------------------------------ duplicate_scope


def test_duplicate_scope_catches_the_same_code_twice_in_one_area(pack):
    job = make_job(
        lines=(make_line("L01", "DEMO-FLR-CPT"), make_line("L02", "DEMO-FLR-CPT")),
    )
    findings = duplicate_scope.run(job, pack).findings
    assert [f.rule_id for f in findings] == ["DUP-001"]
    assert findings[0].subject.line_id == "L02"
    assert findings[0].evidence[0].ref == "L01"


def test_duplicate_scope_catches_two_codes_from_one_exclusive_group(pack):
    job = make_job(
        lines=(
            make_line("L01", "DEMO-DRY-2FT", quantity=108.0),
            make_line("L02", "DEMO-DRY-4FT", quantity=216.0),
        )
    )
    findings = duplicate_scope.run(job, pack).findings
    assert [f.rule_id for f in findings] == ["DUP-002"]
    assert findings[0].subject.line_id == "L02"


def test_the_same_code_in_two_different_areas_is_not_a_duplicate(pack):
    job = make_job(
        areas=(make_area("kitchen"), make_area("hall")),
        lines=(make_line("L01", "DEMO-FLR-CPT"), make_line("L02", "DEMO-FLR-CPT", area_id="hall")),
    )
    assert duplicate_scope.run(job, pack).findings == ()


def test_carpet_and_its_pad_are_not_a_duplicate(pack):
    job = make_job(
        lines=(make_line("L01", "DEMO-FLR-CPT"), make_line("L02", "DEMO-FLR-PAD")),
    )
    assert duplicate_scope.run(job, pack).findings == ()


# ------------------------------------------------------------ sequence_violation


def test_sequence_violation_catches_drywall_replacement_with_no_demolition(pack):
    job = make_job(includes_rebuild=True, lines=(make_line("L01", "RBD-DRY-HANG", quantity=108.0),))
    findings = sequence_violation.run(job, pack).findings
    assert [f.rule_id for f in findings] == ["SEQ-001"]
    assert findings[0].severity == "high"


def test_sequence_violation_catches_paint_over_new_board_with_no_primer(pack):
    job = make_job(
        includes_rebuild=True,
        lines=(
            make_line("L01", "DEMO-DRY-2FT", quantity=108.0),
            make_line("L02", "RBD-DRY-HANG", quantity=108.0),
            make_line("L03", "RBD-PNT-FIN", quantity=432.0),
        ),
    )
    findings = sequence_violation.run(job, pack).findings
    assert [f.rule_id for f in findings] == ["SEQ-002"]
    assert findings[0].ambiguous is False


def test_paint_with_no_primer_on_an_existing_wall_is_the_softer_rule(pack):
    job = make_job(includes_rebuild=True, lines=(make_line("L01", "RBD-PNT-FIN", quantity=432.0),))
    findings = sequence_violation.run(job, pack).findings
    assert [f.rule_id for f in findings] == ["SEQ-003"]
    assert findings[0].severity == "low"
    assert findings[0].ambiguous is True


def test_sequence_rules_are_scoped_to_the_area(pack):
    job = make_job(
        areas=(make_area("kitchen"), make_area("hall")),
        includes_rebuild=True,
        lines=(
            make_line("L01", "DEMO-DRY-2FT", quantity=108.0),
            make_line("L02", "RBD-DRY-HANG", area_id="hall", quantity=108.0),
        ),
    )
    findings = sequence_violation.run(job, pack).findings
    assert [f.subject.line_id for f in findings if f.rule_id == "SEQ-001"] == ["L02"]


# ------------------------------------------------------------ undocumented_area


def test_undocumented_area_fires_on_an_area_in_scope_with_nothing_attached(pack):
    job = make_job(documents=(), lines=(make_line("L01", "MIT-EXT-STD"),))
    findings = undocumented_area.run(job, pack).findings
    assert [f.rule_id for f in findings] == ["DOC-001"]
    assert findings[0].subject.type == "area"


def test_undocumented_area_counts_a_scan_that_covers_several_rooms(pack):
    job = make_job(
        areas=(make_area("kitchen"), make_area("hall")),
        documents=(make_doc("SCAN-1", kind="scan", area_ids=("kitchen", "hall")),),
    )
    assert undocumented_area.run(job, pack).findings == ()


def test_undocumented_area_ignores_an_area_that_carries_no_scope_at_all(pack):
    quiet = make_area("garage", scope=(), affected_floor_sf=0.0, affected_wall_sf=0.0)
    job = make_job(areas=(quiet,), documents=())
    assert undocumented_area.run(job, pack).findings == ()


def test_a_photo_with_no_area_assigned_is_reported_as_not_counted(pack):
    job = make_job(documents=(make_doc("IMG-9", area_ids=()),), lines=(make_line("L01", "MIT-EXT-STD"),))
    finding = undocumented_area.run(job, pack).findings[0]
    detail = " ".join(item.detail for item in finding.evidence)
    assert "no area assignment" in detail


# ------------------------------------------------------------ the whole audit


def test_a_correct_estimate_produces_no_findings(pack):
    from estimate_check.loader import load_job, bundled_jobs_dir

    result = audit(load_job(bundled_jobs_dir() / "JOB-1001.json"), pack)
    assert result.findings == ()
    assert all(item.verdict == "pass" for item in result.lines)


def test_a_line_with_a_code_the_pack_does_not_define_is_never_reported_as_passing(pack):
    job = make_job(
        documents=(make_doc("IMG-1", tags=("wet_floor",)),),
        lines=(make_line("L01", "NOT-A-REAL-CODE"),),
    )
    result = audit(job, pack)
    assert result.lines[0].verdict == "not_checked"
    assert {check.status for check in result.lines[0].checks} <= {"skipped", "pass"}


def test_every_finding_carries_a_rule_id_a_reason_and_evidence(pack):
    from estimate_check.loader import load_bundled_jobs

    for job in load_bundled_jobs():
        for finding in audit(job, pack).findings:
            assert finding.rule_id
            assert finding.reason.strip()
            assert finding.evidence, f"{job.job_id} {finding.rule_id} has no evidence"
            assert finding.severity in ("high", "medium", "low")
