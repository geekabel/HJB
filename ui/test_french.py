from datetime import datetime, timedelta

from django.template import Context, Template
from django.test import SimpleTestCase
from django.utils import timezone

from ui.templatetags.french import jour


class PlurielTests(SimpleTestCase):
    def test_zero_and_one_take_the_singular(self):
        template = Template("{% load french %}{{ n }} message{{ n|pluriel }}")
        for n, text in ((0, "0 message"), (1, "1 message"), (2, "2 messages")):
            self.assertEqual(template.render(Context({"n": n})), text)
        self.assertEqual(
            Template("{% load french %}{{ x|pluriel }}").render(Context({"x": [1, 2]})), "s"
        )


class QuotesTests(SimpleTestCase):
    """French quotes keep their words on the same line (design card D4)."""

    def test_no_plain_space_inside_quotes(self):
        from pathlib import Path

        from django.conf import settings

        root = Path(settings.BASE_DIR)
        skipped = {".venv", "build", "migrations", "management", "tests", "node_modules"}
        found = []
        for path in [*root.rglob("*.html"), *root.rglob("*.py")]:
            parts = set(path.relative_to(root).parts)
            if parts & skipped or path.name.startswith("test_") or path.name == "checks.py":
                continue
            for number, line in enumerate(path.read_text().splitlines(), 1):
                if line.strip().startswith(("#", '"""')):
                    continue  # comments and docstrings are not shown
                if "« " in line or " »" in line:
                    found.append(f"{path.relative_to(root)}:{number}")
        self.assertEqual(found, [], "Use a non-breaking space inside « »")


class JourTests(SimpleTestCase):
    """The day above a group of direct messages (design card D5)."""

    def test_today_yesterday_and_other_days(self):
        now = timezone.now()
        self.assertEqual(jour(now), "Aujourd'hui")
        noon = datetime.combine(timezone.localdate() - timedelta(days=1), datetime.min.time())
        self.assertEqual(jour(timezone.make_aware(noon.replace(hour=12))), "Hier")
        self.assertEqual(jour(None), "")
        year = timezone.localdate().year - 1
        self.assertEqual(
            jour(timezone.make_aware(datetime(year, 3, 5, 10))),
            "{} 5 mars {}".format(
                ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"][
                    datetime(year, 3, 5).weekday()
                ],
                year,
            ),
        )
