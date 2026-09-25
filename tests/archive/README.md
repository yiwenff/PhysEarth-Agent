# Archived tests

These tests exercise evaluation runners and result files that were removed from the tree
in commit `35eee2c` ("update evaluation dashboard"):

- `evaluation/runners/tier0.py`, `model_registration.py`, `registry_contract.py`,
  `registration_demo.py`, `dashboard.py`, `llm_smoke.py`, `llm_robustness.py`,
  `reproduction_eval.py`;
- `evaluation/results/tier0.json`, `model_registration.json`, `registry_contract.json`,
  `registration_demo.json`, `llm_robustness.json`.

They are not collected (`tests/conftest.py`). Each test is kept unchanged apart from the
repository-root path, so it can be moved back into `tests/` when its runner is restored
with `git checkout 35eee2c~1 -- <runner>` and its result file regenerated. A test whose
runner is retired for good should be deleted with it rather than left here.
