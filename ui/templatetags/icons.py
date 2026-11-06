"""Inline SVG icons, line style, with no dependency.

    {% load icons %}
    {% icon "home" %}
    {% icon "bell" label="Notifications" %}

Without ``label``, the icon is decorative (``aria-hidden``): the nearby
text carries the meaning. With ``label``, it becomes a named image.

The markup comes only from the dictionary below, written in the
code; the values passed by templates are escaped by
``format_html`` (Django docs: "How to create custom template tags").
"""

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()

ICONS = {
    "home": '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
    "message": '<path d="M4 5h16v11H8l-4 4z"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "calendar": '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    "wifi": (
        '<path d="M5 12.55a11 11 0 0 1 14.08 0M1.42 9a16 16 0 0 1 21.16 0'
        'M8.53 16.11a6 6 0 0 1 6.95 0"/><circle cx="12" cy="20" r="1"/>'
    ),
    "person": '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    "bell": '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 0 1-3.46 0"/>',
    "alert": (
        '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3'
        'L13.71 3.86a2 2 0 0 0-3.42 0zM12 9v4M12 17h.01"/>'
    ),
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "copy": (
        '<rect x="9" y="9" width="12" height="12" rx="2"/>'
        '<path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/>'
    ),
    "eye": '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "lock": '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    "back": '<path d="M19 12H5M12 19l-7-7 7-7"/>',
    "import": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/>',
    "send": '<path d="M22 2 11 13M22 2l-7 20-4-9-9-4z"/>',
    "door": '<path d="M5 21V4a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v17M3 21h18M15 12h.01"/>',
    "megaphone": '<path d="M3 11v2a1 1 0 0 0 1 1h3l6 4V6L7 10H4a1 1 0 0 0-1 1zM17 9a3 3 0 0 1 0 6"/>',
    "vote": '<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
    "table": (
        '<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/>'
        '<rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/>'
    ),
    "tool": (
        '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 '
        '7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94z"/>'
    ),
    "group": (
        '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
        '<path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>'
    ),
    # Navigation (design card D1).
    "chevron": '<path d="m9 6 6 6-6 6"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>',
    "logout": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
    "menu": '<path d="M4 6h16M4 12h16M4 18h16"/>',
    "close": '<path d="M18 6 6 18M6 6l12 12"/>',
}

# The three roofs of the logo, in color (not line style).
ROOFS = (
    '<svg class="{}" viewBox="0 0 30 20" width="30" height="20" role="img" aria-label="{}">'
    '<path d="M1 12 6 5l5 7v7H1z" fill="#8BC34A"/>'
    '<path d="M9 9 15 1l6 8v10H9z" fill="#03A9F4"/>'
    '<path d="M19 12l5-7 5 7v7H19z" fill="#FFC107"/></svg>'
)


@register.simple_tag
def icon(name, label="", css_class=""):
    """Render the icon ``name``. Raise KeyError if it does not exist (template error)."""
    paths = mark_safe(ICONS[name])
    if label:
        return format_html(
            '<svg class="{}" viewBox="0 0 24 24" width="24" height="24" fill="none" '
            'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
            'stroke-linejoin="round" role="img" aria-label="{}">{}</svg>',
            css_class,
            label,
            paths,
        )
    return format_html(
        '<svg class="{}" viewBox="0 0 24 24" width="24" height="24" fill="none" '
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true">{}</svg>',
        css_class,
        paths,
    )


@register.simple_tag
def roofs(label="Habitat Jeunes Belfort", css_class=""):
    """The three roofs of the logo. ``label=""``: decorative, next to the written name."""
    if not label:
        return format_html(
            ROOFS.replace(' role="img" aria-label="{}"', ' aria-hidden="true"'), css_class
        )
    return format_html(ROOFS, css_class, label)
