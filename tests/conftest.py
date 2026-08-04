"""Test-wide setup.

The scoring tests pin the *shipped* model — jars, $25 deals, Zanesville.
Those constants can be replaced at import time by a ``business.json`` in
the project root, so on a machine where someone has actually run
``python -m fnscraper setup`` (a developer configuring their own booth)
the suite would fail on their settings rather than on the code.  Point the
loader at a path that cannot exist for the duration of the run.
"""

from __future__ import annotations

import importlib
import os
import tempfile

import pytest

from fnscraper import business, config

_ABSENT = os.path.join(tempfile.gettempdir(), "fnscraper-tests-no-business.json")


@pytest.fixture(autouse=True, scope="session")
def shipped_defaults():
    previous = os.environ.get(business.ENV_BUSINESS_FILE)
    os.environ[business.ENV_BUSINESS_FILE] = _ABSENT
    importlib.reload(config)
    yield config
    if previous is None:
        os.environ.pop(business.ENV_BUSINESS_FILE, None)
    else:
        os.environ[business.ENV_BUSINESS_FILE] = previous
    importlib.reload(config)
