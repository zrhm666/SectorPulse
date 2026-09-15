"""Test-only guard. Never let a contract test point at the business database.

`.env` names the business database, and building an app loads that file into the
process environment — verified: `create_app()` alone is enough to put
`SECTOR_PULSE_DATABASE_URL` there. The `postgres`-marked tests read that very
variable and then migrate and write rows. Without this guard the suite reaches the
business database purely because it was started without the canonical env
blanking, which the project forbids outright.
"""

import os

from sqlalchemy.engine import make_url


class BusinessDatabaseRefused(RuntimeError):
    """The configured PostgreSQL connection is not a dedicated test database."""


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
    if url and not _database_name(url).endswith("_test"):
        raise BusinessDatabaseRefused(
            f"refusing to run the suite against {_database_name(url)!r}; "
            "SECTOR_PULSE_DATABASE_URL must name a dedicated database ending in _test"
        )
