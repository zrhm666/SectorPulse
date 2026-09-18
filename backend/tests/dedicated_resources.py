"""Test-only guard for suites that need a real server.

`.env` names the business database, the business bucket and the business collection, and
building an app loads that file into the process environment. The marked suites then
connect and *write*. `postgres_isolation` already refuses a business database by name;
buckets and collections obey the same rule, which is why they live here rather than in
each test module.

The rule has to hold **before** a client exists. A check that runs after the connection
is a comment, not a gate — it can still report a clean run while having already touched
the wrong server. So the guard owns the construction: `connect_to_dedicated_resource`
resolves the name, refuses it unless it is named as a test resource, and only then calls
the factory that opens the connection. There is no path to a client that skips it, and
the factory is what a test can substitute to prove the order.

Two outcomes, deliberately different:

- **Unset** is a missing precondition → `pytest.skip`. Nobody configured a test resource.
- **Misnamed** is a mistake → refuse. A bucket called `sectorpulse-research` can only mean
  production, and "we'll find out by deleting someone's uploads" is not a plan.
"""

from __future__ import annotations

import os
from collections.abc import Callable

import pytest

#: Both spellings are accepted; callers pass the subset their resource actually uses.
TEST_SUFFIXES: tuple[str, ...] = ("_test", "-test")


class BusinessResourceRefused(RuntimeError):
    """A configured resource is not named as a dedicated test resource."""


def require_test_name(
    *,
    kind: str,
    value: str,
    variable: str,
    suffixes: tuple[str, ...] = TEST_SUFFIXES,
) -> str:
    """Return a resource name, or refuse it because it is not a test resource."""
    if not value.endswith(suffixes):
        raise BusinessResourceRefused(
            f"refusing to run against {kind} {value!r}; "
            f"{variable} must name a dedicated test resource ending in {' or '.join(suffixes)}"
        )
    return value


def dedicated_resource_name(
    *,
    kind: str,
    variable: str,
    suffixes: tuple[str, ...] = TEST_SUFFIXES,
) -> str:
    """Read a resource name from the environment: unset skips, misnamed refuses."""
    value = os.environ.get(variable, "")
    if not value:
        pytest.skip(f"no dedicated {kind} is configured")
    return require_test_name(kind=kind, value=value, variable=variable, suffixes=suffixes)


def connect_to_dedicated_resource[T](
    *,
    kind: str,
    variable: str,
    connect: Callable[[str], T],
    suffixes: tuple[str, ...] = TEST_SUFFIXES,
) -> T:
    """Resolve a dedicated test resource and hand it to `connect` — or refuse first.

    Order is the whole point: the factory is not called until the name has passed.
    """
    return connect(
        dedicated_resource_name(kind=kind, variable=variable, suffixes=suffixes)
    )


__all__ = [
    "TEST_SUFFIXES",
    "BusinessResourceRefused",
    "connect_to_dedicated_resource",
    "dedicated_resource_name",
    "require_test_name",
]
