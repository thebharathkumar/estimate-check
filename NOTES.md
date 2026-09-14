# Questions for day one

Fifteen questions I would ask a restoration contractor sitting in their office,
before writing another rule. Each one is a place where this repo currently
guesses. Most of them would change the data model, not just the numbers.

I built the verifier first so the questions would be specific. Every one below
points at a line of code or a fixture that is wrong until somebody who does this
work tells me otherwise.

---

**1. Walk me through the last supplement you got approved. Who asked, what did
you send, how many rounds, how long did it take?**
The tool treats an estimate as one artifact audited once. If the real shape is
initial estimate, then two supplements over three weeks, then a finding is not a
pass or fail, it is an item with a lifecycle: raised, submitted, approved,
denied, dropped. The JSON has no field for any of that yet.

**2. What gets rejected most often, and is it the line item itself or the
documentation behind it?**
Severities in `rulepack.synthetic.json` are mine. They should be ordered by what
actually gets kicked back. If the answer is "the line is fine, the photo is
missing", then `unsupported_line` deserves to be the loudest detector and the
other five are secondary.

**3. Looking back at closed jobs, what is the one line you most often find you
forgot to bill? What did it cost you?**
`missing_required` fires eleven rules at flat severities. A missed debris haul
and a missed cabinet detach and reset are not the same finding. If I can rank
the rules by dollars, the report becomes a list of money rather than a list of
errors, and that changes who is willing to read it.

**4. How does a photo actually get attached to a room? Does anyone tag on site,
or is it filename, timestamp, upload order, or someone sorting them afterwards?**
This is the biggest single assumption in the repo. `undocumented_area` and
`unsupported_line` only count documentation carrying an explicit `area_id`, and
that assumption produces four of the five false positives in the seed run.
JOB-1005 is built around it: two photos of a stairwell that arrived with no room
set. If room association is inferred rather than recorded, it arrives with a
confidence, and then every evidence rule has to reason about a probability
instead of a boolean.

**5. When the adjuster disagrees with a line, what do you do? Argue it, drop it,
or eat it? Who makes that call?**
Findings currently have no owner and no outcome. If outcomes were recorded, they
are the only honest training signal available for deciding which rules are worth
firing, and the seed set in this repo could be replaced with real labels.

**6. Is mitigation and rebuild one estimate or two? Who writes each, and does the
second person see the first one?**
A single `includes_rebuild` boolean gates four rules (REQ-007, REQ-008, REQ-010
and the rebuild sequence rules). If rebuild is a separate estimate written two
weeks later by a different person, then flagging "drywall came out and nothing
puts it back" on the mitigation estimate is noise every single time.

**7. What waste factor do you put on flooring and on paint, and does the carrier
pay it?**
The pack has no waste allowance, which is exactly why a flooring install billed
twelve percent over the room measurement shows up as a false positive in the
eval. The fix is a per code allowance band, probably asymmetric: over by ten
percent is normal, under by ten percent means somebody measured the wrong room.

**8. Which measurements are real and which are estimated? Does anyone put a tape
on the perimeter, or does it come off a sketch?**
`quantity_mismatch` treats `perimeter_lf` as exact and compares against it at a
ten percent tolerance. If perimeter comes from a sketch someone eyeballed, the
tolerance is not protecting anything and the whole detector needs a measurement
provenance field to be worth running.

**9. Who decides a 2 ft cut versus 4 ft versus full height, and is it decided on
site or after the readings come back?**
`DEMO-DRY-2FT` and `DEMO-DRY-4FT` sit in one exclusivity group, so billing both
in one room is a high severity duplicate. If one wall in a room routinely gets a
2 ft cut and another gets 4 ft, that rule is not just wrong, it is loudly wrong
on ordinary jobs.

**10. How do you size equipment, and what does the carrier accept as
justification for the unit count and the number of days?**
Air movers are affected floor area over sixty, dehumidifiers are affected volume
over twelve hundred, both multiplied by planned days. I made those constants up
and the rule pack says so. I would want to know whether equipment is checkable at
all without the drying log, and whether the argument is ever about the count
rather than the days.

**11. When does one physical space end up as two entries? Open plan, two techs
sketching, a remeasure?**
`duplicate_scope` keys on `area_id`, so one room recorded twice under two names
is completely invisible to it. JOB-1008 is that case and it is one of three
labelled false negatives. Catching it needs geometry or a merge step, not a rule.

**12. Who would actually use this, and when in their day? The estimator before
submission, a reviewer after, or the owner on a Friday afternoon?**
The report currently prints every line with every check. If the reader is an
estimator at six in the evening with four jobs to submit, the correct output is
three lines and a number, and `--explain` is the exception rather than the
foundation.

**13. How many wrong flags before you stop reading them? Two a job? One in ten?**
The tool marks borderline findings ambiguous and still shows them. Where that
threshold sits is a decision for the person who has to read them, and it is
currently a constant in `quantity_mismatch.severity_for`.

**14. What happens to the estimate after it leaves you? Desk review, a third
party audit, a reinspection? Does the same rule set apply at each stage?**
One rule pack, one pass, one audience. If three parties review with three
different rule sets, then a finding needs to say which audience it is for, and
the tool needs to load more than one pack at a time.

**15. Contents, cabinets, detach and reset: how does that get scoped, and who
misses it?**
The pack has no cabinet or contents code at all. JOB-1011 has notes describing
three cabinets and a countertop that have to come out to dry the wall behind
them, nothing billed for it, and no rule in the tool that can see it. It is the
third labelled false negative and it is the kind of miss that is worth real money.

---

Every rule in `rulepack.synthetic.json` is a placeholder for one of these
answers. The architecture (deterministic detectors, explicit evidence, a labelled
set to score against, a judge confined to the ambiguous cases) is the part I can
build without a contractor in the room. The rules are not.
