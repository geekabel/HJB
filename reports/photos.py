"""Photos of a report (card T30): smaller, and without their metadata.

A phone photo carries EXIF data: the GPS position where it was taken, the
phone model, the date. None of it is kept. The photo is decoded with Pillow,
turned the right way up (EXIF orientation, ImageOps.exif_transpose), made
smaller, and encoded again as a new JPEG. Pillow writes EXIF data only when
``exif=`` is given to ``save()``: the new file has none.

Only JPEG, PNG and WebP are opened (iPhones send JPEG to a web form). An image
with too many pixels is refused before it is decoded (decompression bomb).
Pillow docs: https://pillow.readthedocs.io/en/stable/reference/ImageOps.html
"""

from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_PHOTOS = 3
MAX_BYTES = 10 * 1024 * 1024  # per photo, as sent by the phone
MAX_PIXELS = 50_000_000  # a 50 megapixel photo; more is refused unread
LONGEST_SIDE = 1600
FORMATS = ["JPEG", "PNG", "WEBP"]
QUALITY = 82


class PhotoRefused(ValueError):
    """The file is not a photo we can read."""


def clean(uploaded):
    """Return (ContentFile, width, height) of the new JPEG. Raise PhotoRefused."""
    if uploaded.size > MAX_BYTES:
        raise PhotoRefused("Photo trop lourde : 10 Mo au plus.")
    try:
        with Image.open(uploaded, formats=FORMATS) as image:
            width, height = image.size
            if width * height > MAX_PIXELS:
                raise PhotoRefused("Photo trop grande.")
            image.load()
            image = ImageOps.exif_transpose(image)
            image.thumbnail((LONGEST_SIDE, LONGEST_SIDE))
            if image.mode not in ("RGB", "L"):
                # Transparency (PNG, WebP) on white, then RGB for JPEG
                background = Image.new("RGB", image.size, "white")
                rgba = image.convert("RGBA")
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            out = BytesIO()
            image.save(out, format="JPEG", quality=QUALITY, optimize=True)
            return ContentFile(out.getvalue()), image.width, image.height
    except PhotoRefused:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise PhotoRefused("Ce fichier n'est pas une photo lisible (JPEG, PNG ou WebP).") from error
