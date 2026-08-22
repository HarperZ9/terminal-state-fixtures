"""verifiers-component-forge: write and repair verifiers components against
normative behavioral contracts, scored by terminal state.

The agent receives a fully normative contract and must emit a Python module;
scoring executes that module in an isolated child interpreter over hidden
frozen probes and compares terminal state against reference-derived
expectations. No judge model, no network, and the oracle never enters the
child process. See DESIGN.md for the family designs and the freeze pipeline.
"""
from __future__ import annotations

import json
from pathlib import Path

import verifiers as vf
from datasets import Dataset

from .families.parser_contract import Variant, scope_text
from .harness import runner

_DATA_DIR = Path(__file__).resolve().parent / "data"


def _load_frozen(name: str) -> dict:
    return json.loads((_DATA_DIR / name).read_text(encoding="utf-8"))


class LastPythonFenceParser(vf.Parser):
    """The environment's own completion parser: from the LAST ```python opener
    to the LAST ``` closer in the reply, all messages joined.

    Deliberately NOT the contract's own non-greedy fence rung: an honest
    solution frequently contains triple-backtick literals (docstrings quoting
    the contract, regexes implementing fence rungs), and a first-close parser
    would truncate it mid-module. Last-opener-to-last-closer survives that,
    and the emission protocol documents it."""

    def parse_answer(self, completion) -> str | None:  # type: ignore[override]
        text = scope_text(completion, "joined")
        opener = text.rfind("```python\n")
        if opener == -1:
            return None
        start = opener + len("```python\n")
        closer = text.rfind("```")
        if closer <= start:
            return None
        content = text[start:closer].strip()
        return content or None


def load_environment(**kwargs) -> vf.Environment:
    frozen_parser = _load_frozen("parser_contract.json")
    frozen_rubric = _load_frozen("rubric_contract.json")
    parser = LastPythonFenceParser()

    rows = []
    from .families.parser_contract_prompt import render_prompt
    from .families.rubric_contract_prompt import render_prompt as render_rubric_prompt

    for variant_id in sorted(frozen_parser):
        entry = frozen_parser[variant_id]
        v = entry["variant"]
        variant = Variant(
            tuple(v["ladder"]), v["scope"], v["think_strip"], v["empty_hit"]
        )
        rows.append(
            {
                "question": render_prompt(variant),
                "answer": variant_id,
                "info": {"family": "parser-contract", "variant_id": variant_id},
            }
        )
    for variant_id in sorted(frozen_rubric):
        entry = frozen_rubric[variant_id]
        rows.append(
            {
                "question": render_rubric_prompt(entry["contract"], entry["worked"]),
                "answer": variant_id,
                "info": {"family": "rubric-contract", "variant_id": variant_id},
            }
        )

    async def _run_parser_family(module_source: str, entry: dict) -> tuple[dict, float]:
        result = await runner.run_child(
            "child_driver_parser.py",
            module_source,
            [p["recipe"] for p in entry["probes"]],
            wall_clock=60.0,
        )
        if not result.ok:
            return {"skipped": result.failure or "child-failure"}, 0.0
        score = runner.match_fraction(
            result.payload["results"],
            [p["expect"] for p in entry["probes"]],
            [p["weight"] for p in entry["probes"]],
        )
        return {"results": result.payload["results"]}, score

    async def _run_rubric_family(module_source: str, entry: dict) -> tuple[dict, float]:
        contract = entry["contract"]
        result = await runner.run_child(
            "child_driver_rubric.py",
            module_source,
            {
                "contract": {
                    "names": contract["names"],
                    "weights": contract["weights"],
                },
                "fixtures": [p["fixture"] for p in entry["fixtures"]],
            },
            wall_clock=90.0,
        )
        if not result.ok:
            return {"skipped": result.failure or "child-failure"}, 0.0
        gate = result.payload["gate"]
        outcome = {"results": result.payload["results"], "gate": gate}
        if not all(gate.values()):
            return outcome, 0.0
        score = runner.match_fraction(
            result.payload["results"],
            [p["expect"] for p in entry["fixtures"]],
        )
        return outcome, score

    async def terminal_state_match(completion, info, state, **_kwargs) -> float:
        module_source = parser.parse_answer(completion)
        if module_source is None:
            state["forge_outcome"] = {"skipped": "no-code"}
            return 0.0
        if info["family"] == "parser-contract":
            outcome, score = await _run_parser_family(
                module_source, frozen_parser[info["variant_id"]]
            )
        else:
            outcome, score = await _run_rubric_family(
                module_source, frozen_rubric[info["variant_id"]]
            )
        state["forge_outcome"] = outcome  # shared with the 0-weight metrics
        return score

    def parsed_code_present(completion, **_kwargs) -> float:
        return 1.0 if parser.parse_answer(completion) is not None else 0.0

    def child_completed(state, **_kwargs) -> float:
        outcome = state.get("forge_outcome") or {}
        return 1.0 if "results" in outcome else 0.0

    def structural_gate_pass(state, **_kwargs) -> float:
        outcome = state.get("forge_outcome") or {}
        gate = outcome.get("gate")
        if gate is None:
            return 1.0  # families without a structural gate
        return 1.0 if all(gate.values()) else 0.0

    def probe_error_fraction(state, **_kwargs) -> float:
        outcome = state.get("forge_outcome") or {}
        results = outcome.get("results")
        if not results:
            return 1.0
        errored = sum(1 for r in results if isinstance(r, dict) and "error" in r)
        return errored / len(results)

    rubric = vf.Rubric(
        funcs=[
            terminal_state_match,
            parsed_code_present,
            child_completed,
            structural_gate_pass,
            probe_error_fraction,
        ],
        weights=[1.0, 0.0, 0.0, 0.0, 0.0],
        parser=parser,
    )

    return vf.SingleTurnEnv(
        dataset=Dataset.from_list(rows),
        parser=parser,
        rubric=rubric,
        **kwargs,
    )
