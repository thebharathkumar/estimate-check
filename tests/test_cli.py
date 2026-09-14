import json

from estimate_check.cli import main
from estimate_check.engine import audit
from estimate_check.loader import bundled_jobs_dir, load_job

JOB = str(bundled_jobs_dir() / "JOB-1004.json")


def test_demo_runs_offline_and_exits_zero(capsys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert main(["demo"]) == 0
    out = capsys.readouterr().out
    assert "SIX DETECTORS" in out
    assert "synthetic" in out


def test_doctor_reports_every_check(capsys):
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    for name in ("python", "rule pack", "bundled jobs", "seed labels", "audit path", "judge"):
        assert name in out
    assert "FAIL" not in out


def test_audit_prints_a_report(capsys):
    assert main(["audit", JOB]) == 0
    out = capsys.readouterr().out
    assert "LINE ITEMS" in out
    assert "DUP-002" in out


def test_audit_json_is_valid_and_carries_the_evidence(capsys):
    assert main(["audit", JOB, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "1.0"
    assert payload["rulepack"]["id"] == "synthetic-water-v0"
    assert payload["summary"]["findings"] == len(payload["findings"])
    finding = payload["findings"][0]
    assert finding["rule_id"] and finding["reason"] and finding["evidence"]
    assert payload["lines"][0]["checks"]


def test_explain_shows_the_checks_that_passed(capsys):
    main(["audit", str(bundled_jobs_dir() / "JOB-1001.json"), "--explain"])
    out = capsys.readouterr().out
    assert "pass" in out
    assert "EVID-001" in out
    assert "QTY-001" in out


def test_fail_on_controls_the_exit_code():
    assert main(["audit", JOB]) == 0
    assert main(["audit", JOB, "--fail-on", "high"]) == 1
    assert main(["audit", str(bundled_jobs_dir() / "JOB-1001.json"), "--fail-on", "low"]) == 0


def test_out_writes_the_json_to_a_file(tmp_path, capsys):
    target = tmp_path / "result.json"
    main(["audit", JOB, "--json", "--out", str(target)])
    payload = json.loads(target.read_text())
    assert payload["job"]["job_id"] == "JOB-1004"


def test_a_bad_path_is_a_clean_error_not_a_traceback(capsys):
    assert main(["audit", "no/such/job.json"]) == 2
    assert "error:" in capsys.readouterr().err


def test_rules_prints_the_pack_and_says_it_is_invented(capsys):
    assert main(["rules"]) == 0
    out = capsys.readouterr().out
    assert "invented" in out.lower()
    assert "MIT-EXT-STD" in out
    assert "sf_per_airmover" in out


def test_eval_prints_counts_alongside_the_ratios(capsys):
    assert main(["eval"]) == 0
    out = capsys.readouterr().out
    assert "precision" in out and "recall" in out
    assert "TP" in out and "FP" in out and "FN" in out


def test_the_audit_is_byte_for_byte_reproducible():
    job = load_job(JOB)
    first = json.dumps(audit(job).to_dict(), indent=2)
    second = json.dumps(audit(load_job(JOB)).to_dict(), indent=2)
    assert first == second
    assert "generated_at" not in first


def test_with_judge_is_off_by_default():
    job = load_job(JOB)
    assert audit(job).judge is None
