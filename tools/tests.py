import io
import os
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from django.http import HttpResponse
from django.test import SimpleTestCase

from .html_capture import save_page
from .validate_w3c import css_files, main


class HtmlCaptureTests(SimpleTestCase):
    def test_does_nothing_without_capture_folder(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(save_page("home", HttpResponse("<p>x</p>")))

    def test_writes_the_page_with_a_safe_file_name(self):
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.dict(os.environ, {"HTML_CAPTURE_DIR": folder}):
                path = save_page("Accueil / Résident", HttpResponse("<p>x</p>"))
            self.assertEqual(path.name, "accueil-r-sident.html")
            self.assertEqual(path.read_bytes(), b"<p>x</p>")


class W3CValidationTests(SimpleTestCase):
    def test_ignores_css_of_generated_folders(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for relative in ("static/css/site.css", "staticfiles/admin/base.css", ".venv/x.css"):
                (root / relative).parent.mkdir(parents=True, exist_ok=True)
                (root / relative).write_text("a { color: red }")
            found = [p.relative_to(root).as_posix() for p in css_files(root)]
            self.assertEqual(found, ["static/css/site.css"])

    def test_fails_if_the_validator_reports_an_error(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "page.html").write_text("<p>x</p>")
            with (
                mock.patch("tools.validate_w3c.css_files", return_value=[]),
                mock.patch("tools.validate_w3c.run_validator", return_value=1) as run_validator,
                redirect_stdout(io.StringIO()),
                redirect_stderr(io.StringIO()),
            ):
                code = main(["--jar", "vnu.jar", "--html", folder])
            self.assertEqual(code, 1)
            run_validator.assert_called_once()

    def test_passes_without_page_or_css(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            mock.patch("tools.validate_w3c.css_files", return_value=[]),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(main(["--jar", "vnu.jar", "--html", folder]), 0)
