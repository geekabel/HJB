from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """Utilisateur de l'application : résident ou membre de l'équipe.

    Ce modèle existe dès la première migration, comme le recommande la
    documentation de Django :
    https://docs.djangoproject.com/en/6.1/topics/auth/customizing/#using-a-custom-user-model-when-starting-a-project

    Les champs propres au projet (rôle, téléphone, modérateur) arrivent
    avec la carte T04.
    """

    class Meta(AbstractUser.Meta):
        verbose_name = "utilisateur"
        verbose_name_plural = "utilisateurs"
