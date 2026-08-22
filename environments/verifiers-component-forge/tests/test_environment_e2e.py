"""Model-free end-to-end: the actual environment, the actual rubric path.

A synthetic "model reply" carrying the inlined reference implementation must
score reward 1.0 through the environment's own parser, reward function, child
execution, and frozen probes; a reply with no code block scores 0.0 with the
diagnostic metrics saying why. This is the slice vf-eval will exercise, minus
only the model."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import verifiers as vf  # noqa: E402
from verifiers.types import State  # noqa: E402

import verifiers_component_forge as forge  # noqa: E402

FAMILY_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "verifiers_component_forge"
    / "families"
    / "parser_contract.py"
).read_text(encoding="utf-8")


def _reference_reply(variant: dict) -> str:
    ladder = ", ".join(repr(r) for r in variant["ladder"])
    module = (
        f"{FAMILY_SOURCE}\n\n"
        f"VARIANT = Variant(({ladder},), {variant['scope']!r}, "
        f"{variant['think_strip']}, {variant['empty_hit']})\n\n"
        "class P:\n"
        "    def parse_answer(self, completion):\n"
        "        return reference_parse(VARIANT, completion)\n\n"
        "def build_parser():\n"
        "    return P()\n"
    )
    return (
        "Here is my implementation of the contract.\n\n"
        "```python\n" + module + "\n```\n\nDone."
    )


def _user_rubric(env) -> vf.Rubric:
    rubric = env.rubric
    if isinstance(rubric, vf.RubricGroup):
        rubric = rubric.rubrics[0]
    return rubric


async def _score(env, row, reply_text: str) -> State:
    state = State(
        {
            "prompt": row["question"],
            "completion": [{"role": "assistant", "content": reply_text}],
            "answer": row["answer"],
            "info": row["info"],
            "task": {},
        }
    )
    await _user_rubric(env).score_rollout(state)
    return state


def test_reference_reply_scores_one_through_the_real_environment():
    env = forge.load_environment()
    dataset = env.get_dataset()
    assert len(dataset) == 96
    row = dataset[0]
    frozen = forge._load_frozen("parser_contract.json")
    variant = frozen[row["answer"]]["variant"]

    state = asyncio.run(_score(env, row, _reference_reply(variant)))
    assert state["reward"] == 1.0, state["metrics"]
    assert state["metrics"]["parsed_code_present"] == 1.0
    assert state["metrics"]["child_completed"] == 1.0
    assert state["metrics"]["probe_error_fraction"] == 0.0


def test_codeless_reply_scores_zero_with_diagnostics():
    env = forge.load_environment()
    row = env.get_dataset()[0]
    state = asyncio.run(_score(env, row, "I think the answer is just the tag."))
    assert state["reward"] == 0.0
    assert state["metrics"]["parsed_code_present"] == 0.0
    assert state["metrics"]["child_completed"] == 0.0


def test_prompt_states_the_whole_contract():
    env = forge.load_environment()
    for row in (env.get_dataset()[0], env.get_dataset()[95]):
        q = row["question"]
        assert "build_parser()" in q
        assert "EMPTY RULE" in q
        assert "Worked examples" in q
        assert "```python" in q
        # the worked-example payload never collides with scored probes
        assert "exampleAlpha" in q
