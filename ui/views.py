from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render

# Django docs "Permissions and Authorization": login_required, then permission_required
# with raise_exception. A logged-in person without the permission gets a 403 instead
# of being sent back to the login page in a loop.


@login_required
@permission_required("accounts.access_staff_area", raise_exception=True)
def guide(request):
    """Style guide: all the components, in the staff template."""
    return render(request, "ui/guide/index.html", {"reports_to_handle": 7})


@login_required
@permission_required("accounts.access_staff_area", raise_exception=True)
def guide_resident(request):
    """Sample resident home page, in the mobile template."""
    return render(request, "ui/guide/resident.html", {"active_nav": "home"})
