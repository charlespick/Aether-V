# Testing the Aether-V Server

This project uses [pytest](https://pytest.org/) to exercise the FastAPI server. The
suite focuses on high-value integration coverage of the API layer while keeping
external dependencies mocked so tests stay fast and deterministic.

## Directory layout

Tests live in `server/tests/` and are split by feature:

- `test_health_and_readiness.py` exercises the health and readiness endpoints and
  the security middleware headers.
- `test_inventory_routes.py` validates inventory summaries produced from the
  in-memory development data set.
- `test_job_routes.py` validates schema-aware provisioning behaviour.

Common fixtures reside in `server/tests/conftest.py` where the FastAPI
application is initialised with:

- Development-friendly environment defaults (authentication disabled, dummy
  data enabled).
- Patched service methods for WinRM and host deployment to avoid real network
  access.
- A shared FastAPI `TestClient` fixture that injects an authenticated test user.

## Running the tests locally

The `server/Makefile` provisions an isolated virtual environment for you. Run:

```bash
cd server
make test
```

The first invocation creates `.venv/`, installs both `requirements.txt` and
`requirements-test.txt`, and then executes `pytest`. Subsequent runs reuse the
existing environment unless the requirements change. You can pass additional
pytest flags via `PYTEST_ARGS`, for example `make test PYTEST_ARGS="-vv"`.

> [!NOTE]
> The tests rely on FastAPI and related runtime dependencies. If package
> installation fails (for example, due to offline mirrors), `make test` emits a
> warning and skips execution until the dependencies can be installed
> successfully.

## Continuous integration

A GitHub Actions workflow (`.github/workflows/server-tests.yml`) executes the
same `make test` command for pushes to the `main` and `server` branches and for
pull requests that touch the server code. The job installs the standard server
requirements plus the testing dependencies before running the suite.

## Tips for extending tests

- Prefer exercising routes through the shared `client` fixture rather than
  importing internal functions. This maintains realistic coverage of routing,
  dependency injection, and middleware.
- When adding new tests that interact with background services, patch external
  I/O in `conftest.py` to keep the suite hermetic.
- If new schema files are introduced, update the `DEFAULT_SCHEMA_PATH` override
  in `conftest.py` so tests use the intended fixtures.
