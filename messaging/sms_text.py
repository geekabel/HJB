"""SMS version of a message (card T20).

An SMS is cheap in the GSM-7 alphabet (160 characters). One character outside
it, such as "ê" or the typographic apostrophe, switches the whole SMS to UCS-2
(70 characters): the same text then costs two or three times more
(sms/segments.py has the counting).
"""

import re
import unicodedata

from sms.segments import GSM_BASE, GSM_EXTENSION, analyze

# Common French characters outside GSM-7, and their closest GSM-7 form.
REPLACEMENTS = {
    "â": "a", "ê": "e", "î": "i", "ô": "o", "û": "u",
    "ë": "e", "ï": "i", "ÿ": "y", "ç": "c",
    "Â": "A", "Ê": "E", "Î": "I", "Ô": "O", "Û": "U",
    "À": "A", "È": "E", "Ë": "E", "Ï": "I", "Ù": "U", "Ÿ": "Y",
    "œ": "oe", "Œ": "OE",
    # Typographic apostrophes, quotes, dashes, ellipsis, non-breaking spaces.
    "\u2019": "'", "\u2018": "'", "«": '"', "»": '"', "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-", "\u2026": "...",
    "\u00a0": " ", "\u202f": " ",
}  # fmt: skip
GSM = GSM_BASE | GSM_EXTENSION


def to_gsm(text):
    """The text with the French characters outside GSM-7 replaced (ê -> e, « -> ")."""
    # French quotes have spaces inside: « noté » -> "noté".
    text = re.sub(r"«\s*", '"', text or "")
    text = re.sub(r"\s*»", '"', text)
    result = []
    for char in text:
        if char in GSM:
            result.append(char)
        elif char in REPLACEMENTS:
            result.append(REPLACEMENTS[char])
        else:
            # Other accents: the letter without its accent, if that is in GSM-7.
            base = unicodedata.normalize("NFKD", char)[0]
            result.append(base if base in GSM else char)
    return "".join(result)


def sms_text(text):
    """The text as it will leave by SMS: spaces tidied, in GSM-7 when possible."""
    lines = [" ".join(line.split()) for line in (text or "").strip().splitlines()]
    return to_gsm("\n".join(line for line in lines if line))


def words_with(text, char, limit=1):
    """The first words of ``text`` that contain ``char`` (to explain the alert)."""
    words = [word.strip(".,;:!?()") for word in (text or "").split() if char in word]
    return list(dict.fromkeys(words))[:limit]


def cost(text):
    return analyze(text)
