"""Write the API's OpenAPI schema to packages/shared-types/openapi.json.

    cd apps/api && uv run python scripts/export_openapi.py

The web app's TypeScript types are generated from this file (``npm run generate:types``);
CI fails if either is stale.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Environment, Settings
from app.main import create_app

OUT = Path(__file__).resolve().parents[3] / "packages" / "shared-types" / "openapi.json"


def main() -> None:
    settings = Settings(app_env=Environment.DEVELOPMENT, _env_file=None)  # type: ignore[call-arg]
    schema = create_app(settings).openapi()
    OUT.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
