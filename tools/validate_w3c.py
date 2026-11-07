"""Validate the captured HTML and the project CSS with the Nu Html Checker (W3C).

    python -m tools.validate_w3c --jar path/to/vnu.jar --html build/html

- HTML: every page written by ``tools.html_capture`` during the tests.
- CSS: every ``.css`` file of the project, except generated folders.

The program exits with a non-zero code if the validator reports an error.
Validator docs: https://validator.github.io/validator/docs/vnu.1.html
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IGNORED_FOLDERS = {".git", ".venv", "venv", "node_modules", "staticfiles", "build", "media"}


def css_files(root=ROOT):
    """CSS files written for the project (generated folders are ignored)."""
    return sorted(
        path
        for path in root.rglob("*.css")
        if not IGNORED_FOLDERS.intersection(path.relative_to(root).parts)
    )


def run_validator(jar, arguments):
    command = ["java", "-jar", str(jar), *arguments]
    return subprocess.run(command, check=False).returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--jar", required=True, type=Path, help="path to vnu.jar")
    parser.add_argument("--html", type=Path, default=ROOT / "build" / "html")
    args = parser.parse_args(argv)

    errors = 0
    pages = sorted(args.html.glob("*.html")) if args.html.is_dir() else []
    if pages:
        print(f"HTML: {len(pages)} page(s) to validate")
        errors += run_validator(args.jar, ["--skip-non-html", str(args.html)])
    else:
        print("HTML: no captured page yet")

    stylesheets = css_files()
    if stylesheets:
        print(f"CSS: {len(stylesheets)} file(s) to validate")
        errors += run_validator(args.jar, ["--css", *map(str, stylesheets)])
    else:
        print("CSS: no file yet")

    if errors:
        print("The W3C validator reports errors.", file=sys.stderr)
        return 1
    print("W3C validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
