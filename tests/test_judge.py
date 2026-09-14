"""The judge is optional and off by default. These tests cover the selection and
parsing logic with a stub client. Nothing here reaches the network.
"""

from __future__ import annotations

import json

import pytest
from conftest import make_doc, make_job, make_line

from estimate_check import judge
from estimate_check.engine import audit
from estimate_check.model import finding_id


class StubMessage:
    def __init__(self, text):
        self.content = [type("Block", (), {"type": "text", "text": text})()]


class StubClient:
    """Stands in for anthropic.Anthropic. Records the request it was given."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return StubMessage(self.reply)


def ambiguous_result(pack):
    job = make_job(
        includes_rebuild=True,
        documents=(make_doc("IMG-1", tags=("wall", "staining")),),
        lines=(make_line("L01", "RBD-PNT-FIN", quantity=432.0),),
    )
    result = audit(job, pack)
    assert any(f.ambiguous for f in result.findings)
    return result


def test_only_ambiguous_findings_are_sent_to_the_judge(pack):
    result = ambiguous_result(pack)
    selected = judge.select_for_review(result.findings, limit=10)
    assert selected
    assert all(finding.ambiguous for finding in selected)
    assert len(selected) < len(result.findings)


def test_the_judge_is_skipped_when_nothing_is_ambiguous(pack):
    from estimate_check.loader import bundled_jobs_dir, load_job

    result = audit(load_job(bundled_jobs_dir() / "JOB-1001.json"), pack)
    verdicts = judge.run(result, client=object())
    assert verdicts["status"] == "skipped"
    assert verdicts["reviews"] == []


def test_the_judge_never_changes_the_deterministic_findings(pack):
    result = ambiguous_result(pack)
    target = finding_id(judge.select_for_review(result.findings, 10)[0])
    client = StubClient(
        json.dumps(
            {
                "reviews": [
                    {
                        "finding_id": target,
                        "verdict": "dismiss",
                        "confidence": "high",
                        "rationale": "The wall is sound, a sealer is not needed.",
                    }
                ]
            }
        )
    )
    verdicts = judge.run(result, client=client)
    assert verdicts["status"] == "ran"
    assert verdicts["reviews"][0]["verdict"] == "dismiss"
    assert result.findings == audit(result.job, pack).findings


def test_the_request_asks_for_a_constrained_json_shape(pack):
    result = ambiguous_result(pack)
    client = StubClient(json.dumps({"reviews": []}))
    judge.run(result, client=client)
    request = client.calls[0]
    assert request["model"] == judge.DEFAULT_MODEL
    assert request["output_config"]["format"]["type"] == "json_schema"
    assert "ambiguous" in request["system"]


def test_reviews_for_findings_we_did_not_ask_about_are_dropped():
    reviews, problems = judge.parse_reviews(
        json.dumps({"reviews": [{"finding_id": "made-up", "verdict": "uphold", "confidence": "high", "rationale": ""}]}),
        {"real-one"},
    )
    assert reviews == []
    assert any("unknown finding id" in problem for problem in problems)
    assert any("no review for" in problem for problem in problems)


def test_a_duplicate_or_malformed_verdict_is_dropped():
    payload = json.dumps(
        {
            "reviews": [
                {"finding_id": "a", "verdict": "uphold", "confidence": "high", "rationale": "x"},
                {"finding_id": "a", "verdict": "dismiss", "confidence": "low", "rationale": "y"},
                {"finding_id": "b", "verdict": "maybe", "confidence": "low", "rationale": "z"},
            ]
        }
    )
    reviews, problems = judge.parse_reviews(payload, {"a", "b"})
    assert [review["finding_id"] for review in reviews] == ["a"]
    assert any("duplicate" in problem for problem in problems)
    assert any("unrecognised verdict" in problem for problem in problems)


def test_a_non_json_reply_is_an_error_not_a_silent_pass():
    with pytest.raises(judge.JudgeUnavailable):
        judge.parse_reviews("I think line 3 looks fine", {"a"})


def test_asking_for_the_judge_without_a_key_does_not_break_the_audit(monkeypatch, capsys, pack):
    from estimate_check.cli import main
    from estimate_check.loader import bundled_jobs_dir

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    code = main(["audit", str(bundled_jobs_dir() / "JOB-1003.json"), "--with-judge"])
    captured = capsys.readouterr()
    assert code == 0
    assert "LINE ITEMS" in captured.out
    assert "judge not run" in captured.err
