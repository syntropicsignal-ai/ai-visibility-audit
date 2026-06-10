#!/usr/bin/env bash
# Apply pending alembic migrations, then exec the container's CMD.
set -euo pipefail
PYTHONPATH=. uv run alembic upgrade head
exec "$@"
