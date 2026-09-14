"""Loading and querying the rule pack.

The bundled pack is synthetic. It is modelled loosely on publicly documented
water damage remediation practice and it is not any carrier's rule set, nor
does it use Xactimate line codes. See README.md for what that means for the
results.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_RULEPACK = Path(__file__).parent / "data" / "rulepack.synthetic.json"


class RulePackError(ValueError):
    """Raised when a rule pack is missing required structure."""


@dataclass(frozen=True)
class CodeSpec:
    code: str
    label: str
    phase: str
    unit: str
    basis: str
    tolerance: float
    duplicate_group: str | None
    evidence_any_of: tuple[dict[str, Any], ...]
    note: str = ""


@dataclass(frozen=True)
class RulePack:
    rulepack_id: str
    version: str
    title: str
    provenance: str
    constants: dict[str, float]
    codes: dict[str, CodeSpec]
    required_rules: tuple[dict[str, Any], ...]
    quantity_rules: tuple[dict[str, Any], ...]
    sequence_rules: tuple[dict[str, Any], ...]
    duplicate_rules: tuple[dict[str, Any], ...]
    documentation_rules: tuple[dict[str, Any], ...]
    evidence_rules: tuple[dict[str, Any], ...]
    source: str = ""

    def spec(self, code: str) -> CodeSpec | None:
        return self.codes.get(code)

    def constant(self, name: str) -> float:
        if name not in self.constants:
            raise RulePackError(f"rule pack {self.rulepack_id} has no constant {name!r}")
        return self.constants[name]

    def codes_in_group(self, group: str) -> tuple[str, ...]:
        return tuple(
            sorted(c.code for c in self.codes.values() if c.duplicate_group == group)
        )

    def rule(self, rule_id: str) -> dict[str, Any] | None:
        for bucket in (
            self.required_rules,
            self.quantity_rules,
            self.sequence_rules,
            self.duplicate_rules,
            self.documentation_rules,
            self.evidence_rules,
        ):
            for rule in bucket:
                if rule.get("rule_id") == rule_id:
                    return rule
        return None

    def all_rules(self) -> tuple[dict[str, Any], ...]:
        return (
            self.evidence_rules
            + self.quantity_rules
            + self.required_rules
            + self.duplicate_rules
            + self.sequence_rules
            + self.documentation_rules
        )


def _require(payload: dict[str, Any], key: str, source: str) -> Any:
    if key not in payload:
        raise RulePackError(f"rule pack {source} is missing required key {key!r}")
    return payload[key]


def load_rulepack(path: str | Path | None = None) -> RulePack:
    path = Path(path) if path is not None else DEFAULT_RULEPACK
    if not path.exists():
        raise RulePackError(f"rule pack not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RulePackError(f"rule pack {path} is not valid JSON: {exc}") from exc
    return parse_rulepack(payload, source=str(path))


def parse_rulepack(payload: dict[str, Any], source: str = "<memory>") -> RulePack:
    codes: dict[str, CodeSpec] = {}
    raw_codes = _require(payload, "codes", source)
    for code, spec in raw_codes.items():
        codes[code] = CodeSpec(
            code=code,
            label=spec.get("label", code),
            phase=spec.get("phase", "unknown"),
            unit=spec.get("unit", ""),
            basis=spec.get("basis", "none"),
            tolerance=float(spec.get("tolerance", 0.10)),
            duplicate_group=spec.get("duplicate_group"),
            evidence_any_of=tuple(spec.get("evidence_any_of", ())),
            note=spec.get("note", ""),
        )
    if not codes:
        raise RulePackError(f"rule pack {source} defines no line codes")
    return RulePack(
        rulepack_id=_require(payload, "rulepack_id", source),
        version=_require(payload, "version", source),
        title=payload.get("title", ""),
        provenance=_require(payload, "provenance", source),
        constants={k: float(v) for k, v in payload.get("constants", {}).items()},
        codes=codes,
        required_rules=tuple(payload.get("required_rules", ())),
        quantity_rules=tuple(payload.get("quantity_rules", ())),
        sequence_rules=tuple(payload.get("sequence_rules", ())),
        duplicate_rules=tuple(payload.get("duplicate_rules", ())),
        documentation_rules=tuple(payload.get("documentation_rules", ())),
        evidence_rules=tuple(payload.get("evidence_rules", ())),
        source=source,
    )
