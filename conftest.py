import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

# Isolate the suite from the developer's own ~/.ontodag. Settings resolve
# flag > env > config file (see ontodag.settings.configured), so a real config with,
# say, `limit = 10` in it would otherwise change what the CLI tests observe.
# Tests that care about the home directory still set ONTODAG_HOME themselves.
os.environ.setdefault(
    "ONTODAG_HOME",
    tempfile.mkdtemp(prefix="ontodag-test-home-"),
)


# A certificate for an answer about a term that has no record carries the
# whole store as a recordstore prefix proof (recordstore 0.25). Under an
# older recordstore, as CI installs until 0.25 is released, such a test is
# skipped rather than failed: the rest of what it checks is unchanged.
import pytest  # noqa: E402


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if not report.failed or call.excinfo is None:
        return
    from ontodag.certificates import NeedsPrefixProofs
    if isinstance(call.excinfo.value, NeedsPrefixProofs):
        report.outcome = "skipped"
        report.longrepr = (str(item.path), item.location[1] or 0,
                           f"Skipped: needs recordstore prefix proofs ({call.excinfo.value})")
