"""Test-only guard. Never let a contract test point at the business database.

`.env` names the business database, and building an app loads that file into the
process environment — verified: `create_app()` alone is enough to put
`SECTOR_PULSE_DATABASE_URL` there. The `postgres`-marked tests read that very
variable and then migrate and write rows. Without this guard the suite reaches the
business database purely because it was started without the canonical env
blanking, which the project forbids outright.

The name rule itself lives in `dedicated_resources`, together with the bucket and
collection guards that state the same thing about other servers. `BusinessDatabaseRefused`
is kept as the name those call sites and tests already catch.
"""

import os

from sqlalchemy.engine import make_url

from backend.tests.dedicated_resources import (
    BusinessResourceRefused,
    require_test_name,
)

#: 与 bucket / collection 共用同一个拒绝类型：这是一条规则，调用方该只 `except` 一次。
BusinessDatabaseRefused = BusinessResourceRefused


def _database_name(url: str) -> str:
    return make_url(url).database or ""


def isolate_configured_postgres_url() -> None:
    """Keep the business connection out of the suite's reach, or refuse to run.

    An unset variable is blanked rather than left alone: dotenv does not overwrite
    a value that is already present, so the empty string is what stops `.env` from
    smuggling the business URL in later. A URL that names something other than a
    `_test` database is the one configuration that can only mean business writes,
    so it fails instead of quietly proceeding.
    """
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
    if url is None:
        os.environ["SECTOR_PULSE_DATABASE_URL"] = ""
        return
    if url:
        require_test_name(
            kind="database",
            value=_database_name(url),
            variable="SECTOR_PULSE_DATABASE_URL",
            suffixes=("_test",),
        )
