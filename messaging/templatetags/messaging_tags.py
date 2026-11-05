from django import template

register = template.Library()


@register.filter
def get_item(mapping, key):
    """{{ answers|get_item:user_id }}: a value of a dict in a template."""
    return mapping.get(key) if mapping else None
