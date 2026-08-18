"""Write the app's OpenAPI schema to stdout.

The frontend's TypeScript client and its React Query hooks are generated from
this, so the schema is the contract between the two halves of the project
rather than a document that drifts from them.

Run through the frontend's `bun run api:generate`, which redirects this into
`frontend/openapi.json` and then runs Orval over it.

DATA_DIR is pointed at a temporary directory before importing the app, because
importing it runs init_db(), which would otherwise create tables and seed tags
in whatever database the environment happens to name.
"""

import json
import os
import sys
import tempfile
from pathlib import Path


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="openapi-dump-") as scratch:
        os.environ["DATA_DIR"] = scratch
        os.environ["DATABASE_URL"] = f"sqlite:///{Path(scratch) / 'schema.db'}"
        # The startup secret check is about deployments, not about printing a
        # schema; dev posture keeps this runnable without a configured secret.
        os.environ["APP_ENV"] = "dev"

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import main as app_module

        # sort_keys so regenerating produces no spurious diff.
        json.dump(app_module.app.openapi(), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
