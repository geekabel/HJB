"""Recipients and composer (card T20)."""

from datetime import date
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user
from housing.models import Floor, Room, Stay
from push.models import PushSubscription
from push.services import SendResult
from tools.html_capture import save_page

from ..audience import audience
from ..models import Campaign, MessageTemplate, MessageType
from ..services import find_target

ARRIVAL = date(2026, 9, 1)


class ComposerTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.nadia = make_user("nadia", Role.FRONT_DESK, first_name="Nadia", phone="+33612345678")
        cls.f1 = Floor.objects.create(number=1)
        cls.f3 = Floor.objects.create(number=3)
        cls.r118 = Room.objects.create(number="118", floor=cls.f1)
        cls.r312 = Room.objects.create(number="312", floor=cls.f3)
        cls.r304 = Room.objects.create(number="304", floor=cls.f3)
        cls.ines = make_user("ines", first_name="Inès", last_name="Martin")
        cls.yanis = make_user("yanis", first_name="Yanis", last_name="Traoré", phone="+33611111111")
        cls.awa = make_user("awa", first_name="Awa", last_name="Koné")
        cls.lucas = make_user("lucas", first_name="Lucas", last_name="Petit", phone="+33622222222")
        Stay.objects.create(resident=cls.ines, room=cls.r312, arrival=ARRIVAL)
        Stay.objects.create(resident=cls.yanis, room=cls.r304, arrival=ARRIVAL)
        Stay.objects.create(resident=cls.awa, room=cls.r118, arrival=ARRIVAL)
        PushSubscription.objects.create(
            user=cls.ines, endpoint="https://web.push.apple.com/x", p256dh="x", auth="y"
        )

    def setUp(self):
        cache.clear()

    def campaign(self, **kwargs):
        data = {
            "title": "Visite",
            "body": "Bonjour {prénom}, chambre {chambre}.",
            "author": self.nadia,
        }
        data.update(kwargs)
        return Campaign.objects.create(**data)


class AudienceTests(ComposerTestCase):
    def test_floors_and_channels(self):
        campaign = self.campaign()
        campaign.floors.add(self.f3)
        result = audience(campaign)
        self.assertEqual([r.user for r in result.recipients], [self.yanis, self.ines])
        self.assertEqual((result.total, result.push, result.sms, result.unreachable), (2, 1, 1, 0))

    def test_everyone_rooms_people_excluded(self):
        campaign = self.campaign(everyone=True)
        self.assertEqual(audience(campaign).total, 3)  # staff never included
        campaign.everyone = False
        campaign.save()
        campaign.rooms.add(self.r118)
        campaign.people.add(self.lucas)  # no room
        self.assertEqual({r.user for r in audience(campaign).recipients}, {self.awa, self.lucas})
        campaign.excluded.add(self.awa)
        result = audience(campaign)
        self.assertEqual([(r.user, r.room) for r in result.recipients], [(self.lucas, None)])
        self.assertEqual(result.recipients[0].channel, "sms")

    def test_departed_and_unreachable(self):
        from residents.departure import record_departure

        campaign = self.campaign(everyone=True)
        record_departure(self.yanis, timezone.localdate())
        result = audience(campaign)
        self.assertNotIn(self.yanis, [r.user for r in result.recipients])
        self.assertEqual(result.unreachable, 1)  # Awa: no device, no phone


class FindTargetTests(ComposerTestCase):
    def test_room_name_accentless_and_ambiguous(self):
        self.assertEqual(find_target("312")[0], self.r312)
        self.assertEqual(find_target("Inès Martin")[1], self.ines)
        self.assertEqual(find_target("ines")[1], self.ines)
        self.assertEqual(find_target("kone")[1], self.awa)
        make_user("ines2", first_name="Inès", last_name="Durand")
        self.assertIn("Plusieurs résidents", find_target("Inès")[2])
        self.assertIn("Aucune chambre ni aucun résident", find_target("999")[2])
        self.assertIn("Aucune", find_target("nadia")[2])  # staff are not recipients


class ComposerPageTests(ComposerTestCase):
    def post(self, url, **data):
        base = {
            "type": "visit",
            "title": "Visite de logement",
            "body": "Bonjour {prénom},\nVisite le {date} entre {début} et {fin}.",
            "sms_body": "",
            "event_date": "2026-11-06",
            "start_time": "15:00",
            "end_time": "17:00",
            "floors": [self.f3.pk],
            "action": "save",
        }
        base.update(data)
        return self.client.post(url, base, follow=True)

    def test_permissions(self):
        log_in_verified(self.client, self.ines)
        self.assertEqual(self.client.get(reverse("messaging:list")).status_code, 403)
        log_in_verified(self.client, make_user("marc", Role.MAINTENANCE))
        self.assertEqual(self.client.get(reverse("messaging:list")).status_code, 200)

    def test_new_from_a_template_then_save(self):
        log_in_verified(self.client, self.nadia)
        template = MessageTemplate.objects.get(name="Visite hebdomadaire · alarme et compteur")
        response = self.client.get(reverse("messaging:new") + f"?modele={template.pk}")
        save_page("messaging-new", response)
        self.assertContains(response, "Le {date}, nous passerons")
        self.assertContains(response, 'name="ask_reply" id="id_ask_reply" checked')
        response = self.post(reverse("messaging:new"), ask_reply="on")
        campaign = Campaign.objects.get()
        self.assertRedirects(response, reverse("messaging:compose", args=[campaign.pk]))
        save_page("messaging-compose", response)
        self.assertEqual(campaign.reply_type, "attendance")
        self.assertContains(response, "Brouillon enregistré à")
        self.assertContains(response, "<strong>2</strong> résidents")
        # Previews: the first recipient (room 304), with the date written out.
        self.assertContains(
            response, "Bonjour Yanis,\nVisite le vendredi 6 novembre entre 15 h et 17 h."
        )
        self.assertContains(response, "1 SMS")

    def test_add_exclude_restore(self):
        log_in_verified(self.client, self.nadia)
        campaign = self.campaign()
        url = reverse("messaging:compose", args=[campaign.pk])
        response = self.post(url, action="add", add="118", floors=[])
        self.assertContains(response, "Chambre 118 ajoutée.")
        response = self.post(url, action="add", add="Lucas", floors=[])
        self.assertContains(response, "<strong>2</strong> résidents")
        response = self.post(url, action=f"exclude:{self.awa.pk}", floors=[])
        self.assertContains(response, "Remettre Awa Koné")
        self.assertEqual(audience(campaign).total, 1)
        self.post(url, action=f"restore:{self.awa.pk}", floors=[])
        self.post(url, action=f"remove_room:{self.r118.pk}", floors=[])
        self.post(url, action=f"remove_person:{self.lucas.pk}", floors=[])
        self.assertEqual(audience(campaign).total, 0)
        response = self.post(url, action="add", add="Zorro", floors=[])
        self.assertContains(response, "Aucune chambre ni aucun résident")

    def test_errors(self):
        log_in_verified(self.client, self.nadia)
        response = self.post(reverse("messaging:new"), body="Bonjour {prenom}", title="")
        save_page("messaging-new-errors", response)
        self.assertContains(response, "Champ inconnu : {prenom}.")
        self.assertFalse(Campaign.objects.exists())
        response = self.post(reverse("messaging:new"), event_date="", start_time="")
        self.assertContains(response, "indiquez leurs valeurs ci-dessus")
        response = self.post(
            reverse("messaging:compose", args=[Campaign.objects.get().pk]),
            start_time="18:00",
        )
        self.assertContains(response, "L&#x27;heure de fin doit venir après")

    def test_sms_report(self):
        log_in_verified(self.client, self.nadia)
        response = self.post(reverse("messaging:new"), sms_body="Fête ce soir 🎉 à la salle")
        self.assertContains(response, "ê → e")
        self.assertContains(response, "Le SMS contient «\u00a0🎉\u00a0» :")
        self.assertContains(response, "1 SMS par personne")
        response = self.post(
            reverse("messaging:compose", args=[Campaign.objects.get().pk]), sms_body="x" * 1000
        )
        self.assertContains(response, "Trop long : 7 SMS.")

    @mock.patch("messaging.services.send_sms")
    @mock.patch("messaging.services.send_to_user", return_value=SendResult(sent=1))
    def test_send_test_to_me(self, push, sms):
        log_in_verified(self.client, self.nadia)
        campaign = self.campaign(event_date=date(2026, 11, 6))
        campaign.floors.add(self.f3)
        url = reverse("messaging:compose", args=[campaign.pk])
        response = self.post(url, action="test", test_sms="yes")
        self.assertContains(response, "Notification d&#x27;essai envoyée sur 1 appareil.")
        self.assertContains(response, "SMS d&#x27;essai envoyé")
        self.assertEqual(push.call_args.args, (self.nadia,))
        self.assertTrue(push.call_args.kwargs["title"].startswith("[Essai] "))
        self.assertIn("Bonjour Yanis", push.call_args.kwargs["body"])
        self.assertEqual(sms.call_args.args[0], "+33612345678")
        response = self.post(url, action="test")
        self.assertContains(response, "Attendez une minute")
        self.assertEqual(push.call_count, 1)

    def test_delete_even_with_an_invalid_form(self):
        log_in_verified(self.client, self.nadia)
        campaign = self.campaign()
        response = self.client.post(reverse("messaging:delete", args=[campaign.pk]), follow=True)
        save_page("messaging-list", response)
        self.assertContains(response, "Brouillon supprimé.")
        self.assertFalse(Campaign.objects.exists())


class TemplatePagesTests(ComposerTestCase):
    def test_list_create_edit_delete(self):
        log_in_verified(self.client, self.nadia)
        response = self.client.get(reverse("messaging:templates"))
        save_page("messaging-templates", response)
        self.assertContains(response, "Coupure d&#x27;eau")
        response = self.client.get(reverse("messaging:template_new"))
        save_page("messaging-template-new", response)
        data = {
            "type": MessageType.MAINTENANCE,
            "name": "Ascenseur en panne",
            "title": "Ascenseur",
            "body": "Bonjour {prénom}, l'ascenseur est en panne jusqu'au {date}.",
            "sms_body": "",
        }
        response = self.client.post(reverse("messaging:template_new"), data, follow=True)
        self.assertContains(response, "Modèle « Ascenseur en panne » enregistré.")
        template = MessageTemplate.objects.get(name="Ascenseur en panne")
        data["body"] = "Bonjour {prénom} {heure}"
        response = self.client.post(reverse("messaging:template_edit", args=[template.pk]), data)
        self.assertContains(response, "Champ inconnu : {heure}.")
        response = self.client.post(
            reverse("messaging:template_delete", args=[template.pk]), follow=True
        )
        self.assertContains(response, "supprimé")
        self.assertFalse(MessageTemplate.objects.filter(pk=template.pk).exists())
