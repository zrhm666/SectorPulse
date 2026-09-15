"""Versioned SQL migrations, applied in filename order.

`MIGRATIONS_DIR` is the single source of truth for their location: the SQLite and
PostgreSQL initializers both glob it, and a test that has to replay history up to a
given version needs it too.
"""

from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent
