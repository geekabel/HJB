"""Form for a resident's profile (creation and change)."""

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify

from accounts.models import User
from housing.models import Room
from housing.services import assign_room, current_stay

NO_AUTOCOMPLETE = {"autocomplete": "off"}


class RoomChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, room):
        return f"{room.number} · {room.floor}"


def free_username(first_name, last_name):
    """'awa.kone', then 'awa.kone-2'... Residents never use it to log in."""
    base = ".".join(p for p in (slugify(first_name), slugify(last_name)) if p) or "resident"
    base = base[:140]
    candidate, n = base, 1
    while User.objects.filter(username=candidate).exists():
        n += 1
        candidate = f"{base}-{n}"
    return candidate


class ResidentForm(forms.ModelForm):
    # Free input (spaces, +33...): the model turns it into the international format.
    phone = forms.CharField(
        label="Téléphone portable",
        max_length=30,
        required=False,
        help_text="Par exemple 06 12 34 56 78. Il sert à envoyer les SMS et le code d'activation.",
        widget=forms.TextInput(attrs={"type": "tel", "inputmode": "tel", **NO_AUTOCOMPLETE}),
    )
    room = RoomChoiceField(
        queryset=Room.objects.none(),
        required=False,
        empty_label="Pas encore de chambre",
        label="Chambre",
    )
    arrival = forms.DateField(
        label="Date d'arrivée",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )

    class Meta:
        model = User
        fields = ["first_name", "last_name", "phone", "email"]
        labels = {"first_name": "Prénom", "last_name": "Nom", "email": "Adresse e-mail"}
        widgets = {
            "first_name": forms.TextInput(attrs=NO_AUTOCOMPLETE),
            "last_name": forms.TextInput(attrs=NO_AUTOCOMPLETE),
            "email": forms.EmailInput(attrs=NO_AUTOCOMPLETE),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True
        # Required as soon as a room is chosen (see clean): no "optional" mention.
        self.fields["arrival"].hide_optional = True
        if self.instance.phone:
            self.initial["phone"] = self.instance.phone_display
        self.stay = current_stay(self.instance) if self.instance.pk else None
        offered = Q(pk__in=Room.objects.free())
        if self.stay:
            offered |= Q(pk=self.stay.room_id)
            field = self.fields["room"]
            field.required = True
            field.empty_label = None
            field.help_text = (
                "Pour un déménagement dans la résidence, choisissez la nouvelle chambre "
                "et mettez la date du changement."
            )
            self.initial.setdefault("room", self.stay.room_id)
            self.initial.setdefault("arrival", self.stay.arrival)
        else:
            self.initial.setdefault("arrival", timezone.localdate())
        self.fields["room"].queryset = Room.objects.filter(offered).select_related("floor")
        if self.instance.pk and not self.instance.is_active and not self.stay:
            # Former resident: keep their identity up to date, without housing them here.
            del self.fields["room"]
            del self.fields["arrival"]

    def clean(self):
        data = super().clean()
        room, arrival = data.get("room"), data.get("arrival")
        if room and not arrival:
            self.add_error("arrival", "Indiquez la date d'arrivée dans la chambre.")
        elif (
            self.stay
            and room
            and room.pk != self.stay.room_id
            and arrival <= self.stay.arrival
            # On the arrival day itself, changing the room fixes a typing mistake.
            and not arrival == self.stay.arrival == timezone.localdate()
        ):
            # Otherwise, keeping the date of the current stay would erase the old room
            # from the history instead of recording a move.
            self.add_error(
                "arrival",
                "Pour un déménagement, indiquez sa date : après le "
                f"{self.stay.arrival:%d/%m/%Y}, jour d'arrivée dans la chambre actuelle.",
            )
        return data

    def save_resident(self):
        """Save the account, then the stay. Call it inside a transaction.

        Raise ValidationError if the stay is refused (room taken in the meantime...).
        """
        resident = self.save(commit=False)
        if resident.pk is None:
            resident.username = free_username(resident.first_name, resident.last_name)
            # Residents log in with a passkey, never with a password.
            resident.set_unusable_password()
            resident.save()
        else:
            # Row lock: a departure recorded at the same moment runs before
            # or after, never in the middle. Only the form fields are written,
            # so that an account disabled in the meantime is not enabled again.
            in_db = User.objects.select_for_update().get(pk=resident.pk)
            if "room" in self.fields and not in_db.is_active:
                raise ValidationError(
                    "Le départ de cette personne vient d'être enregistré. Rechargez la fiche."
                )
            resident.save(update_fields=list(self._meta.fields))
        room, arrival = self.cleaned_data.get("room"), self.cleaned_data.get("arrival")
        if room is None:
            return resident
        if self.stay and self.stay.room_id == room.pk:
            if arrival != self.stay.arrival:
                self.stay.arrival = arrival
                self.stay.full_clean()
                self.stay.save()
        else:
            assign_room(resident, room, arrival)
        return resident

    def add_stay_errors(self, error: ValidationError):
        for field, messages in error.message_dict.items():
            self.add_error(field if field in ("room", "arrival") else None, messages)


class ImportForm(forms.Form):
    file = forms.FileField(
        label="Fichier CSV ou Excel",
        help_text="Format .csv ou .xlsx, 2 Mo au plus, 500 résidents au plus.",
        widget=forms.FileInput(attrs={"accept": ".csv,.xlsx"}),
    )


class DepartureForm(forms.Form):
    departure = forms.DateField(
        label="Date du départ",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )

    def __init__(self, *args, stay=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.stay = stay
        today = timezone.localdate()
        self.fields["departure"].initial = today
        self.fields["departure"].widget.attrs["max"] = today.isoformat()
        if stay:
            self.fields["departure"].widget.attrs["min"] = stay.arrival.isoformat()

    def clean_departure(self):
        from .departure import check_date

        on = self.cleaned_data["departure"]
        check_date(on, self.stay)
        return on


class ReturnForm(forms.Form):
    room = RoomChoiceField(queryset=Room.objects.none(), label="Chambre", empty_label=None)
    arrival = forms.DateField(
        label="Date du retour",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["room"].queryset = Room.objects.free().select_related("floor")
        today = timezone.localdate()
        self.fields["arrival"].initial = today
        self.fields["arrival"].widget.attrs["max"] = today.isoformat()
