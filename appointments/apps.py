from django.apps import AppConfig


class AppointmentsConfig(AppConfig):
    name = "appointments"
    verbose_name = "Rendez-vous"

    def ready(self):
        # A resident who leaves (T09): their upcoming meetings are cancelled.
        from residents.departure import departure_recorded

        from .booking import cancel_on_departure

        departure_recorded.connect(cancel_on_departure, dispatch_uid="appointments.departure")
