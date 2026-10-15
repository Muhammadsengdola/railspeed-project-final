"""Business logic shared by the public and admin views."""
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone

from .models import Booking, BookingSeat, Carriage, Schedule, Seat


class SeatTaken(Exception):
    pass


def booked_seat_ids(schedule):
    """IDs of seats that are currently held, pending or confirmed on this schedule."""
    Booking.release_expired()
    return set(
        BookingSeat.objects.filter(schedule=schedule, active=True).values_list("seat_id", flat=True)
    )


def carriages_with_availability(schedule, taken=None):
    taken = booked_seat_ids(schedule) if taken is None else taken
    cars = (
        Carriage.objects.filter(train=schedule.train)
        .select_related("car_type")
        .annotate(total=Count("seats"))
    )
    result = []
    for car in cars:
        ids = car.seats.values_list("id", flat=True)
        free = sum(1 for i in ids if i not in taken)
        result.append({"car": car, "total": car.total, "free": free})
    return result


def schedule_summary(schedule):
    """Numbers shown on a search-result card (U4)."""
    taken = booked_seat_ids(schedule)
    cars = carriages_with_availability(schedule, taken)
    seat_free = sum(c["free"] for c in cars if not c["car"].car_type.is_sleeper)
    seat_total = sum(c["total"] for c in cars if not c["car"].car_type.is_sleeper)
    bed_free = sum(c["free"] for c in cars if c["car"].car_type.is_sleeper)
    bed_total = sum(c["total"] for c in cars if c["car"].car_type.is_sleeper)
    prices = []
    for c in cars:
        t = c["car"].car_type
        prices.append(t.base_price + min(0, t.upper_berth_diff))
    return {
        "schedule": schedule,
        "min_price": min(prices) if prices else 0,
        "seat_free": seat_free,
        "seat_total": seat_total,
        "bed_free": bed_free,
        "bed_total": bed_total,
        "free": seat_free + bed_free,
    }


def hold_seats(user, schedule, seat_ids):
    """Lock seats for HOLD_MINUTES. Raises SeatTaken / ValueError."""
    seat_ids = [int(s) for s in seat_ids if str(s).isdigit()]
    seat_ids = list(dict.fromkeys(seat_ids))
    if not seat_ids:
        raise ValueError("กรุณาเลือกที่นั่งอย่างน้อย 1 ที่")
    if len(seat_ids) > settings.MAX_SEATS_PER_BOOKING:
        raise ValueError(f"เลือกได้สูงสุด {settings.MAX_SEATS_PER_BOOKING} ที่นั่งต่อการจอง")
    if schedule.departs_at <= timezone.now():
        raise ValueError("รอบเดินทางนี้ออกไปแล้ว")
    seats = list(Seat.objects.filter(id__in=seat_ids, carriage__train=schedule.train).select_related("carriage__car_type"))
    if len(seats) != len(seat_ids):
        raise ValueError("ที่นั่งไม่ถูกต้อง")

    # A user keeps only one unpaid hold at a time: release older ones first.
    for old in Booking.objects.filter(user=user, status="held"):
        old.release("cancelled")

    Booking.release_expired()
    try:
        with transaction.atomic():
            if BookingSeat.objects.select_for_update().filter(schedule=schedule, seat__in=seats, active=True).exists():
                raise SeatTaken()
            booking = Booking.objects.create(
                user=user,
                schedule=schedule,
                status="held",
                hold_expires=timezone.now() + timedelta(minutes=settings.HOLD_MINUTES),
            )
            for seat in seats:
                BookingSeat.objects.create(booking=booking, schedule=schedule, seat=seat, price=seat.price)
            booking.recalc_total()
            booking.save()
    except IntegrityError:
        raise SeatTaken()
    return booking


def user_tab(booking, now=None):
    """Which tab of U9 a booking belongs to."""
    now = now or timezone.now()
    if booking.status in ("cancelled", "expired"):
        return "cancelled"
    if booking.schedule.departs_at <= now:
        return "completed"
    return "upcoming"


# ---------- PromptPay (EMVCo QR payload) ----------

def _tlv(tag, value):
    return f"{tag}{len(value):02d}{value}"


def _crc16(data):
    crc = 0xFFFF
    for ch in data.encode("ascii"):
        crc ^= ch << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return f"{crc:04X}"


def promptpay_payload(target, amount):
    target = "".join(ch for ch in target if ch.isdigit())
    if len(target) >= 13:
        account = _tlv("02", target[:13])
    else:
        account = _tlv("01", ("0066" + target.lstrip("0")).rjust(13, "0"))
    merchant = _tlv("00", "A000000677010111") + account
    payload = (
        _tlv("00", "01")
        + _tlv("01", "12")
        + _tlv("29", merchant)
        + _tlv("53", "764")
        + _tlv("54", f"{amount:.2f}")
        + _tlv("58", "TH")
    )
    payload += "6304"
    return payload + _crc16(payload)


def search_schedules(origin_id, dest_id, date, sort="time"):
    qs = Schedule.objects.filter(origin_id=origin_id, destination_id=dest_id, date=date).select_related(
        "train", "origin", "destination"
    )
    rows = [schedule_summary(s) for s in qs]
    if sort == "price":
        rows.sort(key=lambda r: (r["min_price"], r["schedule"].depart_time))
    else:
        rows.sort(key=lambda r: r["schedule"].depart_time)
    return rows


def status_badge(status):
    return {
        "held": "bg-surface-container text-slate",
        "pending": "bg-warning-bg text-ink border border-amber-signal/40",
        "confirmed": "bg-success/10 text-success border border-success/30",
        "cancelled": "bg-danger/10 text-danger border border-danger/30",
        "expired": "bg-danger/10 text-danger border border-danger/30",
    }.get(status, "")

