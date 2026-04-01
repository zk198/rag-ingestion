---
description: "Use when writing or modifying test files. Covers test conventions, naming, and how to run tests in Docker."
applyTo: "tests/**/*.py"
---

# Test Conventions

- Test files go in `tests/` and are named `test_<module>.py`
- Test functions are named `test_<behavior_under_test>`
- Type-annotate test functions with `-> None`
- Tests run inside the Docker container by mounting the tests directory:
  ```bash
  docker run --rm -v ./tests:/app/tests pst-agent bash -c "pip install pytest -q && python -m pytest /app/tests/ -v"
  ```
- Use `tempfile.TemporaryDirectory` for tests that need a database or filesystem
- Set `PST_AGENT_*` env vars to point at the temp directory in test setup
- Never import test utilities into production code
