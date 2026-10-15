from django.conf import settings

from .models import Booking, ContactMessage


def site(request):
    ctx = {"HOLD_MINUTES": settings.HOLD_MINUTES, "MAX_SEATS": settings.MAX_SEATS_PER_BOOKING}
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        ctx["header_upcoming"] = Booking.objects.filter(user=user, status__in=("held", "pending", "confirmed")).count()
        if user.is_staff and request.path.startswith("/manage/"):
            ctx["nav_pending"] = Booking.objects.filter(status="pending").count()
            ctx["nav_unread"] = ContactMessage.objects.filter(is_read=False).count()
    return ctx
