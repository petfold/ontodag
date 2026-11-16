"""The explainer film (demo/explainer) shows only what odag does.

Every command, answer and root on the film's screen comes from
`demo/explainer/facts.py`, which runs the film's examples on the real
command line and then checks the claims its pictures and narration make.
Run here, a change that made one of them untrue fails in the suite, before
the film has gone stale without anyone noticing.
"""

import importlib.util
from pathlib import Path

FILM = Path(__file__).resolve().parent.parent / "demo" / "explainer"


def test_the_film_shows_what_odag_answers(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "explainer_facts", FILM / "facts.py")
    facts = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(facts)
    facts.check(facts.gather(tmp_path))
