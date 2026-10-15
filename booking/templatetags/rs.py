from django import template
from django.utils import timezone

from ..services import status_badge as _badge

register = template.Library()

TH_MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
TH_DAYS = ["จ.", "อ.", "พ.", "พฤ.", "ศ.", "ส.", "อา."]


@register.filter
def thdate(value, short=False):
    """12 ต.ค. 2026"""
    if not value:
        return ""
    if hasattr(value, "astimezone") and getattr(value, "tzinfo", None):
        value = timezone.localtime(value)
    text = f"{value.day} {TH_MONTHS[value.month - 1]}"
    return text if short else f"{text} {value.year}"


@register.filter
def thday(value):
    return TH_DAYS[value.weekday()] if value else ""


@register.filter
def thdatetime(value):
    if not value:
        return ""
    value = timezone.localtime(value)
    return f"{thdate(value)} {value:%H:%M}"


@register.filter
def hm(value):
    return value.strftime("%H:%M") if value else ""


@register.filter
def baht(value):
    try:
        return f"฿{int(value):,}"
    except (TypeError, ValueError):
        return "฿0"


@register.filter
def badge(status):
    return _badge(status)


@register.filter
def get(d, key):
    try:
        return d.get(key)
    except AttributeError:
        return None


@register.filter
def initials(user):
    name = (user.first_name or user.username or "?").strip()
    return name[:2]
