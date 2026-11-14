"""Runs every test. On GitHub Actions each failure is also written as an annotation, so it can be read from the
run's summary page (or the API) without opening the full log.

    python ci_run.py            the same as:  python -m unittest discover -p "test_*.py"
"""
import os
import sys
import unittest


def annotate(level, title, text):
    text = text.strip().replace("%", "%25").replace("\r", "").replace("\n", "%0A")
    print("::%s title=%s::%s" % (level, title.replace(",", " ").replace("::", " "), text))


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    suite = unittest.defaultTestLoader.discover(here, pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    bad = [("FAIL", t, tb) for t, tb in result.failures] + [("ERROR", t, tb) for t, tb in result.errors]
    if bad and os.environ.get("GITHUB_ACTIONS"):
        annotate("error", "%d of %d tests did not pass" % (len(bad), result.testsRun),
                 "\n".join("%s %s" % (kind, test.id()) for kind, test, _ in bad)[:3500])
        for kind, test, trace in bad[:8]:
            annotate("error", "%s %s" % (kind, test.id()), trace[-1500:])
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
