import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

# Isolate the suite from the developer's own ~/.ontodag. Settings resolve
# flag > env > config file (see __main__._configured), so a real config with,
# say, `limit = 10` in it would otherwise change what the CLI tests observe.
# Tests that care about the home directory still set ONTODAG_HOME themselves.
os.environ.setdefault(
    "ONTODAG_HOME",
    tempfile.mkdtemp(prefix="ontodag-test-home-"),
)
