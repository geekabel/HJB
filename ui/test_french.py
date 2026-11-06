from django.template import Context, Template
from django.test import SimpleTestCase


class PlurielTests(SimpleTestCase):
    def test_zero_and_one_take_the_singular(self):
        template = Template("{% load french %}{{ n }} message{{ n|pluriel }}")
        for n, text in ((0, "0 message"), (1, "1 message"), (2, "2 messages")):
            self.assertEqual(template.render(Context({"n": n})), text)
        self.assertEqual(
            Template("{% load french %}{{ x|pluriel }}").render(Context({"x": [1, 2]})), "s"
        )
