"""Compteur de caractères et de segments d'un SMS.

Un SMS est codé en GSM-7 si tous ses caractères sont dans l'alphabet GSM
(norme 3GPP TS 23.038), sinon en UCS-2.

| Codage | Un seul SMS | Message long, par segment |
|---|---|---|
| GSM-7 | 160 caractères | 153 caractères |
| UCS-2 | 70 caractères | 67 caractères |

Les caractères de la table d'extension GSM (€, [, ], {, }, ~, ^, |, \\) comptent
double. En UCS-2, un emoji compte double (paire de substitution UTF-16).
Un segment ne coupe jamais un caractère double en deux.

Attention au français : « é è à ù » sont en GSM-7, mais « ê â î ô û ç » et
l'apostrophe typographique (U+2019, celle des traitements de texte) font
passer tout le message en UCS-2.
"""

from dataclasses import dataclass

# Table de base GSM 03.38 (le caractère d'échappement 0x1B est exclu).
GSM_BASE = frozenset(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
# Table d'extension : chaque caractère s'écrit avec l'échappement, donc compte double.
GSM_EXTENSION = frozenset("\f^{}\\[~]|€")

LIMITES = {
    "GSM-7": (160, 153),
    "UCS-2": (70, 67),
}


@dataclass(frozen=True)
class InfoSms:
    encodage: str  # "GSM-7" ou "UCS-2"
    unites: int  # septets (GSM-7) ou unités UTF-16 (UCS-2)
    segments: int
    restant: int  # unités encore libres dans le dernier segment
    hors_gsm: tuple  # caractères qui imposent l'UCS-2, sans doublon, dans l'ordre


def _poids(caractere, encodage):
    if encodage == "GSM-7":
        return 2 if caractere in GSM_EXTENSION else 1
    return 2 if ord(caractere) > 0xFFFF else 1


def analyser(texte):
    """Renvoie l'encodage, la taille et le nombre de segments de ``texte``."""
    hors_gsm = tuple(dict.fromkeys(c for c in texte if c not in GSM_BASE | GSM_EXTENSION))
    encodage = "UCS-2" if hors_gsm else "GSM-7"
    seul, par_segment = LIMITES[encodage]
    poids = [_poids(c, encodage) for c in texte]
    unites = sum(poids)

    if unites <= seul:
        return InfoSms(encodage, unites, 1 if texte else 0, seul - unites, hors_gsm)

    # Message long : remplissage segment par segment, sans couper un caractère double.
    segments, rempli = 1, 0
    for p in poids:
        if rempli + p > par_segment:
            segments += 1
            rempli = 0
        rempli += p
    return InfoSms(encodage, unites, segments, par_segment - rempli, hors_gsm)
