"""RailSpeed REST API (Django REST Framework), mounted at /api/.

Public (read only):   stations, car-types, trains, schedules (+ search and seat map)
Logged-in users:      me, bookings (create = hold seats, passengers, slip upload, cancel)
Admin (is_staff):     create/update/delete stations, car-types, trains, schedules; confirm bookings; see all bookings
Auth: session (browser) or token -> POST /api/auth/token/ {"email", "password"} then header  Authorization: Token <key>
"""
import re

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from .models import Booking, BookingSeat, CarType, Carriage, Schedule, Station, Train
from .services import SeatTaken, booked_seat_ids, carriages_with_availability, hold_seats, schedule_summary


# ---------------- permissions ----------------

class IsAdminOrReadOnly(permissions.BasePermission):
    """Anyone can read; only admin (is_staff) can create, update or delete."""

    def has_permission(self, request, view):
        return request.method in permissions.SAFE_METHODS or bool(request.user and request.user.is_staff)


# ---------------- serializers ----------------

class StationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Station
        fields = ["id", "name", "province"]


class CarTypeSerializer(serializers.ModelSerializer):
    upper_berth_price = serializers.SerializerMethodField()

    class Meta:
        model = CarType
        fields = ["id", "name", "layout", "base_price", "upper_berth_diff", "upper_berth_price", "is_first_class"]

    def get_upper_berth_price(self, obj):
        return obj.price_for("upper") if obj.is_sleeper else None

    def validate_layout(self, layout):
        if self.instance and layout != self.instance.layout and self.instance.carriages.exists():
            raise serializers.ValidationError("เปลี่ยนรูปแบบผังไม่ได้ เพราะมีตู้ที่ใช้ประเภทนี้อยู่แล้ว")
        return layout


class CarriageSerializer(serializers.ModelSerializer):
    car_type_name = serializers.CharField(source="car_type.name", read_only=True)
    seat_count = serializers.IntegerField(source="seats.count", read_only=True)

    class Meta:
        model = Carriage
        fields = ["id", "number", "car_type", "car_type_name", "seat_count"]


class TrainSerializer(serializers.ModelSerializer):
    carriages = CarriageSerializer(many=True, read_only=True)

    class Meta:
        model = Train
        fields = ["id", "number", "train_type", "carriages"]


class ScheduleSerializer(serializers.ModelSerializer):
    train_number = serializers.CharField(source="train.number", read_only=True)
    origin_name = serializers.CharField(source="origin.name", read_only=True)
    destination_name = serializers.CharField(source="destination.name", read_only=True)
    duration_minutes = serializers.IntegerField(read_only=True)
    overnight = serializers.BooleanField(read_only=True)
    availability = serializers.SerializerMethodField()

    class Meta:
        model = Schedule
        fields = ["id", "train", "train_number", "origin", "origin_name", "destination", "destination_name", "date",
                  "depart_time", "arrive_time", "duration_minutes", "overnight", "availability"]

    def get_availability(self, obj):
        s = schedule_summary(obj)
        return {k: s[k] for k in ("min_price", "seat_free", "seat_total", "bed_free", "bed_total")}

    def validate(self, data):
        origin = data.get("origin", getattr(self.instance, "origin", None))
        dest = data.get("destination", getattr(self.instance, "destination", None))
        if origin and origin == dest:
            raise serializers.ValidationError("ต้นทางและปลายทางต้องไม่ใช่สถานีเดียวกัน")
        return data


class BookingSeatSerializer(serializers.ModelSerializer):
    carriage = serializers.IntegerField(source="seat.carriage.number", read_only=True)
    car_type = serializers.CharField(source="seat.carriage.car_type.name", read_only=True)
    label = serializers.CharField(source="seat.label", read_only=True)

    class Meta:
        model = BookingSeat
        fields = ["id", "seat", "carriage", "car_type", "label", "price", "passenger_name", "id_card", "phone", "active"]
        read_only_fields = ["seat", "price", "active"]


class BookingSerializer(serializers.ModelSerializer):
    code = serializers.CharField(read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    schedule_detail = serializers.SerializerMethodField()
    seats = serializers.SerializerMethodField()
    slip_url = serializers.SerializerMethodField()
    user_email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = Booking
        fields = ["id", "code", "user_email", "status", "status_display", "total", "schedule", "schedule_detail", "seats",
                  "created_at", "hold_expires", "slip_url", "slip_uploaded_at", "admin_note"]
        read_only_fields = fields

    def get_schedule_detail(self, obj):
        s = obj.schedule
        return {"train": s.train.number, "origin": s.origin.name, "destination": s.destination.name,
                "date": s.date, "depart_time": s.depart_time, "arrive_time": s.arrive_time}

    def get_seats(self, obj):
        return BookingSeatSerializer(obj.shown_seats, many=True).data

    def get_slip_url(self, obj):
        if not obj.slip:
            return None
        request = self.context.get("request")
        url = reverse("slip", args=[obj.id])
        return request.build_absolute_uri(url) if request else url


class BookingCreateSerializer(serializers.Serializer):
    schedule = serializers.PrimaryKeyRelatedField(queryset=Schedule.objects.all())
    seats = serializers.ListField(child=serializers.IntegerField(), min_length=1, max_length=settings.MAX_SEATS_PER_BOOKING)


class PassengerSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="booking seat id (from booking.seats[].id)")
    passenger_name = serializers.CharField(max_length=150)
    id_card = serializers.CharField(max_length=20)
    phone = serializers.CharField(max_length=20)

    def validate_id_card(self, value):
        digits = re.sub(r"\D", "", value)
        if len(digits) != 13:
            raise serializers.ValidationError("เลขบัตรประชาชนต้องมี 13 หลัก")
        return digits

    def validate_phone(self, value):
        if len(re.sub(r"\D", "", value)) < 9:
            raise serializers.ValidationError("กรุณากรอกเบอร์โทรให้ถูกต้อง")
        return value


# ---------------- viewsets ----------------

class StationViewSet(viewsets.ModelViewSet):
    """Stations. Read: everyone · Write: admin."""
    queryset = Station.objects.all()
    serializer_class = StationSerializer
    permission_classes = [IsAdminOrReadOnly]


class CarTypeViewSet(viewsets.ModelViewSet):
    """Car types and prices. Read: everyone · Write: admin."""
    queryset = CarType.objects.all()
    serializer_class = CarTypeSerializer
    permission_classes = [IsAdminOrReadOnly]


class TrainViewSet(viewsets.ModelViewSet):
    """Trains with their carriages. Admin can add a carriage with POST /api/trains/{id}/carriages/ {"car_type": id}."""
    queryset = Train.objects.prefetch_related("carriages__car_type")
    serializer_class = TrainSerializer
    permission_classes = [IsAdminOrReadOnly]

    @action(detail=True, methods=["post"], url_path="carriages")
    def add_carriage(self, request, pk=None):
        train = self.get_object()
        car_type = get_object_or_404(CarType, pk=request.data.get("car_type"))
        number = (train.carriages.order_by("-number").values_list("number", flat=True).first() or 0) + 1
        car = Carriage.objects.create(train=train, number=number, car_type=car_type)
        car.generate_seats()
        return Response(CarriageSerializer(car).data, status=status.HTTP_201_CREATED)


class ScheduleViewSet(viewsets.ModelViewSet):
    """Schedules. Search: /api/schedules/?from=<station id>&to=<station id>&date=YYYY-MM-DD&sort=time|price
    Seat map: /api/schedules/{id}/seats/"""
    serializer_class = ScheduleSerializer
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        qs = Schedule.objects.select_related("train", "origin", "destination")
        p = self.request.query_params
        if p.get("from"):
            qs = qs.filter(origin_id=p["from"])
        if p.get("to"):
            qs = qs.filter(destination_id=p["to"])
        if p.get("date"):
            qs = qs.filter(date=p["date"])
        if p.get("train"):
            qs = qs.filter(train__number__iexact=p["train"])
        return qs.order_by("date", "depart_time")

    def list(self, request, *args, **kwargs):
        if request.query_params.get("sort") == "price":
            rows = sorted(self.get_queryset(), key=lambda s: (schedule_summary(s)["min_price"], s.depart_time))
            page = self.paginate_queryset(rows)
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return super().list(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if self.get_object().bookings.exists():
            return Response({"detail": "ลบไม่ได้ เพราะรอบนี้มีการจองแล้ว"}, status=status.HTTP_409_CONFLICT)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["get"], permission_classes=[permissions.AllowAny])
    def seats(self, request, pk=None):
        """Seat map of every carriage; "taken": true means someone holds or booked it."""
        schedule = self.get_object()
        taken = booked_seat_ids(schedule)
        cars = []
        for c in carriages_with_availability(schedule, taken):
            car = c["car"]
            cars.append({
                "carriage": car.number, "car_type": car.car_type.name, "layout": car.car_type.layout,
                "free": c["free"], "total": c["total"],
                "seats": [{"id": s.id, "label": s.label, "group": s.group, "position": s.position, "berth": s.berth,
                           "price": s.price, "taken": s.id in taken} for s in car.seats.all()],
            })
        return Response({"schedule": schedule.id, "carriages": cars})


class BookingViewSet(viewsets.ReadOnlyModelViewSet):
    """Your bookings (admin sees everyone's; filter with ?status=pending).
    POST /api/bookings/ {"schedule": id, "seats": [seat ids]} holds the seats for HOLD_MINUTES."""
    serializer_class = BookingSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        Booking.release_expired()
        qs = Booking.objects.select_related("user", "schedule__train", "schedule__origin", "schedule__destination")
        if not self.request.user.is_staff:
            qs = qs.filter(user=self.request.user)
        if self.request.query_params.get("status"):
            qs = qs.filter(status=self.request.query_params["status"])
        return qs.order_by("-created_at")

    def get_serializer_class(self):
        return BookingCreateSerializer if self.action == "create" else BookingSerializer

    def _own(self):
        booking = self.get_object()
        if booking.user_id != self.request.user.id:
            raise PermissionDenied("ทำได้เฉพาะการจองของตัวเอง")
        return booking

    def create(self, request):
        data = BookingCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            booking = hold_seats(request.user, data.validated_data["schedule"], data.validated_data["seats"])
        except SeatTaken:
            return Response({"detail": "มีที่นั่งที่เลือกถูกจองไปแล้ว"}, status=status.HTTP_409_CONFLICT)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(BookingSerializer(booking, context={"request": request}).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def passengers(self, request, pk=None):
        """Body: [{"id": booking seat id, "passenger_name", "id_card", "phone"}, ...]"""
        booking = self._own()
        if booking.status != "held":
            return Response({"detail": "แก้ข้อมูลผู้โดยสารได้เฉพาะการจองที่รอชำระเงิน"}, status=status.HTTP_400_BAD_REQUEST)
        rows = PassengerSerializer(data=request.data, many=True)
        rows.is_valid(raise_exception=True)
        seats = {s.id: s for s in booking.active_seats}
        for row in rows.validated_data:
            bs = seats.get(row["id"])
            if not bs:
                return Response({"detail": f"ไม่พบที่นั่ง id {row['id']} ในการจองนี้"}, status=status.HTTP_400_BAD_REQUEST)
            bs.passenger_name, bs.id_card, bs.phone = row["passenger_name"], row["id_card"], row["phone"]
            bs.save(update_fields=["passenger_name", "id_card", "phone"])
        return Response(BookingSerializer(booking, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def slip(self, request, pk=None):
        """multipart/form-data with field "slip" (jpg, png, webp or pdf, max 5MB). Status becomes pending."""
        booking = self._own()
        f = request.FILES.get("slip")
        if booking.status != "held":
            return Response({"detail": "ส่งสลิปได้เฉพาะการจองที่รอชำระเงิน"}, status=status.HTTP_400_BAD_REQUEST)
        if booking.active_seats.filter(passenger_name="").exists():
            return Response({"detail": "กรุณากรอกข้อมูลผู้โดยสารก่อน"}, status=status.HTTP_400_BAD_REQUEST)
        if not f or not f.name.lower().endswith((".jpg", ".jpeg", ".png", ".pdf", ".webp")) or f.size > settings.SLIP_MAX_BYTES:
            return Response({"detail": "แนบไฟล์ JPG, PNG, WEBP หรือ PDF ขนาดไม่เกิน 5MB ในช่อง slip"}, status=status.HTTP_400_BAD_REQUEST)
        booking.slip.save(f"{booking.code}_{f.name}", f, save=False)
        booking.slip_uploaded_at, booking.status, booking.hold_expires = timezone.now(), "pending", None
        booking.save()
        return Response(BookingSerializer(booking, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        booking = self.get_object()
        if booking.user_id != request.user.id and not request.user.is_staff:
            raise PermissionDenied()
        if not (booking.can_cancel or (request.user.is_staff and booking.is_active)):
            return Response({"detail": "การจองนี้ยกเลิกไม่ได้แล้ว"}, status=status.HTTP_400_BAD_REQUEST)
        booking.release("cancelled")
        return Response(BookingSerializer(booking, context={"request": request}).data)

    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAdminUser])
    def confirm(self, request, pk=None):
        """Admin: confirm a booking whose slip was checked (status pending -> confirmed)."""
        booking = self.get_object()
        if booking.status != "pending":
            return Response({"detail": "ยืนยันได้เฉพาะการจองที่รอยืนยัน"}, status=status.HTTP_400_BAD_REQUEST)
        booking.status = "confirmed"
        booking.save(update_fields=["status"])
        return Response(BookingSerializer(booking, context={"request": request}).data)


# ---------------- auth / profile ----------------

@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def obtain_token(request):
    """POST {"email", "password"} -> {"token": "..."}; then send header  Authorization: Token <token>"""
    email = str(request.data.get("email", "")).strip().lower()
    u = User.objects.filter(email__iexact=email).first()
    user = authenticate(request, username=u.username, password=request.data.get("password", "")) if u else None
    if not user:
        return Response({"detail": "อีเมลหรือรหัสผ่านไม่ถูกต้อง หรือบัญชีถูกระงับ"}, status=status.HTTP_400_BAD_REQUEST)
    token, _ = Token.objects.get_or_create(user=user)
    return Response({"token": token.key, "is_staff": user.is_staff})


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def me(request):
    u = request.user
    return Response({
        "id": u.id, "email": u.email, "name": u.get_full_name(), "is_staff": u.is_staff,
        "phone": getattr(getattr(u, "profile", None), "phone", ""),
        "bookings": u.bookings.values("status").annotate(count=Count("id")).order_by("status"),
    })