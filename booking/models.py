from datetime import datetime, timedelta

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    phone = models.CharField("เบอร์โทร", max_length=20, blank=True)

    def __str__(self):
        return self.user.get_full_name() or self.user.username


class Station(models.Model):
    name = models.CharField("ชื่อสถานี", max_length=100, unique=True)
    province = models.CharField("จังหวัด", max_length=100)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.name


class Train(models.Model):
    TYPES = [("ด่วนพิเศษ", "ด่วนพิเศษ"), ("ด่วน", "ด่วน"), ("เร็ว", "เร็ว"), ("ธรรมดา", "ธรรมดา")]
    number = models.CharField("เลขขบวน", max_length=20, unique=True)
    train_type = models.CharField("ประเภท", max_length=20, choices=TYPES, default="ด่วนพิเศษ")

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.number


class CarType(models.Model):
    LAYOUTS = [
        ("seat_2x2", "ตู้นั่ง 2+2 (8 แถว 32 ที่นั่ง)"),
        ("sleeper_open", "ตู้นอนแบบเปิด (6 ล็อก 24 เตียง)"),
        ("sleeper_room", "ตู้นอนห้องคู่ (6 ห้อง 12 เตียง)"),
    ]
    name = models.CharField("ประเภทตู้", max_length=100, unique=True)
    layout = models.CharField("รูปแบบผัง", max_length=20, choices=LAYOUTS, default="seat_2x2")
    base_price = models.PositiveIntegerField("ราคา (บาท)")
    upper_berth_diff = models.IntegerField("ส่วนต่างเตียงบน", default=0)
    is_first_class = models.BooleanField("ชั้น 1", default=False)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.name

    @property
    def is_sleeper(self):
        return self.layout != "seat_2x2"

    @property
    def color(self):
        if self.layout == "seat_2x2":
            return "coach-seat-first" if self.is_first_class else "coach-seat-standard"
        return "coach-sleeper-first" if self.layout == "sleeper_room" else "coach-sleeper-second"

    def price_for(self, berth):
        return self.base_price + (self.upper_berth_diff if berth == "upper" else 0)


class Carriage(models.Model):
    train = models.ForeignKey(Train, on_delete=models.CASCADE, related_name="carriages")
    number = models.PositiveSmallIntegerField("ตู้ที่")
    car_type = models.ForeignKey(CarType, on_delete=models.PROTECT, related_name="carriages", verbose_name="ประเภทตู้")

    class Meta:
        ordering = ["train", "number"]
        unique_together = ("train", "number")

    def __str__(self):
        return f"{self.train} ตู้ {self.number}"

    def generate_seats(self):
        """Create this carriage's seats from its car type layout (see U5, U5_1, U5_2 designs)."""
        layout = self.car_type.layout
        seats = []
        if layout == "seat_2x2":
            for row in range(1, 9):
                for col in "ABCD":
                    seats.append(Seat(carriage=self, label=f"{row:02d}{col}", group=row, position=col))
        elif layout == "sleeper_open":
            n = 1
            for bay in range(1, 7):
                for side in "LR":
                    for berth, th in (("upper", "บน"), ("lower", "ล่าง")):
                        seats.append(Seat(carriage=self, label=f"{n:02d}-{th}", group=bay, position=side, berth=berth))
                    n += 1
        elif layout == "sleeper_room":
            for room in range(1, 7):
                for berth, th in (("upper", "บน"), ("lower", "ล่าง")):
                    seats.append(Seat(carriage=self, label=f"{room:02d}-{th}", group=room, berth=berth))
        Seat.objects.bulk_create(seats)


class Seat(models.Model):
    BERTHS = [("", "-"), ("upper", "เตียงบน"), ("lower", "เตียงล่าง")]
    carriage = models.ForeignKey(Carriage, on_delete=models.CASCADE, related_name="seats")
    label = models.CharField(max_length=10)
    group = models.PositiveSmallIntegerField()  # row / bay / room
    position = models.CharField(max_length=1, blank=True)  # A-D (seats) or L/R (open sleeper)
    berth = models.CharField(max_length=5, choices=BERTHS, blank=True)

    class Meta:
        ordering = ["carriage", "id"]
        unique_together = ("carriage", "label")

    def __str__(self):
        return f"ตู้ {self.carriage.number} ที่นั่ง {self.label}"

    @property
    def price(self):
        return self.carriage.car_type.price_for(self.berth)

    @property
    def berth_label(self):
        return dict(self.BERTHS).get(self.berth, "")

    @property
    def seat_note(self):
        if self.berth:
            return self.berth_label
        return "ริมหน้าต่าง" if self.position in ("A", "D") else "ทางเดิน"


class Schedule(models.Model):
    train = models.ForeignKey(Train, on_delete=models.CASCADE, related_name="schedules", verbose_name="ขบวน")
    origin = models.ForeignKey(Station, on_delete=models.PROTECT, related_name="departures", verbose_name="ต้นทาง")
    destination = models.ForeignKey(Station, on_delete=models.PROTECT, related_name="arrivals", verbose_name="ปลายทาง")
    date = models.DateField("วันที่")
    depart_time = models.TimeField("เวลาออก")
    arrive_time = models.TimeField("เวลาถึง")

    class Meta:
        ordering = ["date", "depart_time"]

    def __str__(self):
        return f"{self.train} {self.origin}→{self.destination} {self.date}"

    @property
    def departs_at(self):
        return timezone.make_aware(datetime.combine(self.date, self.depart_time))

    @property
    def overnight(self):
        return self.arrive_time <= self.depart_time

    @property
    def arrive_date(self):
        return self.date + timedelta(days=1) if self.overnight else self.date

    @property
    def duration_minutes(self):
        start = datetime.combine(self.date, self.depart_time)
        end = datetime.combine(self.arrive_date, self.arrive_time)
        return int((end - start).total_seconds() // 60)

    @property
    def duration_text(self):
        h, m = divmod(self.duration_minutes, 60)
        return f"{h} ชม. {m} นาที" if m else f"{h} ชม."


ACTIVE_STATUSES = ("held", "pending", "confirmed")


class Booking(models.Model):
    STATUSES = [
        ("held", "รอชำระเงิน"),
        ("pending", "รอยืนยัน"),
        ("confirmed", "ยืนยันแล้ว"),
        ("cancelled", "ยกเลิก"),
        ("expired", "หมดเวลา"),
    ]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bookings")
    schedule = models.ForeignKey(Schedule, on_delete=models.PROTECT, related_name="bookings")
    status = models.CharField(max_length=10, choices=STATUSES, default="held")
    total = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    hold_expires = models.DateTimeField(null=True, blank=True)
    slip = models.FileField(upload_to="slips/", blank=True)
    slip_uploaded_at = models.DateTimeField(null=True, blank=True)
    admin_note = models.TextField("บันทึกแอดมิน", blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.code

    @property
    def code(self):
        return f"B{1000 + self.id}" if self.id else "B----"

    @property
    def active_seats(self):
        return self.seats.filter(active=True).select_related("seat__carriage__car_type")

    @property
    def shown_seats(self):
        """Seats to display: active ones, or the original ones for cancelled/expired bookings."""
        qs = self.seats.select_related("seat__carriage__car_type")
        return qs.filter(active=True) if self.is_active else qs

    @property
    def is_active(self):
        return self.status in ACTIVE_STATUSES

    @property
    def can_cancel(self):
        return self.status in ACTIVE_STATUSES and self.schedule.departs_at > timezone.now()

    @property
    def seconds_left(self):
        if self.status != "held" or not self.hold_expires:
            return 0
        return max(0, int((self.hold_expires - timezone.now()).total_seconds()))

    def recalc_total(self):
        self.total = sum(s.price for s in self.seats.filter(active=True))

    def release(self, status):
        self.status = status
        self.hold_expires = None
        self.seats.update(active=False)
        self.save()

    @classmethod
    def release_expired(cls):
        """Lazy expiry: free the seats of held bookings whose hold time has passed."""
        for b in cls.objects.filter(status="held", hold_expires__lt=timezone.now()):
            b.release("expired")

    @classmethod
    def code_to_id(cls, code):
        code = (code or "").strip().upper().lstrip("B")
        return int(code) - 1000 if code.isdigit() else None


class BookingSeat(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="seats")
    schedule = models.ForeignKey(Schedule, on_delete=models.PROTECT, related_name="booked_seats")
    seat = models.ForeignKey(Seat, on_delete=models.PROTECT, related_name="bookings")
    price = models.PositiveIntegerField()
    passenger_name = models.CharField("ชื่อ-นามสกุล", max_length=150, blank=True)
    id_card = models.CharField("เลขบัตรประชาชน", max_length=20, blank=True)
    phone = models.CharField("เบอร์โทร", max_length=20, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["schedule", "seat"], condition=Q(active=True), name="one_active_booking_per_seat"),
        ]

    def __str__(self):
        return f"{self.booking.code} {self.seat}"


class ContactMessage(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    name = models.CharField("ชื่อ", max_length=150)
    email = models.EmailField("อีเมล")
    subject = models.CharField("หัวข้อ", max_length=200)
    message = models.TextField("ข้อความ")
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["is_read", "-created_at"]

    def __str__(self):
        return self.subject
