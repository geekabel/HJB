from django.apps import AppConfig


class ResidentsConfig(AppConfig):
    name = "residents"
    verbose_name = "Résidents (espace équipe)"

    def ready(self):
        # At a departure, the wifi access of the room is cut (card T15).
        from housing.wifi import cut_on_departure

        from .departure import departure_recorded

        departure_recorded.connect(cut_on_departure, dispatch_uid="housing.cut_wifi")
