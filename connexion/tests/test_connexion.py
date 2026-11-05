"""Connexion par clé d'accès, confirmation, déconnexion, sessions (carte T13)."""

import json
import time
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, SESSION_KEY
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.db import SessionStore
from django.http import HttpResponse
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from comptes.roles import Role
from comptes.tests.outils import creer_utilisateur
from connexion import session
from connexion.decorateurs import confirmation_recente
from journal.models import Action, EntreeJournal
from outils.capture_html import enregistrer_page
from residents.depart import enregistrer_depart

from .authentificateur import Authentificateur

DEBUT = reverse("connexion:verification_debut")
FIN = reverse("connexion:verification_fin")


def json_post(client, url, donnees=None):
    corps = json.dumps(donnees) if donnees is not None else ""
    return client.post(url, data=corps, content_type="application/json")


class BaseConnexion(TestCase):
    def setUp(self):
        self.awa = creer_utilisateur("awa", first_name="Awa", last_name="Diallo")
        self.telephone = Authentificateur()
        self.cle = self.telephone.enregistrer(self.awa)

    def se_connecter(self, client=None, *, suite="", **options_reponse):
        client = client or self.client
        options = json_post(client, DEBUT).json()
        url = f"{FIN}?next={suite}" if suite else FIN
        return json_post(client, url, self.telephone.verifier(options, **options_reponse))


class PageConnexionTests(BaseConnexion):
    def test_page(self):
        reponse = self.client.get(reverse("connexion:connexion"))
        enregistrer_page("connexion", reponse)
        self.assertContains(reponse, "Me connecter avec ma clé d'accès</button>")
        self.assertContains(reponse, reverse("activation:saisie"))
        self.assertContains(reponse, "Téléphone perdu ou changé ?")
        self.assertContains(reponse, '"mode": "connexion"')
        self.assertNotContains(reponse, "nav-resident")

    def test_deja_connecte(self):
        self.client.force_login(self.awa)
        self.assertRedirects(self.client.get(reverse("connexion:connexion")), reverse("accueil"))

    def test_page_suivante_conservee(self):
        reponse = self.client.get(reverse("connexion:connexion"), {"next": "/guide/"})
        self.assertContains(reponse, '"suite": "/guide/"')
        reponse = self.client.get(
            reverse("connexion:connexion"), {"next": "https://pirate.example/"}
        )
        self.assertContains(reponse, '"suite": ""')


class ConnexionTests(BaseConnexion):
    def test_options_sans_identifiant(self):
        options = json_post(self.client, DEBUT).json()
        self.assertEqual(options["rpId"], "localhost")
        # Aucune clé listée : rien ne révèle qui a un compte.
        self.assertEqual(options.get("allowCredentials", []), [])
        self.assertEqual(options["userVerification"], "required")

    def test_connexion_resident(self):
        reponse = self.se_connecter()
        self.assertEqual(reponse.status_code, 200, reponse.content)
        self.assertEqual(reponse.json()["redirect_url"], reverse("accueil"))
        session_client = self.client.session
        self.assertEqual(session_client[SESSION_KEY], str(self.awa.pk))
        self.assertEqual(
            session_client[BACKEND_SESSION_KEY], "django_otp_webauthn.backends.WebAuthnBackend"
        )
        self.assertEqual(session_client["otp_device_id"], self.cle.persistent_id)
        self.assertEqual(
            session_client.get_expiry_age(), int(session.DUREE_RESIDENT.total_seconds())
        )
        self.cle.refresh_from_db()
        self.assertIsNotNone(self.cle.last_used_at)
        self.awa.refresh_from_db()
        self.assertIsNotNone(self.awa.last_login)

    def test_connexion_personnel_session_courte(self):
        accueil = creer_utilisateur("lea", Role.ACCUEIL)
        self.telephone.enregistrer(accueil)
        self.assertEqual(self.se_connecter().status_code, 200)
        self.assertEqual(self.client.session.get_expiry_age(), settings.SESSION_COOKIE_AGE)
        # L'accueil va directement à la liste des résidents.
        self.assertRedirects(self.client.get(reverse("accueil")), reverse("residents:liste"))

    def test_page_suivante(self):
        self.assertEqual(self.se_connecter(suite="/guide/").json()["redirect_url"], "/guide/")

    def test_page_suivante_externe_ignoree(self):
        reponse = self.se_connecter(suite="https://pirate.example/")
        self.assertEqual(reponse.json()["redirect_url"], reverse("accueil"))

    def test_nouvelle_cle_de_session(self):
        self.client.get(reverse("connexion:connexion"))
        avant = self.client.session.session_key
        options = json_post(self.client, DEBUT).json()
        json_post(self.client, FIN, self.telephone.verifier(options))
        self.assertNotEqual(self.client.session.session_key, avant)


class ConnexionRefusTests(BaseConnexion):
    def verifier_refus(self, reponse, statut, code):
        self.assertEqual(reponse.status_code, statut, reponse.content)
        self.assertEqual(reponse.json()["code"], code)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_cle_inconnue(self):
        self.cle.delete()  # remplacée à l'accueil, par exemple
        with self.assertLogs("django_otp_webauthn", "ERROR"):
            reponse = self.se_connecter()
        self.verifier_refus(reponse, 404, "credential_not_found")
        self.assertIn("Passez à l'accueil", reponse.json()["detail"])

    def test_compte_desactive(self):
        self.awa.is_active = False
        self.awa.save()
        reponse = self.se_connecter()
        self.verifier_refus(reponse, 403, "user_disabled")
        self.assertEqual(reponse.json()["detail"], "Ce compte est désactivé. Passez à l'accueil.")

    def test_verification_de_l_utilisateur_obligatoire(self):
        # Sans Face ID, empreinte ni code : refusé, même avec la bonne clé.
        with self.assertLogs("django_otp_webauthn", "ERROR"):
            reponse = self.se_connecter(verification=False)
        self.verifier_refus(reponse, 422, "invalid_authentication_response")

    def test_mauvaise_origine(self):
        with self.assertLogs("django_otp_webauthn", "ERROR"):
            reponse = self.se_connecter(origine="https://pirate.example")
        self.verifier_refus(reponse, 422, "invalid_authentication_response")

    def test_pas_de_rejeu(self):
        options = json_post(self.client, DEBUT).json()
        reponse_cle = self.telephone.verifier(options)
        self.assertEqual(json_post(self.client, FIN, reponse_cle).status_code, 200)
        autre = Client()
        json_post(autre, DEBUT)  # autre défi
        with self.assertLogs("django_otp_webauthn", "ERROR"):
            reponse = json_post(autre, FIN, reponse_cle)
        self.assertEqual(reponse.status_code, 422)
        # Et sans début, pas d'état du tout.
        self.assertEqual(json_post(Client(), FIN, reponse_cle).json()["code"], "invalid_state")

    def test_sans_debut(self):
        self.verifier_refus(json_post(self.client, FIN, {"id": "x"}), 400, "invalid_state")

    def test_csrf_obligatoire(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(json_post(client, DEBUT).status_code, 403)


class ConfirmationTests(BaseConnexion):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.se_connecter().status_code, 200)

    def test_page(self):
        reponse = self.client.get(reverse("connexion:confirmer"), {"next": "/guide/"})
        enregistrer_page("connexion-confirmer", reponse)
        self.assertContains(reponse, "Confirmer avec ma clé d'accès</button>")
        self.assertContains(reponse, '"mode": "confirmation"')
        self.assertContains(reponse, '"suite": "/guide/"')

    def test_page_sans_cle(self):
        self.cle.delete()
        reponse = self.client.get(reverse("connexion:confirmer"))
        self.assertContains(reponse, "pas encore de clé d'accès")
        self.assertNotContains(reponse, "cle-acces.js")

    def test_anonyme(self):
        url = reverse("connexion:confirmer")
        self.assertRedirects(Client().get(url), f"{reverse('connexion:connexion')}?next={url}")

    def test_confirmation(self):
        # Il y a 11 minutes : plus récent.
        donnees = self.client.session
        donnees[session.CLE_CONFIRMEE] = time.time() - 11 * 60
        donnees.save()
        options = json_post(self.client, DEBUT).json()
        # Personne connectée : ses clés sont listées, et la vérification reste obligatoire.
        self.assertEqual(len(options["allowCredentials"]), 1)
        self.assertEqual(options["userVerification"], "required")
        reponse = json_post(self.client, f"{FIN}?next=/guide/", self.telephone.verifier(options))
        self.assertEqual(reponse.json()["redirect_url"], "/guide/")
        self.assertLess(time.time() - self.client.session[session.CLE_CONFIRMEE], 5)

    def test_cle_d_un_autre_compte(self):
        intrus = Authentificateur()
        intrus.enregistrer(creer_utilisateur("ben"))
        options = json_post(self.client, DEBUT).json()
        with self.assertLogs("django_otp_webauthn", "ERROR"):
            reponse = json_post(self.client, FIN, intrus.verifier(options))
        self.assertEqual(reponse.status_code, 403)
        self.assertEqual(reponse.json()["code"], "credential_user_mismatch")
        self.assertEqual(self.client.session[SESSION_KEY], str(self.awa.pk))


class DecorateurTests(TestCase):
    def setUp(self):
        self.awa = creer_utilisateur("awa")
        self.vue = confirmation_recente(lambda request: HttpResponse("secret"))

    def requete(self, utilisateur, confirmee_il_y_a=None):
        requete = RequestFactory().get("/wifi/?onglet=1")
        requete.user = utilisateur
        requete.session = SessionStore()
        if confirmee_il_y_a is not None:
            requete.session[session.CLE_CONFIRMEE] = time.time() - confirmee_il_y_a
        return requete

    def test_anonyme(self):
        reponse = self.vue(self.requete(AnonymousUser()))
        self.assertEqual(reponse.status_code, 302)
        self.assertTrue(reponse["Location"].startswith(reverse("connexion:connexion")))

    def test_sans_confirmation(self):
        reponse = self.vue(self.requete(self.awa))
        self.assertEqual(
            reponse["Location"], f"{reverse('connexion:confirmer')}?next=%2Fwifi%2F%3Fonglet%3D1"
        )

    def test_confirmation_trop_ancienne(self):
        reponse = self.vue(self.requete(self.awa, confirmee_il_y_a=11 * 60))
        self.assertEqual(reponse.status_code, 302)

    def test_confirmation_recente(self):
        self.assertEqual(self.vue(self.requete(self.awa, confirmee_il_y_a=60)).content, b"secret")

    def test_heure_dans_le_futur_refusee(self):
        self.assertEqual(self.vue(self.requete(self.awa, confirmee_il_y_a=-60)).status_code, 302)


class DeconnexionEtAccueilTests(BaseConnexion):
    def test_deconnexion(self):
        self.se_connecter()
        self.assertEqual(self.client.get(reverse("connexion:deconnexion")).status_code, 405)
        reponse = self.client.post(reverse("connexion:deconnexion"), follow=True)
        self.assertRedirects(reponse, reverse("connexion:connexion"))
        self.assertContains(reponse, "Vous êtes déconnecté.")
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_accueil_anonyme(self):
        self.assertRedirects(
            self.client.get(reverse("accueil")), f"{reverse('connexion:connexion')}?next=/"
        )

    def test_accueil_resident(self):
        self.se_connecter()
        reponse = self.client.get(reverse("accueil"))
        self.assertContains(reponse, "Bonjour Awa")
        self.assertContains(reponse, "Créée le <time")
        self.assertContains(reponse, "utilisée le <time")


class DepartTests(BaseConnexion):
    def test_le_depart_supprime_les_cles(self):
        self.se_connecter()
        enregistrer_depart(self.awa, timezone.localdate())
        self.assertFalse(self.awa.webauthncredential_set.exists())
        entree = EntreeJournal.objects.get(action=Action.DEPART_RESIDENT)
        self.assertEqual(entree.details["cles_retirees"], 1)
        self.assertIn("1 clé d'accès supprimée.", entree.resume())
        # La session est fermée, et la clé ne permet plus de se connecter.
        self.assertRedirects(
            self.client.get(reverse("accueil")), f"{reverse('connexion:connexion')}?next=/"
        )
        with self.assertLogs("django_otp_webauthn", "ERROR"):
            self.assertEqual(self.se_connecter(client=Client()).status_code, 404)


class AdministrationTests(TestCase):
    def test_cles_visibles_et_non_modifiables(self):
        admin = creer_utilisateur("admin", Role.ADMIN, is_staff=True, is_superuser=True)
        cle = Authentificateur().enregistrer(creer_utilisateur("awa"))
        self.client.force_login(admin)
        url = reverse("admin:django_otp_webauthn_webauthncredential_changelist")
        self.assertEqual(self.client.get(url).status_code, 200)
        url = reverse("admin:django_otp_webauthn_webauthncredential_change", args=[cle.pk])
        reponse = self.client.post(url, {"name": "autre", "confirmed": ""})
        self.assertEqual(reponse.status_code, 403)
        cle.refresh_from_db()
        self.assertTrue(cle.confirmed)


class RevueSessionsTests(BaseConnexion):
    """Cas trouvés par la relecture indépendante (5 nov.)."""

    def test_duree_sans_activite(self):
        """La date de fin repart à chaque requête (SESSION_SAVE_EVERY_REQUEST)."""
        from django.contrib.sessions.models import Session

        self.se_connecter()
        cle = self.client.session.session_key
        Session.objects.filter(pk=cle).update(expire_date=timezone.now() + timedelta(days=1))
        self.client.get(reverse("accueil"))
        reste = Session.objects.get(pk=cle).expire_date - timezone.now()
        self.assertGreater(reste, session.DUREE_RESIDENT - timedelta(minutes=1))

    def test_supprimer_la_cle_dans_l_administration_ferme_les_sessions(self):
        self.se_connecter()
        admin = creer_utilisateur("admin", Role.ADMIN, is_staff=True, is_superuser=True)
        equipe = Client()
        equipe.force_login(admin)
        url = reverse("admin:django_otp_webauthn_webauthncredential_delete", args=[self.cle.pk])
        with self.captureOnCommitCallbacks(execute=True):
            reponse = equipe.post(url, {"post": "yes"})
        self.assertEqual(reponse.status_code, 302)
        self.assertRedirects(
            self.client.get(reverse("accueil")), f"{reverse('connexion:connexion')}?next=/"
        )
        self.assertEqual(equipe.get(reverse("admin:index")).status_code, 200)

    def test_csrf_sur_la_fin(self):
        client = Client(enforce_csrf_checks=True)
        reponse = json_post(client, FIN, {})
        self.assertEqual(reponse.status_code, 403)
        self.assertNotEqual(reponse["Content-Type"], "application/json")
