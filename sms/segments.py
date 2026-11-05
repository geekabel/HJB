"""Character and segment counter for an SMS.

An SMS is encoded in GSM-7 if all its characters are in the GSM alphabet
(3GPP TS 23.038 standard). Otherwise it is encoded in UCS-2.

| Encoding | Single SMS | Long message, per segment |
|---|---|---|
| GSM-7 | 160 characters | 153 characters |
| UCS-2 | 70 characters | 67 characters |

Characters from the GSM extension table (€, [, ], {, }, ~, ^, |, \\) count
double. In UCS-2, an emoji counts double (UTF-16 surrogate pair).
A segment never splits a double character in two.

Watch out for French: "é è à ù" are in GSM-7, but "ê â î ô û ç" and the
typographic apostrophe (U+2019, the one word processors use) switch the
whole message to UCS-2.
"""

from dataclasses import dataclass

# GSM 03.38 base table (the escape character 0x1B is excluded).
GSM_BASE = frozenset(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
# Extension table: each character is written with the escape, so it counts double.
GSM_EXTENSION = frozenset("\f^{}\\[~]|€")

LIMITS = {
    "GSM-7": (160, 153),
    "UCS-2": (70, 67),
}


@dataclass(frozen=True)
class SmsInfo:
    encoding: str  # "GSM-7" or "UCS-2"
    units: int  # septets (GSM-7) or UTF-16 units (UCS-2)
    segments: int
    remaining: int  # units still free in the last segment
    non_gsm: tuple  # characters that force UCS-2, without duplicates, in order


def _weight(char, encoding):
    if encoding == "GSM-7":
        return 2 if char in GSM_EXTENSION else 1
    return 2 if ord(char) > 0xFFFF else 1


def analyze(text):
    """Return the encoding, the size and the number of segments of ``text``."""
    non_gsm = tuple(dict.fromkeys(c for c in text if c not in GSM_BASE | GSM_EXTENSION))
    encoding = "UCS-2" if non_gsm else "GSM-7"
    single, per_segment = LIMITS[encoding]
    weights = [_weight(c, encoding) for c in text]
    units = sum(weights)

    if units <= single:
        return SmsInfo(encoding, units, 1 if text else 0, single - units, non_gsm)

    # Long message: fill segment by segment, without splitting a double character.
    segments, filled = 1, 0
    for w in weights:
        if filled + w > per_segment:
            segments += 1
            filled = 0
        filled += w
    return SmsInfo(encoding, units, segments, per_segment - filled, non_gsm)
