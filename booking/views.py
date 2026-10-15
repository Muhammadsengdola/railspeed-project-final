import re
from datetime import date, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .models import Booking, ContactMessage, Profile, Schedule, Station
from .services import SeatTaken, booked_seat_ids, carriages_with_availability, hold_seats, promptpay_payload, search_schedules, user_tab

POPULAR = [("กรุงเทพอภิวัฒน์", "เชียงใหม่"), ("กรุงเทพอภิวัฒน์", "หัวหิน"), ("กรุงเทพอภิวัฒน์", "อุบลราชธานี")]
POPULAR_IMG = {
    "เชียงใหม่": ("สายเหนือ", "https://lh3.googleusercontent.com/aida-public/AB6AXuAtNU1kehfT3rocw_QVhq-3ywg2FPNrllEUXHGd89DLzo1TCh3o7Ox2fzYOH1AWVjunTPRwKBCutXQ8PRdakjm0_Uwsbnu_yk6pYg7O9jd-zB6qKiFCM7GEvBisxkaOt-ooV-qw0TcQeK_my7H90uY22j93xxaeyjNLLB-rO1mBu15UjXWegbUbAiEijSjHD7Th0eGRvwwP0sYGCFJhNvVcUFN18rcoaYCNLzMb4Hz9yZoJ6W1S2LZPUQ"),
    "หัวหิน": ("สายใต้", "https://lh3.googleusercontent.com/aida-public/AB6AXuAKDxxeDFff9sTQpoT4REJjpdgdp-uRw92WI__ubkzHG5sps46RLy6XQrSMU41iHXYj6SCQQViaBHEQjQqgYAu6d5y6vDxZRcMF6tw2_eX48YTrf8z2_n61vQEYuGdTUWT83dmzEw_2APhExwfZMqcpIplEeGhaRhGgXVgJPdAM62Pt0R75BBWS11LumsTPJ5YMK5g38JCwR1COlVOBYv3RR1CA1sEemTzF1VYC1xV9eEHhofazuEAeZg"),
    "อุบลราชธานี": ("สายตะวันออกเฉียงเหนือ", "https://lh3.googleusercontent.com/aida-public/AB6AXuCJFRH_SWmP6pM7pXEixWaYU4zF7ui5l5uzrnqhBombKL_5x9f_HKXeN4dfbpVgp-cIcPmjIwONkXaBdGrW-l5RxnHd--eAncS9dVD8wF24hrCTWevGYySzp-jrOZC6UZlDjSdeVtfBAf6z9ojiNhhT_c9wFA4_Vwg6HWjWbJyNW0AMV-O1WKXkaocAiENirIan9UeiCahi9jULRJZpwtRNbZjRxskivHsdvz5k7mx6ZUmh7dR_AvnEEA"),
}


def _parse_date(value, default=None):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return default


def _safe_next(request, fallback="home"):
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return nxt
    return reverse(fallback)


# ---------------- U1 / U4 ----------------

def home(request):
    stations = Station.objects.all()
    by_name = {s.name: s for s in stations}
    today = timezone.localdate()
    popular = []
    for a, b in POPULAR:
        if a in by_name and b in by_name:
            popular.append({
                "origin": by_name[a], "dest": by_name[b], "tag": POPULAR_IMG.get(b, ("", ""))[0], "img": POPULAR_IMG.get(b, ("", ""))[1],
                "count": Schedule.objects.filter(origin=by_name[a], destination=by_name[b], date__gte=today).values("train").distinct().count(),
            })
    default_origin = by_name.get("กรุงเทพอภิวัฒน์")
    default_dest = by_name.get("เชียงใหม่")
    return render(request, "public/home.html", {
        "stations": stations, "popular": popular, "today": today,
        "default_origin": default_origin, "default_dest": default_dest,
    })


def search(request):
    stations = Station.objects.all()
    today = timezone.localdate()
    origin = Station.objects.filter(pk=request.GET.get("from") or 0).first()
    dest = Station.objects.filter(pk=request.GET.get("to") or 0).first()
    day = _parse_date(request.GET.get("date"), today)
    sort = "price" if request.GET.get("sort") == "price" else "time"
    try:
        pax = min(max(int(request.GET.get("pax", 1)), 1), settings.MAX_SEATS_PER_BOOKING)
    except ValueError:
        pax = 1
    if not origin or not dest:
        messages.info(request, "กรุณาเลือกสถานีต้นทางและปลายทาง")
        return redirect("home")
    if origin == dest:
        messages.error(request, "ต้นทางและปลายทางต้องไม่ใช่สถานีเดียวกัน")
        return redirect("home")
    rows = search_schedules(origin.id, dest.id, day, sort)
    now = timezone.now()
    for r in rows:
        r["departed"] = r["schedule"].departs_at <= now
    base = f"?from={origin.id}&to={dest.id}&pax={pax}&sort={sort}"
    return render(request, "public/search.html", {
        "stations": stations, "origin": origin, "dest": dest, "day": day, "sort": sort, "pax": pax, "rows": rows,
        "prev_url": f"{base}&date={day - timedelta(days=1)}" if day > today else None,
        "next_url": f"{base}&date={day + timedelta(days=1)}",
        "sort_base": f"?from={origin.id}&to={dest.id}&pax={pax}&date={day}",
    })


# ---------------- U5 seat selection ----------------

def _seat_map(car, taken):
    """Group the seats of a carriage the way each layout is drawn."""
    seats = list(car.seats.all())
    layout = car.car_type.layout
    for s in seats:
        s.taken = s.id in taken
    groups = {}
    for s in seats:
        groups.setdefault(s.group, []).append(s)
    rows = []
    for g, items in sorted(groups.items()):
        if layout == "seat_2x2":
            by = {s.position: s for s in items}
            rows.append({"no": g, "A": by.get("A"), "B": by.get("B"), "C": by.get("C"), "D": by.get("D")})
        elif layout == "sleeper_open":
            left = [s for s in items if s.position == "L"]
            right = [s for s in items if s.position == "R"]
            rows.append({"no": g, "left": left, "right": right})
        else:
            rows.append({"no": g, "beds": items, "full": all(s.taken for s in items)})
    return rows


@login_required
def seats(request, schedule_id):
    schedule = get_object_or_404(Schedule.objects.select_related("train", "origin", "destination"), pk=schedule_id)
    if request.method == "POST":
        try:
            booking = hold_seats(request.user, schedule, request.POST.getlist("seat"))
        except SeatTaken:
            messages.error(request, "ขออภัย มีที่นั่งที่คุณเลือกถูกจองไปแล้ว กรุณาเลือกใหม่")
            return redirect(f"{reverse('seats', args=[schedule.id])}?car={request.POST.get('car', '')}")
        except ValueError as e:
            messages.error(request, str(e))
            return redirect(f"{reverse('seats', args=[schedule.id])}?car={request.POST.get('car', '')}")
        return redirect("passengers", booking.id)

    taken = booked_seat_ids(schedule)
    cars = carriages_with_availability(schedule, taken)
    if not cars:
        messages.error(request, "ขบวนนี้ยังไม่มีตู้โดยสาร")
        return redirect("home")
    try:
        car_no = int(request.GET.get("car", 0))
    except ValueError:
        car_no = 0
    current = next((c for c in cars if c["car"].number == car_no), None)
    if current is None:
        current = next((c for c in cars if c["free"]), cars[0])
    for c in cars:
        t = c["car"].car_type
        c["rows"] = _seat_map(c["car"], taken)
        c["layout"] = t.layout
        c["lower_price"], c["upper_price"] = t.price_for("lower"), t.price_for("upper")
    try:
        pax = min(max(int(request.GET.get("pax", settings.MAX_SEATS_PER_BOOKING)), 1), settings.MAX_SEATS_PER_BOOKING)
    except ValueError:
        pax = settings.MAX_SEATS_PER_BOOKING
    return render(request, "public/seats.html", {
        "schedule": schedule, "cars": cars, "current": current, "max_seats": settings.MAX_SEATS_PER_BOOKING, "pax": pax,
        "departed": schedule.departs_at <= timezone.now(),
    })


# ---------------- U6 / U7 / U8 booking flow ----------------

def _own_booking(request, booking_id, status=None):
    Booking.release_expired()
    qs = Booking.objects.select_related("schedule__train", "schedule__origin", "schedule__destination", "user")
    b = get_object_or_404(qs, pk=booking_id)
    if b.user_id != request.user.id and not request.user.is_staff:
        raise Http404
    return b


def _flow_guard(request, booking):
    if booking.status == "expired":
        messages.error(request, f"การจอง {booking.code} หมดเวลารักษาที่นั่งแล้ว กรุณาเลือกที่นั่งใหม่")
        return redirect("seats", booking.schedule_id)
    if booking.status != "held":
        return redirect("ticket", booking.id)
    return None


ID_RE = re.compile(r"^\d{13}$")


@login_required
def passengers(request, booking_id):
    booking = _own_booking(request, booking_id)
    guard = _flow_guard(request, booking)
    if guard:
        return guard
    seats_qs = list(booking.active_seats)
    errors = {}
    if request.method == "POST":
        for bs in seats_qs:
            name = request.POST.get(f"name_{bs.id}", "").strip()
            idc = re.sub(r"\D", "", request.POST.get(f"idcard_{bs.id}", ""))
            phone = request.POST.get(f"phone_{bs.id}", "").strip()
            bs.passenger_name, bs.id_card, bs.phone = name, idc, phone
            if not name:
                errors[f"name_{bs.id}"] = "กรุณากรอกชื่อ-นามสกุล"
            if not ID_RE.match(idc):
                errors[f"idcard_{bs.id}"] = "เลขบัตรประชาชนต้องมี 13 หลัก"
            if len(re.sub(r"\D", "", phone)) < 9:
                errors[f"phone_{bs.id}"] = "กรุณากรอกเบอร์โทรให้ถูกต้อง"
        if not errors:
            for bs in seats_qs:
                bs.save(update_fields=["passenger_name", "id_card", "phone"])
            return redirect("pay", booking.id)
        messages.error(request, "กรุณาตรวจสอบข้อมูลผู้โดยสารอีกครั้ง")
    me = request.user
    return render(request, "public/passengers.html", {
        "booking": booking, "seats": seats_qs, "errors": errors,
        "me": {"name": me.get_full_name(), "phone": getattr(getattr(me, "profile", None), "phone", "")},
    })


ALLOWED_SLIP = (".jpg", ".jpeg", ".png", ".pdf", ".webp")


@login_required
def pay(request, booking_id):
    booking = _own_booking(request, booking_id)
    guard = _flow_guard(request, booking)
    if guard:
        return guard
    if booking.active_seats.filter(passenger_name="").exists():
        messages.info(request, "กรุณากรอกข้อมูลผู้โดยสารก่อนชำระเงิน")
        return redirect("passengers", booking.id)
    if request.method == "POST":
        f = request.FILES.get("slip")
        if not f:
            messages.error(request, "กรุณาแนบไฟล์สลิปก่อนส่งหลักฐาน")
        elif not f.name.lower().endswith(ALLOWED_SLIP):
            messages.error(request, "รองรับเฉพาะไฟล์ JPG, PNG, WEBP หรือ PDF")
        elif f.size > settings.SLIP_MAX_BYTES:
            messages.error(request, "ไฟล์ใหญ่เกิน 5MB")
        else:
            booking.slip.save(f"{booking.code}_{f.name}", f, save=False)
            booking.slip_uploaded_at = timezone.now()
            booking.status = "pending"
            booking.hold_expires = None
            booking.save()
            messages.success(request, "ส่งหลักฐานการชำระเงินแล้ว รอแอดมินตรวจสอบ")
            return redirect("ticket", booking.id)
    qr_amount = round(booking.total / settings.PAY_DIVISOR, 2)
    return render(request, "public/pay.html", {
        "booking": booking, "seats": booking.active_seats,
        "qr_payload": promptpay_payload(settings.PROMPTPAY_ID, qr_amount),
        "qr_amount": qr_amount, "pay_divisor": settings.PAY_DIVISOR,
        "promptpay_id": settings.PROMPTPAY_ID, "promptpay_name": settings.PROMPTPAY_NAME,
    })


@login_required
def ticket(request, booking_id):
    booking = _own_booking(request, booking_id)
    if booking.status == "held":
        return redirect("pay" if not booking.active_seats.filter(passenger_name="").exists() else "passengers", booking.id)
    return render(request, "public/ticket.html", {"booking": booking, "seats": booking.shown_seats})


@login_required
@require_POST
def cancel_booking(request, booking_id):
    booking = _own_booking(request, booking_id)
    if booking.user_id != request.user.id:
        raise Http404
    if booking.can_cancel:
        booking.release("cancelled")
        messages.success(request, f"ยกเลิกการจอง {booking.code} แล้ว")
    else:
        messages.error(request, "การจองนี้ยกเลิกไม่ได้แล้ว")
    return redirect(_safe_next(request, "my_bookings"))


@login_required
def slip(request, booking_id):
    booking = _own_booking(request, booking_id)
    if not booking.slip:
        raise Http404
    if not booking.slip.storage.exists(booking.slip.name):
        if booking.slip.name.startswith("slips/seed_"):  # demo data: draw the sample slip instead of storing 25,000 files
            from .management.commands.seed import SLIP_SVG
            svg = SLIP_SVG.format(amount=f"{booking.total:,}", name=booking.user.get_full_name(), code=booking.code,
                                  when=timezone.localtime(booking.slip_uploaded_at or booking.created_at).strftime("%d/%m/%Y %H:%M"))
            return HttpResponse(svg, content_type="image/svg+xml; charset=utf-8")
        raise Http404
    return FileResponse(booking.slip.open("rb"), filename=booking.slip.name.rsplit("/", 1)[-1])


@login_required
def my_bookings(request):
    Booking.release_expired()
    tab = request.GET.get("tab", "upcoming")
    if tab not in ("upcoming", "completed", "cancelled"):
        tab = "upcoming"
    all_b = list(Booking.objects.filter(user=request.user).select_related("schedule__train", "schedule__origin", "schedule__destination"))
    now = timezone.now()
    counts = {"upcoming": 0, "completed": 0, "cancelled": 0}
    shown = []
    for b in all_b:
        t = user_tab(b, now)
        counts[t] += 1
        if t == tab:
            shown.append(b)
    if tab == "upcoming":
        shown.sort(key=lambda b: b.schedule.departs_at)
    return render(request, "public/my_bookings.html", {"tab": tab, "bookings": shown, "counts": counts})


# ---------------- U2 / U3 / U10 ----------------

def login_view(request):
    if request.user.is_authenticated:
        return redirect(_safe_next(request))
    email = ""
    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password", "")
        u = User.objects.filter(email__iexact=email).first()
        user = authenticate(request, username=u.username, password=password) if u else None
        if user:
            login(request, user)
            messages.success(request, f"ยินดีต้อนรับ คุณ{user.first_name or user.username}")
            return redirect(_safe_next(request))
        if u and not u.is_active and u.check_password(password):
            messages.error(request, "บัญชีนี้ถูกระงับการใช้งาน กรุณาติดต่อแอดมิน")
        else:
            messages.error(request, "อีเมลหรือรหัสผ่านไม่ถูกต้อง")
    return render(request, "public/login.html", {"email": email, "next": request.GET.get("next", request.POST.get("next", ""))})


def register(request):
    if request.user.is_authenticated:
        return redirect("home")
    data, errors = {}, {}
    if request.method == "POST":
        data = {k: request.POST.get(k, "").strip() for k in ("full_name", "email", "phone")}
        password = request.POST.get("password", "")
        email = data["email"].lower()
        if len(data["full_name"]) < 2:
            errors["full_name"] = "กรุณากรอกชื่อ-นามสกุล"
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            errors["email"] = "รูปแบบอีเมลไม่ถูกต้อง"
        elif User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).exists():
            errors["email"] = "อีเมลนี้มีผู้ใช้แล้ว"
        if len(re.sub(r"\D", "", data["phone"])) < 9:
            errors["phone"] = "กรุณากรอกเบอร์โทรให้ถูกต้อง"
        try:
            validate_password(password)
        except ValidationError:
            errors["password"] = "รหัสผ่านต้องยาวอย่างน้อย 8 ตัวอักษร"
        if not errors:
            first, _, last = data["full_name"].partition(" ")
            user = User.objects.create_user(username=email, email=email, password=password, first_name=first, last_name=last.strip())
            Profile.objects.create(user=user, phone=data["phone"])
            login(request, user)
            messages.success(request, "สมัครสมาชิกเรียบร้อย ยินดีต้อนรับ")
            return redirect(_safe_next(request))
    return render(request, "public/register.html", {"data": data, "errors": errors})


@require_POST
def logout_view(request):
    logout(request)
    messages.success(request, "ออกจากระบบแล้ว")
    return redirect("home")


@login_required
def profile(request):
    user = request.user
    prof, _ = Profile.objects.get_or_create(user=user)
    if request.method == "POST":
        if request.POST.get("action") == "password":
            cur, new = request.POST.get("current_password", ""), request.POST.get("new_password", "")
            if not user.check_password(cur):
                messages.error(request, "รหัสผ่านปัจจุบันไม่ถูกต้อง")
            else:
                try:
                    validate_password(new, user)
                except ValidationError:
                    messages.error(request, "รหัสผ่านใหม่ต้องยาวอย่างน้อย 8 ตัวอักษร")
                else:
                    user.set_password(new)
                    user.save()
                    update_session_auth_hash(request, user)
                    messages.success(request, "เปลี่ยนรหัสผ่านเรียบร้อยแล้ว")
        else:
            name = request.POST.get("full_name", "").strip()
            phone = request.POST.get("phone", "").strip()
            if len(name) < 2:
                messages.error(request, "กรุณากรอกชื่อ-นามสกุล")
            else:
                first, _, last = name.partition(" ")
                user.first_name, user.last_name = first, last.strip()
                user.save()
                prof.phone = phone
                prof.save()
                messages.success(request, "บันทึกข้อมูลส่วนตัวเรียบร้อยแล้ว")
        return redirect("profile")
    stats = Booking.objects.filter(user=user).aggregate(total=Count("id"), active=Count("id", filter=Q(status__in=("pending", "confirmed"))))
    return render(request, "public/profile.html", {"prof": prof, "stats": stats})


# ---------------- U11 contact ----------------

def contact(request):
    user = request.user if request.user.is_authenticated else None
    data = {"name": user.get_full_name() if user else "", "email": user.email if user else "", "subject": request.GET.get("subject", ""), "message": ""}
    sent = False
    if request.method == "POST":
        data = {k: request.POST.get(k, "").strip() for k in ("name", "email", "subject", "message")}
        if not all(data.values()):
            messages.error(request, "กรุณากรอกข้อมูลให้ครบทุกช่อง")
        elif not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", data["email"]):
            messages.error(request, "รูปแบบอีเมลไม่ถูกต้อง")
        else:
            ContactMessage.objects.create(user=user, **data)
            sent = True
            data["subject"] = data["message"] = ""
    return render(request, "public/contact.html", {"data": data, "sent": sent})