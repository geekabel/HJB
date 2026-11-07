"""French public holidays: no booking on these days (card T27).

Fixed days, plus the days that follow Easter (Monday, Ascension, Whit Monday).
Easter Sunday: the "anonymous Gregorian" computation (Meeus, Astronomical
Algorithms, chapter 8), valid for every year of the Gregorian calendar.
"""

from datetime import date, timedelta
from functools import cache

FIXED = (
    (1, 1, "Jour de l'an"),
    (5, 1, "Fête du travail"),
    (5, 8, "Victoire 1945"),
    (7, 14, "Fête nationale"),
    (8, 15, "Assomption"),
    (11, 1, "Toussaint"),
    (11, 11, "Armistice 1918"),
    (12, 25, "Noël"),
)


def easter(year):
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741 (name of the algorithm)
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


@cache
def holidays(year):
    """{date: name} of the French public holidays of ``year``."""
    found = {date(year, month, day): name for month, day, name in FIXED}
    sunday = easter(year)
    found[sunday + timedelta(days=1)] = "Lundi de Pâques"
    found[sunday + timedelta(days=39)] = "Ascension"
    found[sunday + timedelta(days=50)] = "Lundi de Pentecôte"
    return found


def holiday_name(day):
    return holidays(day.year).get(day, "")
