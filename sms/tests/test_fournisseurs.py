"""Fournisseurs : les appels réseau sont simulés, aucun SMS ne part."""

import io
from unittest import mock

import requests
from django.test import SimpleTestCase
from ovh import exceptions as ovh_exceptions

from sms.fournisseurs.aucun import FournisseurAucun
from sms.fournisseurs.base import ErreurConfiguration, ErreurEnvoi
from sms.fournisseurs.console import FournisseurConsole
from sms.fournisseurs.ovh import FournisseurOvh
from sms.fournisseurs.smsgate import FournisseurSmsGate

NUMERO = "+33612345678"


def reponse_http(code, corps=None):
    reponse = mock.Mock(status_code=code)
    if corps is None:
        reponse.json.side_effect = ValueError("pas de JSON")
    else:
        reponse.json.return_value = corps
    return reponse


class AucunTests(SimpleTestCase):
    def test_refuse_sans_rien_ecrire(self):
        with self.assertRaisesMessage(ErreurConfiguration, "DJANGO_SMS_FOURNISSEUR"):
            FournisseurAucun().envoyer(NUMERO, "Code 123456")


class ConsoleTests(SimpleTestCase):
    def test_ecrit_dans_la_console(self):
        flux = io.StringIO()
        resultat = FournisseurConsole(flux=flux).envoyer(NUMERO, "Bonjour")
        self.assertIn("SMS à +33612345678 (GSM-7, 1 segment)", flux.getvalue())
        self.assertIn("Bonjour", flux.getvalue())
        self.assertEqual(resultat.fournisseur, "console")


class SmsGateTests(SimpleTestCase):
    def fournisseur(self, **options):
        return FournisseurSmsGate(
            **({"url": "http://192.0.2.5:8080/", "identifiant": "u", "mot_de_passe": "p"} | options)
        )

    @mock.patch("sms.fournisseurs.smsgate.requests.post")
    def test_envoi_mode_local(self, post):
        post.return_value = reponse_http(202, {"id": "abc123", "status": "queued"})
        resultat = self.fournisseur(sim="2").envoyer(NUMERO, "Bonjour")
        self.assertEqual((resultat.fournisseur, resultat.identifiant), ("smsgate", "abc123"))
        (url,) = post.call_args.args
        self.assertEqual(url, "http://192.0.2.5:8080/3rdparty/v1/messages")
        kwargs = post.call_args.kwargs
        self.assertEqual(
            kwargs["json"],
            {"textMessage": {"text": "Bonjour"}, "phoneNumbers": [NUMERO], "simNumber": 2},
        )
        self.assertEqual(kwargs["auth"], ("u", "p"))
        self.assertEqual(kwargs["timeout"], 10.0)

    @mock.patch("sms.fournisseurs.smsgate.requests.post")
    def test_envoi_avec_jeton(self, post):
        post.return_value = reponse_http(202, {"id": "x"})
        self.fournisseur(url="https://api.sms-gate.app", jeton="J").envoyer(NUMERO, "Bonjour")
        self.assertEqual(post.call_args.kwargs["headers"], {"Authorization": "Bearer J"})
        self.assertIsNone(post.call_args.kwargs["auth"])

    @mock.patch("sms.fournisseurs.smsgate.requests.post")
    def test_erreurs(self, post):
        cas = [
            (reponse_http(400, {"message": "Invalid phone number format"}), False, "code 400"),
            (reponse_http(401, None), False, "code 401"),
            (reponse_http(429, {"message": "Too many"}), True, "code 429"),
            (reponse_http(503, None), True, "code 503"),
            (reponse_http(500, ["liste"]), True, "code 500"),
        ]
        for reponse, temporaire, extrait in cas:
            with self.subTest(code=reponse.status_code):
                post.return_value = reponse
                with self.assertRaisesMessage(ErreurEnvoi, extrait) as ctx:
                    self.fournisseur().envoyer(NUMERO, "Bonjour")
                self.assertEqual(ctx.exception.temporaire, temporaire)
                self.assertFalse(ctx.exception.incertain)

    @mock.patch("sms.fournisseurs.smsgate.requests.post")
    def test_acceptation_sans_identifiant_est_incertaine(self, post):
        for corps in ({"status": "queued"}, ["liste"], None):
            with self.subTest(corps=corps):
                post.return_value = reponse_http(202, corps)
                with self.assertRaises(ErreurEnvoi) as ctx:
                    self.fournisseur().envoyer(NUMERO, "Bonjour")
                # Le SMS est peut-être parti : pas de nouvel essai automatique.
                self.assertTrue(ctx.exception.incertain)
                self.assertFalse(ctx.exception.temporaire)

    @mock.patch("sms.fournisseurs.smsgate.requests.post")
    def test_delai_de_reponse_depasse(self, post):
        post.side_effect = requests.ReadTimeout("lent")
        with self.assertRaisesMessage(ErreurEnvoi, "pas répondu à temps") as ctx:
            self.fournisseur().envoyer(NUMERO, "Bonjour")
        self.assertTrue(ctx.exception.incertain)
        self.assertFalse(ctx.exception.temporaire)
        post.side_effect = requests.ConnectTimeout("connexion")
        with self.assertRaises(ErreurEnvoi) as ctx:
            self.fournisseur().envoyer(NUMERO, "Bonjour")
        self.assertTrue(ctx.exception.temporaire)

    @mock.patch("sms.fournisseurs.smsgate.requests.post")
    def test_telephone_injoignable(self, post):
        post.side_effect = requests.ConnectionError("refusé")
        with self.assertRaisesMessage(ErreurEnvoi, "injoignable") as ctx:
            self.fournisseur().envoyer(NUMERO, "Bonjour")
        self.assertTrue(ctx.exception.temporaire)

    def test_options_manquantes(self):
        self.assertEqual(
            FournisseurSmsGate().options_manquantes(),
            ["url", "jeton (ou identifiant et mot_de_passe)"],
        )
        self.assertEqual(self.fournisseur().options_manquantes(), [])
        self.assertEqual(FournisseurSmsGate(url="u", jeton="j").options_manquantes(), [])
        self.assertEqual(
            FournisseurSmsGate(url="u", jeton="j", sim="SIM1").options_manquantes(),
            ["sim (1, 2 ou 3)"],
        )


OPTIONS_OVH = {
    "service": "sms-ab12345-1",
    "application_key": "ak",
    "application_secret": "as",
    "consumer_key": "ck",
}


class OvhTests(SimpleTestCase):
    def fournisseur(self, **options):
        return FournisseurOvh(**(OPTIONS_OVH | options))

    @mock.patch("ovh.Client")
    def test_envoi(self, client):
        client.return_value.post.return_value = {
            "totalCreditsRemoved": 1,
            "invalidReceivers": [],
            "ids": [27814656],
            "validReceivers": [NUMERO],
        }
        resultat = self.fournisseur().envoyer(NUMERO, "Bonjour")
        self.assertEqual((resultat.fournisseur, resultat.identifiant), ("ovh", "27814656"))
        client.assert_called_once_with(
            endpoint="ovh-eu",
            application_key="ak",
            application_secret="as",
            consumer_key="ck",
            timeout=10.0,
        )
        (chemin,) = client.return_value.post.call_args.args
        self.assertEqual(chemin, "/sms/sms-ab12345-1/jobs")
        self.assertEqual(
            client.return_value.post.call_args.kwargs,
            {
                "message": "Bonjour",
                "receivers": [NUMERO],
                "charset": "UTF-8",
                "priority": "high",
                "noStopClause": True,
                "senderForResponse": True,
            },
        )

    @mock.patch("ovh.Client")
    def test_expediteur_declare(self, client):
        client.return_value.post.return_value = {"ids": [1], "invalidReceivers": []}
        self.fournisseur(expediteur="HJB").envoyer(NUMERO, "Bonjour")
        corps = client.return_value.post.call_args.kwargs
        self.assertEqual(corps["sender"], "HJB")
        self.assertNotIn("senderForResponse", corps)

    @mock.patch("ovh.Client")
    def test_numero_refuse(self, client):
        client.return_value.post.return_value = {"ids": [], "invalidReceivers": [NUMERO]}
        with self.assertRaisesMessage(ErreurEnvoi, "refusé ce numéro") as ctx:
            self.fournisseur().envoyer(NUMERO, "Bonjour")
        self.assertFalse(ctx.exception.temporaire)

    @mock.patch("ovh.Client")
    def test_erreurs_de_l_api(self, client):
        def reponse(code):
            return mock.Mock(status_code=code, headers={})

        # (erreur, temporaire, incertain)
        cas = [
            (ovh_exceptions.HTTPError("x", requests.ConnectionError("refusé")), True, False),
            (ovh_exceptions.HTTPError("x", requests.ReadTimeout("lent")), False, True),
            (ovh_exceptions.NetworkError(), False, True),
            (ovh_exceptions.InvalidResponse("x"), False, True),
            (ovh_exceptions.InvalidCredential("clé", response=reponse(403)), False, False),
            (ovh_exceptions.BadParametersError("paramètre", response=reponse(400)), False, False),
            (ovh_exceptions.APIError("trop de requêtes", response=reponse(429)), True, False),
            (ovh_exceptions.APIError("panne", response=reponse(500)), True, False),
        ]
        for erreur, temporaire, incertain in cas:
            with self.subTest(erreur=f"{type(erreur).__name__} {erreur.args[:1]}"):
                client.return_value.post.side_effect = erreur
                with self.assertRaises(ErreurEnvoi) as ctx:
                    self.fournisseur().envoyer(NUMERO, "Bonjour")
                self.assertEqual(
                    (ctx.exception.temporaire, ctx.exception.incertain), (temporaire, incertain)
                )

    @mock.patch("ovh.Client")
    def test_reponse_inattendue(self, client):
        client.return_value.post.return_value = ["pas", "un", "objet"]
        with self.assertRaises(ErreurEnvoi) as ctx:
            self.fournisseur().envoyer(NUMERO, "Bonjour")
        self.assertTrue(ctx.exception.incertain)

    def test_region_inconnue(self):
        with self.assertRaises(ErreurConfiguration):
            self.fournisseur(endpoint="ovh-mars").envoyer(NUMERO, "Bonjour")

    def test_options_manquantes(self):
        self.assertEqual(
            FournisseurOvh(service="s").options_manquantes(),
            ["application_key", "application_secret", "consumer_key"],
        )
