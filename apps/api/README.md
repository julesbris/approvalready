# ApprovalReady API

FastAPI modular monolith. See the repository root `README.md` and `ARCHITECTURE.md`.

```bash
uv sync                               # install (Python 3.12+; images use 3.14)
../../scripts/test-services.sh up     # throwaway Postgres 18 + Redis
uv run pytest                         # tests
uv run alembic upgrade head           # migrations
uv run uvicorn app.main:app --reload  # dev server on :8000
```
