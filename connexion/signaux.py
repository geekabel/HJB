from django_otp_webauthn.utils import get_credential_model


def retirer_cles_au_depart(sender, resident, **kwargs):
    """Appelé dans la transaction du départ. Le nombre de clés va au journal."""
    cles = get_credential_model().objects.filter(user=resident)
    nombre = cles.count()
    cles.delete()
    return {"cles_retirees": nombre}
