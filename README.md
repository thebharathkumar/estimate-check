# estimate-check

[![ci](https://github.com/thebharathkumar/estimate-check/actions/workflows/ci.yml/badge.svg)](https://github.com/thebharathkumar/estimate-check/actions/workflows/ci.yml)

A verifier for restoration estimate line items. Give it a job package (scope of
damage, room measurements, a photo and note manifest) and a proposed set of line
items, and it returns a verdict per line with the rule that fired and the
evidence the rule relied on.

It is deterministic, offline, and has no runtime dependencies. An operator sees
why a line passed or failed, not a score.

## Ten second demo

```bash
git clone https://github.com/thebharathkumar/estimate-check
cd estimate-check
python3 -m estimate_check demo
```

No install, no API key, no network. It runs in well under a second against
bundled synthetic jobs.

```
JOB-1004  Roof leak into two bedrooms, rebuild included, duplicated and out of order lines
  21 lines, 17 pass, 4 fail   findings: 6 (high 5, medium 1, low 0)
    [high]  duplicate_scope    DUP-002  L05  L05 bills DEMO-DRY-4FT in bed1 where L04 already
                                             bills DEMO-DRY-2FT. Both codes are in the
                                             drywall_removal group, which bills one piece of
                                             work once.
    [high]  sequence_violation SEQ-001  L12  New drywall is billed in this area but no drywall
                                             removal is billed for it.
```

To see every rule that was evaluated, including the ones that passed:

```bash
python3 -m estimate_check audit estimate_check/data/jobs/JOB-1001.json --explain
```

Install it properly if you want the `estimate-check` command and the tests:

```bash
pip install -e ".[dev]" && pytest
```

## The six detectors

| detector | what it catches |
| --- | --- |
| `unsupported_line` | a billed line with no documentation behind it |
| `missing_required` | the scope implies a line item that the estimate does not have |
| `quantity_mismatch` | a quantity that contradicts the room measurements |
| `duplicate_scope` | two line items billing the same work |
| `sequence_violation` | a line that depends on work nobody billed |
| `undocumented_area` | an area in scope with no photo, note or scan coverage |

Every finding carries the detector, a severity, the line item (or the line item
that should exist), the rule id, a readable reason, and pointers to the evidence.
An absence is evidence too and is reported as one.

## Commands

```
estimate-check demo                    bundled synthetic jobs, offline
estimate-check audit <job.json>        audit one job package
  --explain                            show the checks that passed as well
  --json --out result.json             structured output
  --fail-on high|medium|low            exit 1 when something at that severity fired
  --with-judge                         optional LLM review, off by default
estimate-check eval                    precision and recall over the labelled seed set
estimate-check rules                   what the loaded rule pack actually contains
estimate-check doctor                  environment checks
```

The JSON output carries no timestamps, so the same job package produces the same
bytes on every run and two audits can be diffed.

## What I do not know

I have never worked in restoration. I do not have Xactimate's line codes or any
carrier's rule set, and nothing here is derived from either.

- **The rule pack is synthetic.** `estimate_check/data/rulepack.synthetic.json`
  uses invented generic codes (`DEMO-DRY-2FT`, `MIT-EXT-STD`) and rules modelled
  loosely on publicly documented water damage remediation practice: extract,
  remove wet material, treat, dry, monitor, rebuild. The numeric constants
  (60 SF per air mover, 1200 cubic feet per dehumidifier) were chosen to make the
  demonstration legible. Real rule packs are carrier specific, negotiated and
  proprietary. Run `estimate-check rules` to see the whole thing, including which
  codes carry no quantity check at all.
- **The fixtures are invented.** All 13 jobs in `estimate_check/data/jobs` were
  written by me. No real loss, address, photo or estimate appears anywhere.
- **There is no Xactimate integration.** No import, no export, no ESX, no code
  mapping. The job package format is my own.
- **The seed set is too small to estimate accuracy.** See below.
- **The point of the repo is the verification architecture**, not the rules. The
  rules come from the field. `NOTES.md` is the list of questions I would ask on
  day one to replace them.

## Metrics

`estimate-check eval` scores the detectors against a hand labelled seed set. The
labels live in `estimate_check/data/seed/labels.json` and were written by reading
each job against the rule pack, including cases the detectors cannot catch. A
label whose `rule_id` is `none` describes a finding no rule in the pack can
produce; those are counted as false negatives rather than quietly dropped.

Seed set: 13 invented jobs, 148 line items, 29 labelled findings. Output of the
command, not rounded up:

```
detector              TP  FP  FN  precision  recall
unsupported_line       3   3   0       0.50    1.00
missing_required      12   0   1       1.00    0.92
quantity_mismatch      3   1   1       0.75    0.75
duplicate_scope        2   0   1       1.00    0.66
sequence_violation     5   0   0       1.00    1.00
undocumented_area      1   1   0       0.50    1.00
all detectors         26   5   3       0.83    0.89
```

**These numbers do not support an accuracy claim.** Two reasons, and both matter
more than the ratios:

1. Twenty nine labelled findings over thirteen jobs is far too small. Several
   detectors are scored on two or three examples. A single fixture changes a
   figure by a quarter. Read the counts, not the ratios.
2. I wrote the detectors and I wrote the labels. Where a rule and a label agree,
   that agreement is partly an artefact of one person doing both, which is most
   of why `missing_required` and `sequence_violation` look as good as they do.

What the numbers are useful for is showing where the design is weak, which is why
the command prints every disagreement:

- `unsupported_line` and `undocumented_area` lose precision on the same fixture.
  JOB-1005 has two photos of a stairwell that arrived with no room assigned,
  which is normal in the field. A reviewer counts them. This tool only counts
  documentation that is attached to an area, so it raises four findings that a
  human would not. Fixing that properly needs to know how photos actually get
  associated with rooms, which is question 4 in `NOTES.md`.
- `quantity_mismatch` loses precision on a flooring install billed twelve percent
  over the room measurement. That is as likely to be a waste factor as an error.
  The pack carries no waste allowance because I do not know what the convention
  is, so the detector flags it as low severity and ambiguous.
- The three false negatives are all things no rule in the pack can see: one open
  room measured twice under two names, a containment barrier quantity on a code
  with no basis, and cabinet work the pack has no code for at all.

## The optional judge

`--with-judge` is off by default and the repo publishes no numbers about it,
because I have not run it. The code path exists, it is unit tested against a stub
client, and it has never been executed against the live API.

If it were enabled, this is what it does:

- It only ever sees findings the deterministic layer marked **ambiguous**: a
  quantity just outside tolerance, a repaint with no primer on a wall that may
  well be sound, a line whose area is documented but not with the specific thing
  the rule pack asked for. That is a handful of findings per job, not all of them.
- It never creates, edits or removes a deterministic finding. It attaches an
  advisory opinion (`uphold`, `dismiss`, `unsure`) with a rationale, in a separate
  `judge` block of the JSON, so a downstream consumer can ignore it entirely.
- It is asked for a constrained JSON shape, and any review naming a finding it
  was not asked about is dropped and reported.

```bash
pip install -r requirements-judge.txt
export ANTHROPIC_API_KEY=...
estimate-check audit job.json --with-judge
```

The deterministic detectors are the product. The judge is for the part of the
problem where a rule pack is honestly the wrong tool.

## Layout

```
estimate_check/
  detectors/          one module per detector, each a pure function
  data/
    rulepack.synthetic.json   the invented rules, with their provenance in the file
    jobs/                     13 invented job packages
    seed/labels.json          ground truth for eval, with the protocol in the file
  engine.py           runs the detectors, assembles verdicts
  judge.py            optional, off by default, never run
  evaluation.py       precision and recall, truncated not rounded
tests/                pytest, CI on 3.11 and 3.12
NOTES.md              the questions that would change this design
```

MIT licensed.
