"""Admin side (/manage/) — designs A1-A12."""
from datetime import timedelta
from functools import wraps

from django import forms
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.db.models import Count, Max, ProtectedError, Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Booking, BookingSeat, CarType, Carriage, ContactMessage, Profile, Schedule, Seat, Station, Train
from .services import booked_seat_ids


def staff_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_staff:
            return redirect(f"{reverse('manage_login')}?next={request.path}")
        return view(request, *args, **kwargs)
    return wrapper


def manage_login(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect("manage_dashboard")
    email = ""
    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        u = User.objects.filter(email__iexact=email, is_staff=True).first()
        user = authenticate(request, username=u.username, password=request.POST.get("password", "")) if u else None
        if user and user.is_staff:
            login(request, user)
            nxt = request.GET.get("next", "")
            return redirect(nxt if nxt.startswith("/manage/") else "manage_dashboard")
        messages.error(request, "อีเมลหรือรหัสผ่านไม่ถูกต้อง หรือบัญชีนี้ไม่ใช่ผู้ดูแลระบบ")
    return render(request, "manage/login.html", {"email": email})


@require_POST
def manage_logout(request):
    logout(request)
    return redirect("manage_login")


# ---------------- A2 dashboard ----------------

@staff_required
def dashboard(request):
    Booking.release_expired()
    today = timezone.localdate()
    tz = timezone.get_current_timezone()
    active = Booking.objects.filter(status__in=("pending", "confirmed"))
    days = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        days.append({"date": d, "count": Booking.objects.filter(created_at__date=d).exclude(status="held").count()})
    peak = max([d["count"] for d in days] + [1])
    for d in days:
        d["pct"] = max(4, round(d["count"] * 100 / peak))
    ctx = {
        "today_count": Booking.objects.filter(created_at__date=today).exclude(status="held").count(),
        "revenue": Booking.objects.filter(status="confirmed").aggregate(s=Sum("total"))["s"] or 0,
        "seats_booked": BookingSeat.objects.filter(active=True, booking__status__in=("pending", "confirmed"), schedule__date__gte=today).count(),
        "pending_count": active.filter(status="pending").count(),
        "days": days,
        "recent": Booking.objects.exclude(status="held").select_related("user", "schedule__train").prefetch_related("seats__seat__carriage")[:6],
    }
    return render(request, "manage/dashboard.html", ctx)


# ---------------- A3 bookings ----------------

@staff_required
def bookings(request):
    Booking.release_expired()
    status = request.GET.get("status", "")
    q = request.GET.get("q", "").strip()
    qs = Booking.objects.exclude(status="held").select_related("user", "schedule__train", "schedule__origin", "schedule__destination")
    if status in ("pending", "confirmed", "cancelled", "expired"):
        qs = qs.filter(status=status)
    if q:
        bid = Booking.code_to_id(q)
        cond = Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q) | Q(user__email__icontains=q) | Q(schedule__train__number__icontains=q) | Q(seats__passenger_name__icontains=q)
        if bid:
            cond |= Q(id=bid)
        qs = qs.filter(cond).distinct()
    edit = None
    edit_id = request.GET.get("edit")
    if edit_id and edit_id.isdigit():
        edit = Booking.objects.filter(pk=edit_id).select_related("schedule__train").first()
        if edit:
            taken = booked_seat_ids(edit.schedule)
            mine = set(edit.seats.filter(active=True).values_list("seat_id", flat=True))
            free = Seat.objects.filter(carriage__train=edit.schedule.train).select_related("carriage__car_type").exclude(id__in=taken - mine)
            edit.free_seats = list(free)
            edit.seat_rows = list(edit.shown_seats)
    return render(request, "manage/bookings.html", {
        "bookings": qs[:200], "status": status, "q": q, "edit": edit,
        "counts": dict(Booking.objects.exclude(status="held").values_list("status").annotate(c=Count("id"))),
    })


def _back(request, fallback="manage_bookings"):
    nxt = request.POST.get("next", "")
    return redirect(nxt if nxt.startswith("/manage/") else reverse(fallback))


@staff_required
@require_POST
def booking_status(request, booking_id):
    b = get_object_or_404(Booking, pk=booking_id)
    new = request.POST.get("status")
    if new == "confirmed" and b.status == "pending":
        b.status = "confirmed"
        b.save(update_fields=["status"])
        messages.success(request, f"ยืนยันการจอง {b.code} แล้ว")
    elif new == "cancelled" and b.status in ("pending", "confirmed", "held"):
        b.release("cancelled")
        messages.success(request, f"ยกเลิกการจอง {b.code} และคืนที่นั่งแล้ว")
    else:
        messages.error(request, "เปลี่ยนสถานะนี้ไม่ได้")
    return _back(request)


@staff_required
@require_POST
def booking_edit(request, booking_id):
    b = get_object_or_404(Booking.objects.select_related("schedule"), pk=booking_id)
    new_status = request.POST.get("status", b.status)
    try:
        with transaction.atomic():
            rows = list(b.seats.select_related("seat"))
            reactivate = new_status in ("pending", "confirmed") and b.status in ("cancelled", "expired")
            for bs in rows:
                if not bs.active and not reactivate:
                    continue
                bs.passenger_name = request.POST.get(f"name_{bs.id}", bs.passenger_name).strip()
                bs.phone = request.POST.get(f"phone_{bs.id}", bs.phone).strip()
                seat_id = request.POST.get(f"seat_{bs.id}")
                if seat_id and seat_id.isdigit() and int(seat_id) != bs.seat_id:
                    seat = get_object_or_404(Seat, pk=seat_id, carriage__train=b.schedule.train)
                    bs.seat, bs.price = seat, seat.price
                if reactivate:
                    bs.active = True
                bs.save()
            if new_status in ("cancelled", "expired") and b.status not in ("cancelled", "expired"):
                b.seats.update(active=False)
            b.status = new_status if new_status in dict(Booking.STATUSES) else b.status
            b.admin_note = request.POST.get("admin_note", b.admin_note)
            b.recalc_total() if b.status not in ("cancelled", "expired") else None
            b.save()
    except IntegrityError:
        messages.error(request, "บันทึกไม่ได้: ที่นั่งที่เลือกมีผู้อื่นจองอยู่แล้ว")
        return redirect(f"{reverse('manage_bookings')}?edit={b.id}")
    messages.success(request, f"บันทึกการแก้ไข {b.code} แล้ว")
    return _back(request)


# ---------------- generic CRUD (A5 A6 A8 A9 A11) ----------------

class StationForm(forms.ModelForm):
    class Meta:
        model = Station
        fields = ["name", "province"]


class TrainForm(forms.ModelForm):
    class Meta:
        model = Train
        fields = ["number", "train_type"]


class ScheduleForm(forms.ModelForm):
    class Meta:
        model = Schedule
        fields = ["train", "origin", "destination", "date", "depart_time", "arrive_time"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "depart_time": forms.TimeInput(attrs={"type": "time"}),
            "arrive_time": forms.TimeInput(attrs={"type": "time"}),
        }

    def clean(self):
        c = super().clean()
        if c.get("origin") and c.get("origin") == c.get("destination"):
            raise forms.ValidationError("ต้นทางและปลายทางต้องไม่ใช่สถานีเดียวกัน")
        return c


class CarTypeForm(forms.ModelForm):
    class Meta:
        model = CarType
        fields = ["name", "layout", "base_price", "upper_berth_diff", "is_first_class"]

    def clean_layout(self):
        layout = self.cleaned_data["layout"]
        if self.instance.pk and layout != self.instance.layout and self.instance.carriages.exists():
            raise forms.ValidationError("เปลี่ยนรูปแบบผังไม่ได้ เพราะมีตู้ที่ใช้ประเภทนี้อยู่แล้ว")
        return layout


class AdminForm(forms.Form):
    full_name = forms.CharField(label="ชื่อ-นามสกุล", max_length=150)
    email = forms.EmailField(label="อีเมล")
    password = forms.CharField(label="รหัสผ่านเริ่มต้น", min_length=8, widget=forms.PasswordInput)

    def clean_email(self):
        e = self.cleaned_data["email"].lower()
        if User.objects.filter(Q(email__iexact=e) | Q(username__iexact=e)).exists():
            raise forms.ValidationError("อีเมลนี้มีผู้ใช้แล้ว")
        return e


CRUD = {
    "stations": {"title": "สถานี", "model": Station, "form": StationForm, "icon": "pin_drop", "noun": "สถานี",
                 "cols": [("ชื่อสถานี", "name"), ("จังหวัด", "province")], "search": ["name", "province"]},
    "trains": {"title": "ขบวนรถ", "model": Train, "form": TrainForm, "icon": "directions_railway", "noun": "ขบวนรถ",
               "cols": [("เลขขบวน", "number"), ("ประเภท", "train_type"), ("จำนวนตู้", "car_count")], "search": ["number", "train_type"]},
    "schedules": {"title": "รอบเดินทาง", "model": Schedule, "form": ScheduleForm, "icon": "calendar_month", "noun": "รอบเดินทาง",
                  "cols": [("ขบวน", "train"), ("ต้นทาง", "origin"), ("ปลายทาง", "destination"), ("วันที่", "date"), ("ออก", "depart_time"), ("ถึง", "arrive_time"), ("จองแล้ว", "booked")],
                  "search": ["train__number", "origin__name", "destination__name"]},
    "classes": {"title": "ประเภทตู้/ราคา", "model": CarType, "form": CarTypeForm, "icon": "airline_seat_recline_extra", "noun": "ประเภทตู้",
                "cols": [("ประเภทตู้", "name"), ("รูปแบบผัง", "get_layout_display"), ("ราคา (บาท)", "base_price"), ("ส่วนต่างเตียงบน", "upper_berth_diff")], "search": ["name"]},
}


def _crud_queryset(kind, q):
    cfg = CRUD[kind]
    qs = cfg["model"].objects.all()
    if kind == "trains":
        qs = qs.annotate(car_count=Count("carriages"))
    if kind == "schedules":
        qs = qs.select_related("train", "origin", "destination").annotate(booked=Count("booked_seats", filter=Q(booked_seats__active=True))).order_by("date", "depart_time")
        if not q and not cfg.get("show_past"):
            qs = qs.filter(date__gte=timezone.localdate() - timedelta(days=1), date__lte=timezone.localdate() + timedelta(days=14))
    if q:
        cond = Q()
        for f in cfg["search"]:
            cond |= Q(**{f"{f}__icontains": q})
        qs = qs.filter(cond)
    return qs


@staff_required
def crud_list(request, kind):
    if kind not in CRUD:
        raise Http404
    cfg = CRUD[kind]
    q = request.GET.get("q", "").strip()
    form, editing = None, None
    if request.method == "POST":
        pk = request.POST.get("id")
        editing = get_object_or_404(cfg["model"], pk=pk) if pk else None
        form = cfg["form"](request.POST, instance=editing)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"บันทึก{cfg['noun']}แล้ว")
            return redirect(f"{reverse('manage_crud', args=[kind])}{'?q=' + q if q else ''}")
        messages.error(request, "กรุณาตรวจสอบข้อมูลในฟอร์ม")
    elif request.GET.get("edit", "").isdigit():
        editing = get_object_or_404(cfg["model"], pk=request.GET["edit"])
        form = cfg["form"](instance=editing)
    elif request.GET.get("new"):
        form = cfg["form"]()
    rows = []
    for obj in _crud_queryset(kind, q)[:300]:
        cells = []
        for _, attr in cfg["cols"]:
            v = getattr(obj, attr)
            cells.append(v() if callable(v) else v)
        rows.append({"obj": obj, "cells": cells})
    return render(request, "manage/crud.html", {"kind": kind, "cfg": cfg, "rows": rows, "q": q, "form": form, "editing": editing})


@staff_required
@require_POST
def crud_delete(request, kind, pk):
    if kind not in CRUD:
        raise Http404
    obj = get_object_or_404(CRUD[kind]["model"], pk=pk)
    try:
        if kind == "trains" and BookingSeat.objects.filter(schedule__train=obj).exists():
            raise ProtectedError("bookings", [])
        if kind == "schedules" and obj.bookings.exists():
            raise ProtectedError("bookings", [])
        obj.delete()
        messages.success(request, f"ลบ{CRUD[kind]['noun']}แล้ว")
    except ProtectedError:
        messages.error(request, f"ลบไม่ได้ เพราะ{CRUD[kind]['noun']}นี้ยังมีข้อมูลอื่นอ้างอิงอยู่ (เช่น รอบเดินทางหรือการจอง)")
    return redirect("manage_crud", kind)


# ---------------- A7 carriages ----------------

@staff_required
def train_cars(request, train_id):
    train = get_object_or_404(Train, pk=train_id)
    if request.method == "POST":
        ct = get_object_or_404(CarType, pk=request.POST.get("car_type"))
        with transaction.atomic():
            n = (train.carriages.aggregate(m=Max("number"))["m"] or 0) + 1
            car = Carriage.objects.create(train=train, number=n, car_type=ct)
            car.generate_seats()
        messages.success(request, f"เพิ่มตู้ {n} ({ct.name}) และสร้างที่นั่ง {car.seats.count()} ที่แล้ว")
        return redirect("manage_train_cars", train.id)
    cars = train.carriages.select_related("car_type").annotate(seat_count=Count("seats"))
    return render(request, "manage/train_cars.html", {"train": train, "cars": cars, "car_types": CarType.objects.all()})


@staff_required
@require_POST
def train_car_delete(request, train_id, car_id):
    car = get_object_or_404(Carriage, pk=car_id, train_id=train_id)
    if BookingSeat.objects.filter(seat__carriage=car).exists():
        messages.error(request, f"ลบตู้ {car.number} ไม่ได้ เพราะมีประวัติการจองที่นั่งในตู้นี้")
    else:
        n = car.number
        with transaction.atomic():
            car.delete()
            for c in Carriage.objects.filter(train_id=train_id, number__gt=n).order_by("number"):
                c.number -= 1
                c.save(update_fields=["number"])
        messages.success(request, f"ลบตู้ {n} แล้ว (เลขตู้ถัดไปเลื่อนขึ้นมา)")
    return redirect("manage_train_cars", train_id)


# ---------------- A10 users ----------------

@staff_required
def users(request):
    q = request.GET.get("q", "").strip()
    qs = User.objects.filter(is_staff=False).select_related("profile").annotate(nb=Count("bookings")).order_by("-date_joined")
    if q:
        qs = qs.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q) | Q(profile__phone__icontains=q))
    return render(request, "manage/users.html", {"users": qs, "q": q})


@staff_required
@require_POST
def user_toggle(request, user_id):
    u = get_object_or_404(User, pk=user_id, is_staff=False)
    u.is_active = not u.is_active
    u.save(update_fields=["is_active"])
    messages.success(request, f"{'ปลดระงับ' if u.is_active else 'ระงับ'}บัญชี {u.get_full_name() or u.email} แล้ว")
    return redirect(f"{reverse('manage_users')}?q={request.POST.get('q', '')}")


# ---------------- A11 admins ----------------

@staff_required
def admins(request):
    q = request.GET.get("q", "").strip()
    form = None
    if request.method == "POST":
        form = AdminForm(request.POST)
        if form.is_valid():
            first, _, last = form.cleaned_data["full_name"].partition(" ")
            u = User.objects.create_user(username=form.cleaned_data["email"], email=form.cleaned_data["email"], password=form.cleaned_data["password"],
                                         first_name=first, last_name=last.strip(), is_staff=True)
            Profile.objects.get_or_create(user=u)
            messages.success(request, f"เพิ่มผู้ดูแล {u.get_full_name()} แล้ว")
            return redirect("manage_admins")
        messages.error(request, "กรุณาตรวจสอบข้อมูลในฟอร์ม")
    elif request.GET.get("new"):
        form = AdminForm()
    qs = User.objects.filter(is_staff=True).order_by("date_joined")
    if q:
        qs = qs.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q))
    return render(request, "manage/admins.html", {"admins": qs, "q": q, "form": form})


@staff_required
@require_POST
def admin_delete(request, user_id):
    u = get_object_or_404(User, pk=user_id, is_staff=True)
    if u == request.user:
        messages.error(request, "ลบบัญชีของตัวเองไม่ได้")
    elif User.objects.filter(is_staff=True).count() <= 1:
        messages.error(request, "ต้องมีผู้ดูแลอย่างน้อย 1 คน")
    else:
        u.delete()
        messages.success(request, "ลบผู้ดูแลแล้ว")
    return redirect("manage_admins")


# ---------------- A12 messages ----------------

@staff_required
def contact_messages(request):
    q = request.GET.get("q", "").strip()
    qs = ContactMessage.objects.all()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(email__icontains=q) | Q(subject__icontains=q) | Q(message__icontains=q))
    return render(request, "manage/messages.html", {"items": qs, "q": q})


@staff_required
@require_POST
def message_read(request, pk):
    m = get_object_or_404(ContactMessage, pk=pk)
    m.is_read = not m.is_read if request.POST.get("toggle") else True
    m.save(update_fields=["is_read"])
    return redirect(f"{reverse('manage_messages')}?q={request.POST.get('q', '')}")
