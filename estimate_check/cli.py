"""Command line entry point.

    estimate-check demo              bundled synthetic jobs, offline, no API key
    estimate-check audit <job.json>  audit one job package
    estimate-check eval              precision and recall over the labelled seed set
    estimate-check rules             what the loaded rule pack actually contains
    estimate-check doctor            environment checks
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from estimate_check import __version__
from estimate_check.detectors import DETECTOR_SUMMARIES
from estimate_check.engine import audit
from estimate_check.loader import JobLoadError, bundled_jobs_dir, load_job
from estimate_check.model import SEVERITY_ORDER, AuditResult
from estimate_check.report import Painter, render, render_compact, use_color
from estimate_check.rulepack import RulePackError, load_rulepack

DEMO_JOBS = ("JOB-1001.json", "JOB-1004.json", "JOB-1007.json", "JOB-1013.json")


def _exit_code(result: AuditResult, fail_on: str) -> int:
    if fail_on == "none":
        return 0
    threshold = SEVERITY_ORDER[fail_on]
    worst = result.max_severity()
    if worst is None:
        return 0
    return 1 if SEVERITY_ORDER[worst] >= threshold else 0


def _load_pack(args):
    return load_rulepack(getattr(args, "rules", None))


def _maybe_judge(result: AuditResult, args) -> AuditResult:
    if not getattr(args, "with_judge", False):
        return result
    from estimate_check.judge import JudgeConfig, JudgeUnavailable
    from estimate_check.judge import run as run_judge

    config = JudgeConfig(model=args.judge_model)
    try:
        verdicts = run_judge(result, config)
    except JudgeUnavailable as exc:
        print(f"judge not run: {exc}", file=sys.stderr)
        return result
    return AuditResult(
        job=result.job,
        rulepack_id=result.rulepack_id,
        rulepack_version=result.rulepack_version,
        lines=result.lines,
        findings=result.findings,
        judge=verdicts,
    )


def cmd_audit(args) -> int:
    pack = _load_pack(args)
    job = load_job(args.job)
    result = _maybe_judge(audit(job, pack), args)

    if args.json:
        payload = json.dumps(result.to_dict(), indent=2, sort_keys=False)
        if args.out:
            Path(args.out).write_text(payload + "\n", encoding="utf-8")
            print(f"wrote {args.out}")
        else:
            print(payload)
    else:
        print(render(result, pack, explain=args.explain))
        if args.out:
            Path(args.out).write_text(
                json.dumps(result.to_dict(), indent=2, sort_keys=False) + "\n", encoding="utf-8"
            )
            print(f"\nJSON written to {args.out}")
    return _exit_code(result, args.fail_on)


def cmd_demo(args) -> int:
    pack = _load_pack(args)
    paint = Painter(use_color())
    jobs_dir = bundled_jobs_dir()
    paths = [jobs_dir / name for name in DEMO_JOBS]
    paths = [path for path in paths if path.exists()] or sorted(jobs_dir.glob("*.json"))[:3]

    print(
        paint(f"estimate-check {__version__} demo", "bold")
        + "   offline, no API key, bundled synthetic jobs"
    )
    print(
        paint(
            f"rule pack {pack.rulepack_id} {pack.version} is synthetic and illustrative. "
            "The jobs below are invented. See README.",
            "dim",
        )
    )
    print()
    results = []
    for path in paths:
        result = audit(load_job(path), pack)
        results.append(result)
        print(render_compact(result))
        print()

    findings = sum(len(result.findings) for result in results)
    lines = sum(len(result.lines) for result in results)
    print(paint("SIX DETECTORS", "bold"))
    for name, summary in DETECTOR_SUMMARIES.items():
        fired = sum(result.counts_by("detector").get(name, 0) for result in results)
        print(f"  {name:<20} {summary}{paint(f'   fired {fired}x', 'dim')}")
    print()
    print(f"{len(results)} jobs, {lines} line items, {findings} findings.")
    example = paths[0].relative_to(Path.cwd()) if paths[0].is_relative_to(Path.cwd()) else paths[0]
    print(
        "Every rule that was evaluated, including the ones that passed:\n"
        f"  estimate-check audit {example} --explain"
    )
    return 0


def cmd_eval(args) -> int:
    from estimate_check.evaluation import evaluate
    from estimate_check.evaluation import render as render_eval

    report = evaluate(labels_path=args.labels, pack=_load_pack(args))
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(render_eval(report))
    return 0


def cmd_rules(args) -> int:
    pack = _load_pack(args)
    print(f"{pack.rulepack_id} {pack.version}: {pack.title}")
    print()
    print(pack.provenance)
    print()
    print(f"{len(pack.codes)} line codes")
    for code, spec in sorted(pack.codes.items()):
        basis = spec.basis if spec.basis != "none" else "no quantity check"
        print(f"  {code:<22} {spec.unit:<7} {basis:<28} {spec.label}")
    print()
    rules = pack.all_rules()
    print(f"{len(rules)} rules")
    for rule in rules:
        print(f"  {rule['rule_id']:<9} {rule.get('severity', '-'):<7} {rule['title']}")
    print()
    print("Constants used by the quantity rules, all of them invented for this demo:")
    for name, value in sorted(pack.constants.items()):
        print(f"  {name:<26} {value:g}")
    return 0


def cmd_doctor(args) -> int:
    checks: list[tuple[str, bool, str]] = []

    version_ok = sys.version_info >= (3, 11)
    checks.append(
        ("python", version_ok, f"{sys.version.split()[0]} (3.11 or newer required)")
    )
    checks.append(("estimate-check", True, f"{__version__} importable, no runtime dependencies"))

    try:
        pack = load_rulepack(getattr(args, "rules", None))
        checks.append(
            (
                "rule pack",
                True,
                f"{pack.rulepack_id} {pack.version}, {len(pack.codes)} codes, {len(pack.all_rules())} rules (synthetic)",
            )
        )
    except RulePackError as exc:
        pack = None
        checks.append(("rule pack", False, str(exc)))

    jobs = sorted(bundled_jobs_dir().glob("*.json"))
    if not jobs:
        checks.append(("bundled jobs", False, f"no job packages found in {bundled_jobs_dir()}"))
    else:
        try:
            for path in jobs:
                load_job(path)
            checks.append(("bundled jobs", True, f"{len(jobs)} invented job packages load and validate"))
        except JobLoadError as exc:
            checks.append(("bundled jobs", False, str(exc)))

    try:
        from estimate_check.evaluation import load_labels

        labels = load_labels()
        checks.append(
            (
                "seed labels",
                True,
                f"{len(labels.get('labels', ()))} labelled findings in {labels.get('seed_set_id')}",
            )
        )
    except Exception as exc:  # noqa: BLE001 - doctor reports rather than raises
        checks.append(("seed labels", False, str(exc)))

    if pack is not None and jobs:
        try:
            result = audit(load_job(jobs[0]), pack)
            checks.append(
                ("audit path", True, f"{jobs[0].name} audited, {len(result.findings)} findings")
            )
        except Exception as exc:  # noqa: BLE001
            checks.append(("audit path", False, str(exc)))

    try:
        import anthropic  # noqa: F401

        judge_note = "anthropic installed"
    except ImportError:
        judge_note = "anthropic not installed (pip install 'estimate-check[judge]')"
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    judge_note += ", API key set" if has_key else ", no API key in the environment"
    checks.append(("judge (optional)", True, judge_note + ". Off by default and not required."))

    width = max(len(name) for name, _, _ in checks)
    failed = 0
    for name, ok, detail in checks:
        mark = "ok  " if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"{mark}  {name:<{width}}  {detail}")
    print()
    if failed:
        print(f"{failed} check(s) failed.")
    else:
        print("All required checks passed. The deterministic path uses no network.")
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="estimate-check",
        description=(
            "Audit proposed estimate line items against a job package. Deterministic, "
            "offline, with a synthetic rule pack."
        ),
    )
    parser.add_argument("--version", action="version", version=f"estimate-check {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_rules_flag(sub):
        sub.add_argument(
            "--rules",
            metavar="PATH",
            help="path to a rule pack JSON file (default: the bundled synthetic pack)",
        )

    demo = subparsers.add_parser("demo", help="audit the bundled synthetic jobs, offline")
    add_rules_flag(demo)
    demo.set_defaults(func=cmd_demo)

    audit_cmd = subparsers.add_parser("audit", help="audit one job package")
    audit_cmd.add_argument("job", help="path to a job package JSON file")
    add_rules_flag(audit_cmd)
    audit_cmd.add_argument("--json", action="store_true", help="print the structured JSON result")
    audit_cmd.add_argument("--out", metavar="PATH", help="also write the JSON result to a file")
    audit_cmd.add_argument(
        "--explain",
        action="store_true",
        help="show every rule that was evaluated, including the ones that passed",
    )
    audit_cmd.add_argument(
        "--fail-on",
        choices=("none", "low", "medium", "high"),
        default="none",
        help="exit 1 when a finding at this severity or above is present (default: none)",
    )
    audit_cmd.add_argument(
        "--with-judge",
        action="store_true",
        help="ask an LLM to review the ambiguous findings only. Off by default, needs an API key.",
    )
    audit_cmd.add_argument(
        "--judge-model",
        default="claude-opus-5",
        help="model id for the optional judge (default: claude-opus-5)",
    )
    audit_cmd.set_defaults(func=cmd_audit)

    eval_cmd = subparsers.add_parser("eval", help="precision and recall over the labelled seed set")
    add_rules_flag(eval_cmd)
    eval_cmd.add_argument("--labels", metavar="PATH", help="path to a labels file")
    eval_cmd.add_argument("--json", action="store_true", help="print the metrics as JSON")
    eval_cmd.set_defaults(func=cmd_eval)

    rules_cmd = subparsers.add_parser("rules", help="print the loaded rule pack")
    add_rules_flag(rules_cmd)
    rules_cmd.set_defaults(func=cmd_rules)

    doctor = subparsers.add_parser("doctor", help="environment checks")
    add_rules_flag(doctor)
    doctor.set_defaults(func=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (JobLoadError, RulePackError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
