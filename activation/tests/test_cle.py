"""Activation, étape 3 : création de la clé d'accès (carte T13)."""

import json
import re
from datetime import timedelta

from django.contrib.auth import SESSION_KEY
from django.db.models import F
from django.test import Client, TestCase
from django.urls import reverse
from django_otp_webauthn.utils import get_credential_model

from activation import parcours
from comptes.activation import generer_code
from comptes.models import EtatCompte, VerificationTelephone
from comptes.tests.outils import creer_utilisateur
from connexion.session import DUREE_RESIDENT
from connexion.tests.authentificateur import Authentificateur
from journal.models import Action, EntreeJournal
from outils.capture_html import enregistrer_page
from sms.fournisseurs import memoire

Cle = get_credential_model()


def activer_jusqu_au_telephone(client, personne):
    """Étapes 1 et 2 : code de l'accueil, puis code SMS."""
    client.post(reverse("activation:saisie"), {"code": generer_code(personne)})
    client.post(reverse("activation:telephone"), {"action": "envoyer"})
    code = re.search(r"\b(\d{6})\b", memoire.boite[-1].texte).group(1)
    client.post(reverse("activation:telephone"), {"action": "verifier", "code": code})


def json_post(client, url, donnees=None):
    return client.post(
        url,
        data=json.dumps(donnees) if donnees is not None else "",
        content_type="application/json",
    )


def creer_cle(client, authentificateur):
    """Étape 3 complète. Renvoie la réponse de fin."""
    options = json_post(client, reverse("activation:cle_debut")).json()
    return json_post(client, reverse("activation:cle_fin"), authentificateur.creer(options))


class BaseCle(TestCase):
    def setUp(self):
        memoire.boite.clear()
        self.awa = creer_utilisateur(
            "awa", first_name="Awa", last_name="Diallo", telephone="+33612345647"
        )
        self.telephone = Authentificateur()
        activer_jusqu_au_telephone(self.client, self.awa)


class EtapeCleTests(BaseCle):
    def test_page(self):
        reponse = self.client.get(reverse("activation:cle"))
        enregistrer_page("activation-cle", reponse)
        self.assertContains(reponse, 'aria-current="step">3. Clé d\'accès')
        # Texte écrit dans le gabarit : pas échappé.
        self.assertContains(reponse, "Créer ma clé d'accès</button>")
        self.assertContains(reponse, 'id="cle-acces-config"')
        self.assertContains(reponse, "interface/js/cle-acces.js")
        self.assertContains(reponse, "csrfmiddlewaretoken")
        # Le bouton reste caché tant que le script n'a pas vérifié le navigateur.
        self.assertContains(reponse, "data-cle-acces-bouton hidden")

    def test_options(self):
        options = json_post(self.client, reverse("activation:cle_debut")).json()
        self.assertEqual(options["rp"], {"name": "Habitat Jeunes Belfort", "id": "localhost"})
        self.assertEqual(options["user"]["displayName"], "Awa Diallo")
        # Clé « découvrable » obligatoire : la connexion se fait sans identifiant.
        self.assertEqual(options["authenticatorSelection"]["residentKey"], "required")
        self.assertEqual(options["excludeCredentials"], [])

    def test_creation_complete(self):
        reponse = creer_cle(self.client, self.telephone)
        self.assertEqual(reponse.status_code, 200, reponse.content)
        self.assertEqual(reponse.json()["redirect_url"], reverse("accueil"))

        cle = Cle.objects.get()
        self.assertEqual(cle.user, self.awa)
        self.assertTrue(cle.discoverable)
        self.awa.refresh_from_db()
        self.assertEqual(self.awa.etat_compte, EtatCompte.ACTIVE)

        session = self.client.session
        self.assertEqual(session[SESSION_KEY], str(self.awa.pk))
        self.assertEqual(session["otp_device_id"], cle.persistent_id)
        self.assertNotIn(parcours.CLE, session)
        self.assertEqual(session.get_expiry_age(), int(DUREE_RESIDENT.total_seconds()))

        entree = EntreeJournal.objects.get(action=Action.CLE_ACCES_CREEE)
        self.assertEqual(entree.resume(), "Première clé d'accès.")

        reponse = self.client.get(reverse("accueil"))
        enregistrer_page("accueil-resident", reponse)
        self.assertContains(reponse, "Bonjour Awa")
        self.assertContains(reponse, "Me déconnecter")

    def test_get_refuse(self):
        self.assertEqual(self.client.get(reverse("activation:cle_debut")).status_code, 405)
        self.assertEqual(self.client.get(reverse("activation:cle_fin")).status_code, 405)

    def test_csrf_obligatoire(self):
        # Même session (téléphone vérifié), mais sans jeton CSRF : refusé.
        client = Client(enforce_csrf_checks=True)
        client.cookies = self.client.cookies
        self.assertEqual(json_post(client, reverse("activation:cle_debut")).status_code, 403)


class EtapeCleRefusTests(BaseCle):
    def test_sans_parcours(self):
        client = Client()
        reponse = json_post(client, reverse("activation:cle_debut"))
        self.assertEqual(reponse.status_code, 403)
        self.assertEqual(reponse.json()["code"], "parcours")
        self.assertIn("Recommencez", reponse.json()["detail"])

    def test_sans_telephone_verifie(self):
        client = Client()
        client.post(reverse("activation:saisie"), {"code": generer_code(self.awa)})
        self.assertEqual(json_post(client, reverse("activation:cle_debut")).status_code, 403)
        self.assertRedirects(client.get(reverse("activation:cle")), reverse("activation:telephone"))

    def test_fin_sans_debut(self):
        reponse = json_post(self.client, reverse("activation:cle_fin"), {"id": "x"})
        self.assertEqual(reponse.status_code, 400)
        self.assertEqual(reponse.json()["code"], "invalid_state")

    def test_json_illisible(self):
        json_post(self.client, reverse("activation:cle_debut"))
        reponse = self.client.post(
            reverse("activation:cle_fin"), data="{pas du json", content_type="application/json"
        )
        self.assertEqual(reponse.status_code, 400)
        self.assertEqual(reponse.json()["code"], "malformed_request")

    def test_mauvaise_origine_puis_pas_de_rejeu(self):
        options = json_post(self.client, reverse("activation:cle_debut")).json()
        piege = self.telephone.creer(options, origine="https://pirate.example")
        with self.assertLogs("django_otp_webauthn", "ERROR"):
            reponse = json_post(self.client, reverse("activation:cle_fin"), piege)
        self.assertEqual(reponse.status_code, 422)
        self.assertEqual(
            reponse.json()["detail"], "La clé d'accès n'a pas pu être vérifiée. Réessayez."
        )
        # L'état a servi une fois : même une bonne réponse au même défi est refusée.
        bonne = self.telephone.creer(options)
        reponse = json_post(self.client, reverse("activation:cle_fin"), bonne)
        self.assertEqual(reponse.json()["code"], "invalid_state")
        self.assertFalse(Cle.objects.exists())
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_numero_change_avant_la_fin(self):
        options = json_post(self.client, reverse("activation:cle_debut")).json()
        self.awa.telephone = "+33781234588"
        self.awa.save()
        reponse = json_post(
            self.client, reverse("activation:cle_fin"), self.telephone.creer(options)
        )
        self.assertEqual(reponse.status_code, 403)
        self.assertFalse(Cle.objects.exists())

    def test_nouveau_code_pendant_la_creation(self):
        options = json_post(self.client, reverse("activation:cle_debut")).json()
        generer_code(self.awa)  # l'accueil remet un autre code : celui-ci ne compte plus
        reponse = json_post(
            self.client, reverse("activation:cle_fin"), self.telephone.creer(options)
        )
        self.assertEqual(reponse.status_code, 403)
        self.assertFalse(Cle.objects.exists())


class RecuperationTests(BaseCle):
    """Téléphone perdu : nouveau code à l'accueil, nouvelle clé, l'ancienne ne sert plus."""

    def test_nouvelle_cle_remplace_l_ancienne(self):
        creer_cle(self.client, self.telephone)
        ancienne = Cle.objects.get()
        ancien_telephone = self.client  # session encore ouverte sur l'ancien téléphone

        # Plus d'une minute après le premier SMS (délai avant un nouvel envoi).
        VerificationTelephone.objects.update(cree_le=F("cree_le") - timedelta(minutes=2))
        nouveau_telephone = Client()
        activer_jusqu_au_telephone(nouveau_telephone, self.awa)
        options = json_post(nouveau_telephone, reverse("activation:cle_debut")).json()
        # Les clés existantes ne sont pas exclues : le même appareil peut la recréer.
        self.assertEqual(options["excludeCredentials"], [])
        reponse = json_post(
            nouveau_telephone, reverse("activation:cle_fin"), Authentificateur().creer(options)
        )
        self.assertEqual(reponse.status_code, 200)

        self.assertFalse(Cle.objects.filter(pk=ancienne.pk).exists())
        self.assertEqual(Cle.objects.filter(user=self.awa).count(), 1)
        # L'ancienne session est fermée, la nouvelle est ouverte.
        self.assertRedirects(
            ancien_telephone.get(reverse("accueil")),
            f"{reverse('connexion:connexion')}?next=/",
        )
        self.assertEqual(nouveau_telephone.get(reverse("accueil")).status_code, 200)
        entree = EntreeJournal.objects.filter(action=Action.CLE_ACCES_CREEE).latest("pk")
        self.assertEqual(entree.resume(), "Remplace 1 ancienne clé, désormais inutilisable.")
