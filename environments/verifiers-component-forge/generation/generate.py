"""Offline generator for verifiers-component-forge frozen expectations.

Runs the committed reference implementations over each family's input grammar
and freezes the results as JSON committed to the repo. Regeneration is this
one command; a diff in the frozen file means the reference, the grammar, or
the variant table changed, never ambient state:

    python generation/generate.py

Determinism is asserted, not assumed: the file is built twice in-process and
byte-compared before it is written.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from verifiers_component_forge.families import parser_contract as pc  # noqa: E402
from verifiers_component_forge.families import parser_contract_grammar as pcg  # noqa: E402
from verifiers_component_forge.families import redaction_contract as red  # noqa: E402
from verifiers_component_forge.families import rubric_contract as rc  # noqa: E402
from verifiers_component_forge.families import rubric_contract_grammar as rcg  # noqa: E402
from verifiers_component_forge.harness.child_driver_parser import (  # noqa: E402
    _build_completion,
)

DATA_DIR = ROOT / "verifiers_component_forge" / "data"


def build_parser_contract() -> dict:
    out: dict[str, dict] = {}
    for variant in pc.all_variants():
        probes = pcg.probes_for(variant)
        weights = pcg.probe_weights(probes)
        rows = []
        for probe, weight in zip(probes, weights):
            completion = _build_completion(probe["recipe"])
            expect = pc.reference_parse(variant, completion)
            rows.append(
                {
                    "cell": probe["cell"],
                    "recipe": probe["recipe"],
                    "weight": round(weight, 12),
                    "expect": expect,
                }
            )
        out[variant.variant_id] = {
            "variant": {
                "ladder": list(variant.ladder),
                "scope": variant.scope,
                "think_strip": variant.think_strip,
                "empty_hit": variant.empty_hit,
            },
            "probes": rows,
        }
    return out


def build_rubric_contract() -> dict:
    """Execute each contract's reference module through the REAL verifiers
    machinery (the exact path the child driver replays) and freeze rewards
    and metrics per fixture."""
    import asyncio
    import types

    import verifiers as vf
    from verifiers.types import State

    out: dict[str, dict] = {}
    for contract in rc.all_contracts():
        source = rc.reference_module_source(contract)
        module = types.ModuleType("reference_module")
        sys.modules["reference_module"] = module
        exec(compile(source, "<reference_module>", "exec"), module.__dict__)
        env = module.load_environment()
        rubric = env.rubric
        if isinstance(rubric, vf.RubricGroup):
            rubric = rubric.rubrics[0]

        async def score(fixture: dict) -> dict:
            state = State(
                {
                    "prompt": fixture["prompt"],
                    "completion": fixture["completion"],
                    "answer": fixture["answer"],
                    "info": fixture["info"],
                    "task": {},
                }
            )
            await rubric.score_rollout(state)
            return {
                "reward": float(state["reward"]),
                "metrics": {k: float(v) for k, v in state["metrics"].items()},
            }

        rows = []
        for fixture in rcg.fixtures_for(contract):
            expect = asyncio.run(score(fixture))
            rows.append(
                {
                    "cell": fixture["cell"],
                    "fixture": {
                        "prompt": fixture["prompt"],
                        "completion": fixture["completion"],
                        "answer": fixture["answer"],
                        "info": fixture["info"],
                    },
                    "expect": expect,
                }
            )
        worked = []
        for fixture in rcg.worked_for(contract):
            worked.append(
                {
                    "cell": fixture["cell"],
                    "fixture": {
                        "prompt": fixture["prompt"],
                        "completion": fixture["completion"],
                        "answer": fixture["answer"],
                        "info": fixture["info"],
                    },
                    "expect": asyncio.run(score(fixture)),
                }
            )
        out[contract.variant_id] = {
            "worked": worked,
            "contract": {
                "table_ix": contract.table_ix,
                "names": [c.name for c in contract.criteria],
                "kinds": [[c.name, c.kind, c.param] for c in contract.criteria],
                "weights": list(contract.effective_weights),
                "exclusion": contract.exclusion,
                "negative": contract.negative,
            },
            "fixtures": rows,
        }
    return out


def build_redaction_contract() -> dict:
    out: dict[str, dict] = {}
    for variant in red.all_variants():
        rows = []
        for fixture in red.fixtures_for(variant):
            rows.append(
                {
                    "cell": fixture["cell"],
                    "record": fixture["record"],
                    "expect": red.reference_redact(fixture["record"]),
                }
            )
        out[variant.variant_id] = {
            "variant": {
                "title": variant.title,
                "purpose": variant.purpose,
            },
            "worked": red.worked_for(variant),
            "fixtures": rows,
        }
    return out


def _declared_raw_secret_values(record: dict) -> list[str]:
    rows = record.get("secrets") or []
    values = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        raw = item.get("value")
        if isinstance(raw, str) and raw:
            values.append(raw)
    return values


def assert_redaction_expected_safe(data: dict) -> int:
    """Fail closed if any expected output contains a declared raw secret.

    The scan derives raw values from each row's own ``record['secrets']``
    declarations, so it catches non-standard synthetic values as well as the
    standard ``FAKE_SECRET_DO_NOT_USE_LOOP29`` marker family.
    """
    checked_values = 0
    for variant_id, entry in sorted(data.items()):
        if not isinstance(entry, dict):
            raise ValueError(f"{variant_id}: redaction entry must be a dict")
        for section in ("fixtures", "worked"):
            rows = entry.get(section)
            if not isinstance(rows, list):
                raise ValueError(f"{variant_id}: {section} must be a list")
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError(f"{variant_id}/{section}: row must be a dict")
                cell = row.get("cell", "<unknown>")
                record = row.get("record")
                if not isinstance(record, dict):
                    raise ValueError(
                        f"{variant_id}/{section}/{cell}: record must be a dict"
                    )
                expected = json.dumps(
                    row.get("expect"), sort_keys=True, ensure_ascii=True
                )
                for raw in _declared_raw_secret_values(record):
                    checked_values += 1
                    if raw in expected:
                        raise ValueError(
                            "declared raw secret leaked into expected JSON at "
                            f"{variant_id}/{section}/{cell}"
                        )
    return checked_values


def _dumps(data: dict) -> str:
    return json.dumps(data, indent=1, sort_keys=True, ensure_ascii=True) + "\n"


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    first = _dumps(build_parser_contract())
    second = _dumps(build_parser_contract())
    if first != second:
        print("FATAL: parser_contract generator is not deterministic", file=sys.stderr)
        return 1
    (DATA_DIR / "parser_contract.json").write_text(first, encoding="utf-8", newline="\n")
    data = json.loads(first)
    n_probes = sum(len(v["probes"]) for v in data.values())
    n_none = sum(
        1 for v in data.values() for p in v["probes"] if p["expect"] is None
    )
    print(
        f"parser_contract.json: {len(data)} variants, {n_probes} probes "
        f"({n_none} expect None), {len(first)} bytes"
    )

    first = _dumps(build_rubric_contract())
    second = _dumps(build_rubric_contract())
    if first != second:
        print("FATAL: rubric_contract generator is not deterministic", file=sys.stderr)
        return 1
    (DATA_DIR / "rubric_contract.json").write_text(first, encoding="utf-8", newline="\n")
    data = json.loads(first)
    n_fx = sum(len(v["fixtures"]) for v in data.values())
    rewards = sorted(
        {p["expect"]["reward"] for v in data.values() for p in v["fixtures"]}
    )
    print(
        f"rubric_contract.json: {len(data)} contracts, {n_fx} fixtures, "
        f"{len(rewards)} distinct rewards "
        f"(min {rewards[0]}, max {rewards[-1]}), {len(first)} bytes"
    )

    redaction_data = build_redaction_contract()
    first = _dumps(redaction_data)
    second = _dumps(build_redaction_contract())
    if first != second:
        print("FATAL: redaction_contract generator is not deterministic", file=sys.stderr)
        return 1
    try:
        n_checked_raw = assert_redaction_expected_safe(redaction_data)
    except ValueError as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 1
    (DATA_DIR / "redaction_contract.json").write_text(
        first, encoding="utf-8", newline="\n"
    )
    data = json.loads(first)
    n_fx = sum(len(v["fixtures"]) for v in data.values())
    print(
        f"redaction_contract.json: {len(data)} variants, {n_fx} fixtures, "
        f"0 declared raw secret leaks across {n_checked_raw} values, {len(first)} bytes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
