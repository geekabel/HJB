"""French typography in templates (design card D4).

``pluriel``: the French plural mark. Unlike Django's ``pluralize``, 0 takes
the singular: « 0 notification », « 1 message », « 2 messages ».
Docs: https://docs.djangoproject.com/en/6.1/howto/custom-template-tags/#writing-custom-template-filters
"""

from django import template

register = template.Library()


@register.filter(is_safe=False)
def pluriel(value, suffix="s"):
    """``suffix`` when ``value`` (a number, or a list) is more than 1, else ""."""
    try:
        count = len(value) if hasattr(value, "__len__") and not isinstance(value, str) else value
        return suffix if abs(float(count)) > 1 else ""
    except (TypeError, ValueError):
        return ""
