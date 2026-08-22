# terminal-state fixtures

Evaluation environments that score an AI agent by the terminal state of its
work, not by what its transcript claims. Each environment ships an exhaustive
dataset, a deterministic reference scorer, and rewards whose discrimination is
pinned by tests, so every score is re-derivable on any machine.

## Why terminal state

A transcript says what a model believes happened. The environment's terminal
state says what happened. When the two disagree, the terminal state wins, and
an evaluation built on it cannot be talked into a better score. The same
discipline covers the denominator: a provider outage or a blocked launch is
excluded from the quality denominator rather than counted as a failure, so a
regression in the numbers means a regression in the behavior.

## Environments

### mlflow-terminal-state

Classify agent-run records into seven terminal verdicts and decide which runs
belong in the quality denominator. 324 records, every reachable field
combination, no sampling. Published on Prime Intellect's Environments Hub as
`zaindanaharper/mlflow-terminal-state`.

Load it directly:

```python
import mlflow_terminal_state

env = mlflow_terminal_state.load_environment()  # a verifiers SingleTurnEnv
dataset = mlflow_terminal_state.build_dataset()  # 324 rows, deterministic
```

Or install from the hub and evaluate with the [verifiers](https://github.com/willccbb/verifiers)
toolchain; the hub page carries the install command for your setup.

Full task, dataset, and reward spec:
[environments/mlflow_terminal_state/README.md](environments/mlflow_terminal_state/README.md).

### verifiers-component-forge

Write and repair verifiers components against terminal-state contracts. The
environment now includes parser, rubric, and synthetic redaction contract
families. The redaction family uses fake secret markers only, scores terminal
JSON output, and pins that expected outputs preserve public metadata while
removing every raw marker value.

Reproduce:
[environments/verifiers-component-forge/REPRODUCE.md](environments/verifiers-component-forge/REPRODUCE.md).

## The claims are tests

The spec's validation claims are pinned in
[environments/mlflow_terminal_state/tests](environments/mlflow_terminal_state/tests):
the dataset is exhaustive and builds identically twice, correct answers score
1.0, wrong verdicts and garbage score 0.0, integrity beats the oracle, and a
missing oracle is an honest null rather than a pass.

```bash
cd environments/mlflow_terminal_state
uv venv && uv pip install verifiers pytest
uv run pytest tests/ -q
```

The component-forge claims are pinned in
[environments/verifiers-component-forge/tests](environments/verifiers-component-forge/tests):
frozen data regenerates deterministically, reference components score 1.0,
known-bad implementations fail, and redacted expected outputs contain no raw
synthetic secret markers.

## Reusing the pattern

To build a terminal-state environment for another tool: enumerate the reachable
states of the thing being scored, write the reference scorer first, generate the
dataset from the scorer so ground truth is re-derivable, then pin the scorer's
subtle cases and the rewards' discrimination as tests. The environment here is
small enough to read in one sitting and serves as the worked example.

One environment is published today. More follow as they clear the same bar.
