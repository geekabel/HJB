"""Save the pages rendered during tests, to pass them to the W3C validator.

Usage in a test:

    response = self.client.get(url)
    save_page("resident-home", response)

Nothing is written while the ``HTML_CAPTURE_DIR`` environment variable
is not set: normal test runs do not touch the disk.
"""

import os
import re
from pathlib import Path


def save_page(name, response):
    """Write the HTML of ``response`` to ``$HTML_CAPTURE_DIR/<name>.html``."""
    folder = os.environ.get("HTML_CAPTURE_DIR")
    if not folder:
        return None
    file_name = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-") or "page"
    path = Path(folder) / f"{file_name}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    return path
