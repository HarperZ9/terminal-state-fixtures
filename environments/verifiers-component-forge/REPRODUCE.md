# Reproduce verifiers-component-forge

This environment is a local, synthetic fixture family for writing verifiers
components against terminal-state contracts. It does not contact a model, a
provider, a network service, or a private endpoint during its tests.

## Setup

Run from this directory:

```bash
uv run --python 3.13 --prerelease=allow --with pytest python -m pytest tests/ -q
```

If `uv` selects Python 3.14, force Python 3.13 as shown above. The project pins
its supported Python range to `>=3.11,<3.14` because `verifiers` currently
publishes in that range.

## Regenerate frozen fixtures

```bash
uv run --python 3.13 --prerelease=allow python generation/generate.py
```

The generator builds each frozen JSON file twice in one process and refuses to
write if either build differs. Test coverage then compares the committed files
against fresh regeneration.

## Rubric-repair kill-check

The `rubric-repair` family ships only mutants that flip at least two battery
fixtures under the installed verifiers, so one flip is shown as the visible
symptom while at least one stays hidden and scored. The generator refused the
`guard-dropped` operator wholesale: verifiers itself scores a raising reward
function as 0.0, which makes removing the reference's try/except behaviorally
invisible, and a non-discriminating mutant never ships. The frozen file
records a no-op ceiling per instance (0.0 for gate-breaking mutants, the
regression share 0.15 otherwise); tests assert every ceiling and replay a
sample through the real child driver.

```bash
uv run --python 3.13 --prerelease=allow --with pytest python -m pytest tests/test_rubric_repair.py -q
```

## Redaction-contract public-safety check

The `redaction-contract` family uses only fake marker values with the prefix
`FAKE_SECRET_DO_NOT_USE_LOOP29`. Raw markers are allowed in synthetic input
fixtures because the scorer needs something to redact. The expected terminal
outputs are scanned by tests and must not contain that prefix.

Relevant tests:

```bash
uv run --python 3.13 --prerelease=allow --with pytest python -m pytest tests/test_redaction_contract.py -q
```

## Does not prove

Passing these tests does not prove upstream maintainer interest, model quality,
production secret handling, sandbox security, legal clearance, or readiness to
publish. The child-process runner is a deterministic scoring boundary, not a
security sandbox. Any public release still needs a fresh public-safety scan,
repository status check, and action-time approval.
