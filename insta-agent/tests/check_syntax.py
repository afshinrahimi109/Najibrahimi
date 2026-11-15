"""Quick syntax check while editing insta_agent.py (the tests and the browser checks do the real checking).

    python check_syntax.py

- compiles the Python file;
- pulls the panel's JavaScript out of UI_HTML and lets node check its syntax (skipped when node is missing);
- runs pyflakes when it is installed (pip install pyflakes).
"""
import os
import py_compile
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "..", "insta_agent.py")


def main():
    bad = 0
    try:
        py_compile.compile(TARGET, doraise=True, cfile=os.path.join(tempfile.gettempdir(), "ia-check.pyc"))
        print("PY: OK")
    except py_compile.PyCompileError as e:
        print("PY: FAILED\n%s" % e)
        return 1
    with open(TARGET, encoding="utf-8") as fh:
        src = fh.read()
    start = src.index("UI_HTML = r'''") + len("UI_HTML = r'''")
    html = src[start:src.index("'''", start)]
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.S)
    node = shutil.which("node")
    if not scripts:
        print("JS: no <script> found in UI_HTML")
        bad = 1
    elif not node:
        print("JS: skipped (node is not installed)")
    else:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
            fh.write("\n".join(scripts))
            path = fh.name
        try:
            res = subprocess.run([node, "--check", path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        finally:
            os.remove(path)
        if res.returncode:
            print("JS syntax: FAILED\n" + res.stdout[-3000:])
            bad = 1
        else:
            print("JS syntax: OK (%d lines)" % sum(s.count("\n") for s in scripts))
    flakes = [sys.executable, "-m", "pyflakes"]
    try:
        import pyflakes                                  # noqa: F401
    except ImportError:
        alt = os.path.join(tempfile.gettempdir(), "venv", "bin", "python")
        flakes = [alt, "-m", "pyflakes"] if os.path.exists(alt) else None
    if not flakes:
        print("pyflakes: skipped (not installed)")
    else:
        res = subprocess.run(flakes + [TARGET], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        if res.stdout.strip():
            print("pyflakes:\n" + res.stdout[-3000:])
            bad = 1
        else:
            print("pyflakes: clean")
    return bad


if __name__ == "__main__":
    sys.exit(main())
