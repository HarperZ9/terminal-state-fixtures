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


def _dumps(data: dict) -> str:
    return json.dumps(data, indent=1, sort_keys=True, ensure_ascii=True) + "\n"


def main() -> int:
    first = _dumps(build_parser_contract())
    second = _dumps(build_parser_contract())
    if first != second:
        print("FATAL: generator is not deterministic", file=sys.stderr)
        return 1
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    target = DATA_DIR / "parser_contract.json"
    target.write_text(first, encoding="utf-8", newline="\n")
    data = json.loads(first)
    n_probes = sum(len(v["probes"]) for v in data.values())
    n_none = sum(
        1 for v in data.values() for p in v["probes"] if p["expect"] is None
    )
    print(
        f"parser_contract.json: {len(data)} variants, {n_probes} probes "
        f"({n_none} expect None), {len(first)} bytes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
