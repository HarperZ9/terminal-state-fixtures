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
    frozen = _load_frozen("parser_contract.json")
    parser = LastPythonFenceParser()

    rows = []
    from .families.parser_contract_prompt import render_prompt

    for variant_id in sorted(frozen):
        entry = frozen[variant_id]
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

    async def _run_probes(completion, info) -> dict:
        """One child run for this rollout; memoization-free by design (each
        rollout is independent)."""
        module_source = parser.parse_answer(completion)
        if module_source is None:
            return {"skipped": "no-code"}
        entry = frozen[info["variant_id"]]
        result = await runner.run_child(
            "child_driver_parser.py",
            module_source,
            [p["recipe"] for p in entry["probes"]],
            wall_clock=60.0,
        )
        if not result.ok:
            return {"skipped": result.failure or "child-failure"}
        return {"results": result.payload["results"], "entry": entry}

    async def terminal_state_match(completion, info, state, **_kwargs) -> float:
        outcome = await _run_probes(completion, info)
        state["forge_outcome"] = outcome  # shared with the 0-weight metrics
        if "results" not in outcome:
            return 0.0
        entry = outcome["entry"]
        return runner.match_fraction(
            outcome["results"],
            [p["expect"] for p in entry["probes"]],
            [p["weight"] for p in entry["probes"]],
        )

    def parsed_code_present(completion, **_kwargs) -> float:
        return 1.0 if parser.parse_answer(completion) is not None else 0.0

    def child_completed(state, **_kwargs) -> float:
        outcome = state.get("forge_outcome") or {}
        return 1.0 if "results" in outcome else 0.0

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
            probe_error_fraction,
        ],
        weights=[1.0, 0.0, 0.0, 0.0],
        parser=parser,
    )

    return vf.SingleTurnEnv(
        dataset=Dataset.from_list(rows),
        parser=parser,
        rubric=rubric,
        **kwargs,
    )
