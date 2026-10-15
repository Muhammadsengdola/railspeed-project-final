"""python manage.py seed  — create demo data (stations, trains, carriages, schedules, users, real bookings)."""
import random
from datetime import datetime, time, timedelta

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from booking.models import Booking, BookingSeat, CarType, Carriage, ContactMessage, Profile, Schedule, Seat, Station, Train

STATIONS = [
    ("กรุงเทพอภิวัฒน์", "กรุงเทพมหานคร"), ("อยุธยา", "พระนครศรีอยุธยา"), ("พิษณุโลก", "พิษณุโลก"),
    ("ลำปาง", "ลำปาง"), ("เชียงใหม่", "เชียงใหม่"), ("หัวหิน", "ประจวบคีรีขันธ์"),
    ("นครราชสีมา", "นครราชสีมา"), ("ขอนแก่น", "ขอนแก่น"), ("อุบลราชธานี", "อุบลราชธานี"), ("ชุมทางหาดใหญ่", "สงขลา"),
]

CAR_TYPES = [
    # name, layout, price, upper diff, first class
    ("นั่งธรรมดา", "seat_2x2", 441, 0, False),
    ("นั่งปรับอากาศ ชั้น 1", "seat_2x2", 750, 0, True),
    ("นอนชั้น 2", "sleeper_open", 900, -100, False),
    ("นอนชั้น 1 (ห้องคู่)", "sleeper_room", 1500, -100, True),
]

# number, type, carriages (car type index), route, depart, arrive
TRAINS = [
    ("EXP 9", "ด่วนพิเศษ", [0, 0, 1, 2, 3], ("กรุงเทพอภิวัฒน์", "เชียงใหม่"), "08:30", "19:15"),
    ("SPR 13", "ด่วน", [0, 0, 1, 1], ("กรุงเทพอภิวัฒน์", "เชียงใหม่"), "10:05", "21:40"),
    ("NT 7", "ด่วนพิเศษ", [1, 2, 2, 3], ("กรุงเทพอภิวัฒน์", "เชียงใหม่"), "18:20", "07:05"),
    ("EXP 10", "ด่วนพิเศษ", [0, 0, 1, 2, 3], ("เชียงใหม่", "กรุงเทพอภิวัฒน์"), "08:50", "19:25"),
    ("SPR 43", "ด่วน", [0, 0, 0, 1], ("กรุงเทพอภิวัฒน์", "หัวหิน"), "08:05", "11:55"),
    ("EXP 21", "ด่วนพิเศษ", [0, 1, 2, 3], ("กรุงเทพอภิวัฒน์", "อุบลราชธานี"), "20:30", "07:10"),
]

USERS = [
    ("สมชาย", "ใจดี", "081-234-5678"), ("มาลี", "สุขใจ", "089-111-2222"), ("ปรีชา", "แก้วตา", "086-555-0101"),
    ("สุดา", "รักษ์ดี", "082-333-4444"), ("วิชัย", "ทองมา", "087-222-1111"), ("นภา", "ศรีสุข", "084-666-7777"),
    ("อนันต์", "มั่นคง", "085-888-9999"), ("พิมพ์ชนก", "แสงทอง", "083-121-3434"), ("ธนกร", "บุญมี", "080-909-1010"),
    ("กมลวรรณ", "ใจงาม", "092-456-7890"),
]
COMPANIONS = ["สมหญิง ใจดี", "ด.ช. ภูมิ", "นิดา พรมมา", "ชาตรี ศรีวงศ์", "อรุณี แก้วใส", "ณัฐพล รุ่งเรือง"]

SLIP_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="360" height="560" viewBox="0 0 360 560">
<rect width="360" height="560" rx="18" fill="#f2f4f7"/><rect x="20" y="20" width="320" height="520" rx="14" fill="#fff" stroke="#d9dee6"/>
<circle cx="180" cy="95" r="34" fill="#2e8b57"/><path d="M164 96l11 11 22-24" stroke="#fff" stroke-width="7" fill="none" stroke-linecap="round"/>
<text x="180" y="170" font-family="sans-serif" font-size="20" text-anchor="middle" fill="#14202e" font-weight="bold">โอนเงินสำเร็จ</text>
<text x="180" y="200" font-family="sans-serif" font-size="14" text-anchor="middle" fill="#667085">สลิปตัวอย่างจากข้อมูล seed</text>
<text x="180" y="270" font-family="sans-serif" font-size="34" text-anchor="middle" fill="#14304d" font-weight="bold">{amount} บาท</text>
<text x="50" y="340" font-family="sans-serif" font-size="14" fill="#667085">จาก</text><text x="310" y="340" font-family="sans-serif" font-size="14" text-anchor="end" fill="#14202e">{name}</text>
<text x="50" y="375" font-family="sans-serif" font-size="14" fill="#667085">ไปยัง</text><text x="310" y="375" font-family="sans-serif" font-size="14" text-anchor="end" fill="#14202e">RailSpeed (พร้อมเพย์)</text>
<text x="50" y="410" font-family="sans-serif" font-size="14" fill="#667085">อ้างอิง</text><text x="310" y="410" font-family="sans-serif" font-size="14" text-anchor="end" fill="#14202e">{code}</text>
<text x="50" y="445" font-family="sans-serif" font-size="14" fill="#667085">เวลา</text><text x="310" y="445" font-family="sans-serif" font-size="14" text-anchor="end" fill="#14202e">{when}</text>
</svg>"""


def t(s):
    h, m = s.split(":")
    return time(int(h), int(m))


class Command(BaseCommand):
    help = "Create RailSpeed demo data. Use --reset to wipe existing data first."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="delete all existing RailSpeed data and users first")

    @transaction.atomic
    def handle(self, *args, **opts):
        if opts["reset"]:
            BookingSeat.objects.all().delete()
            Booking.objects.all().delete()
            ContactMessage.objects.all().delete()
            Schedule.objects.all().delete()
            Seat.objects.all().delete()
            Carriage.objects.all().delete()
            Train.objects.all().delete()
            CarType.objects.all().delete()
            Station.objects.all().delete()
            User.objects.all().delete()
        elif Station.objects.exists():
            self.stdout.write(self.style.WARNING("มีข้อมูลอยู่แล้ว ใช้ --reset ถ้าต้องการล้างแล้วสร้างใหม่"))
            return

        rng = random.Random(2026)
        stations = {n: Station.objects.create(name=n, province=p) for n, p in STATIONS}
        types = [CarType.objects.create(name=n, layout=l, base_price=p, upper_berth_diff=d, is_first_class=f) for n, l, p, d, f in CAR_TYPES]

        today = timezone.localdate()
        trains = {}
        for number, ttype, cars, (a, b), dep, arr in TRAINS:
            tr = Train.objects.create(number=number, train_type=ttype)
            for i, ti in enumerate(cars, start=1):
                Carriage.objects.create(train=tr, number=i, car_type=types[ti]).generate_seats()
            trains[number] = tr
            Schedule.objects.bulk_create([
                Schedule(train=tr, origin=stations[a], destination=stations[b], date=today + timedelta(days=d), depart_time=t(dep), arrive_time=t(arr))
                for d in range(-5, 31)
            ])

        # accounts
        admin = User.objects.create_user("admin@railspeed.th", "admin@railspeed.th", "Admin1234!", first_name="ผู้ดูแล", last_name="หลัก", is_staff=True, is_superuser=True)
        Profile.objects.create(user=admin, phone="02-000-0000")
        tester = User.objects.create_user("test@railspeed.th", "test@railspeed.th", "Test1234!", first_name="ผู้ทดสอบ", last_name="ระบบ")
        Profile.objects.create(user=tester, phone="099-999-9999")
        users = []
        for i, (first, last, phone) in enumerate(USERS, start=1):
            email = f"user{i:02d}@example.com"
            u = User.objects.create_user(email, email, "User1234!", first_name=first, last_name=last)
            u.date_joined = timezone.now() - timedelta(days=30 - i)
            u.save()
            Profile.objects.create(user=u, phone=phone)
            users.append(u)

        def sched(train, day):
            return Schedule.objects.get(train=trains[train], date=today + timedelta(days=day))

        def book(user, schedule, count, status, created_days_ago, car_numbers=None):
            free = list(
                Seat.objects.filter(carriage__train=schedule.train, **({"carriage__number__in": car_numbers} if car_numbers else {}))
                .exclude(bookings__schedule=schedule, bookings__active=True)
                .select_related("carriage__car_type")
            )
            # keep a booking inside one carriage, like a real group would
            by_car = {}
            for s in free:
                by_car.setdefault(s.carriage_id, []).append(s)
            car_seats = rng.choice([v for v in by_car.values() if len(v) >= count])
            start = rng.randrange(0, len(car_seats) - count + 1)
            chosen = car_seats[start:start + count]
            created = timezone.now() - timedelta(days=created_days_ago, hours=rng.randint(0, 10), minutes=rng.randint(0, 59))
            b = Booking.objects.create(user=user, schedule=schedule, status=status, created_at=created)
            active = status in ("pending", "confirmed")
            for k, seat in enumerate(chosen):
                BookingSeat.objects.create(
                    booking=b, schedule=schedule, seat=seat, price=seat.price, active=active,
                    passenger_name=user.get_full_name() if k == 0 else rng.choice(COMPANIONS),
                    id_card="".join(str(rng.randint(0, 9)) for _ in range(13)),
                    phone=user.profile.phone,
                )
            b.total = sum(s.price for s in chosen)
            if status in ("pending", "confirmed", "cancelled"):
                svg = SLIP_SVG.format(amount=f"{b.total:,}", name=user.get_full_name(), code=b.code, when=timezone.localtime(created).strftime("%d/%m/%Y %H:%M"))
                b.slip.save(f"seed_{b.code}.svg", ContentFile(svg.encode("utf-8")), save=False)
                b.slip_uploaded_at = created + timedelta(minutes=8)
            if status == "cancelled":
                b.admin_note = "ผู้โดยสารขอยกเลิกทางโทรศัพท์"
            b.save()
            return b

        # 10 users with real bookings: the busy demo trip is EXP 9 in 7 days
        plan = [
            (0, "EXP 9", 7, 2, "pending", 0, [1]),
            (1, "NT 7", 7, 1, "confirmed", 1, [2]),
            (2, "SPR 13", 7, 1, "confirmed", 1, None),
            (3, "EXP 9", 7, 3, "confirmed", 2, [1]),
            (4, "EXP 9", 7, 2, "confirmed", 3, [4]),
            (5, "EXP 9", 7, 2, "pending", 0, [5]),
            (6, "EXP 9", 7, 4, "confirmed", 4, [2]),
            (7, "EXP 9", 7, 1, "pending", 0, [3]),
            (8, "SPR 43", 3, 2, "confirmed", 5, None),
            (9, "EXP 9", 7, 2, "cancelled", 6, [3]),
        ]
        for ui, train, day, n, status, ago, cars in plan:
            book(users[ui], sched(train, day), n, status, ago, cars)
        # extra history so every tab and the dashboard have data
        book(users[0], sched("EXP 10", -3), 1, "confirmed", 6)
        book(users[1], sched("EXP 21", -2), 2, "confirmed", 5)
        book(users[3], sched("EXP 9", 1), 2, "confirmed", 2, [4])
        book(users[4], sched("NT 7", 7), 2, "confirmed", 1, [4])
        book(users[5], sched("EXP 9", 7), 4, "confirmed", 3, [1])
        book(users[6], sched("EXP 9", 7), 2, "confirmed", 2, [5])
        book(users[8], sched("EXP 9", 7), 3, "confirmed", 1, [3])
        book(users[2], sched("EXP 9", 7), 2, "confirmed", 0, [2])

        ContactMessage.objects.create(user=users[1], name="มาลี สุขใจ", email=users[1].email, subject="ขอเปลี่ยนวันเดินทาง",
                                      message="อยากเลื่อนการเดินทางของการจองไปอีก 1 วัน ทำได้ไหมคะ", created_at=timezone.now() - timedelta(hours=5))
        ContactMessage.objects.create(user=users[2], name="ปรีชา แก้วตา", email=users[2].email, subject="ชำระเงินแล้วสถานะไม่เปลี่ยน",
                                      message="โอนไปเมื่อเช้าแล้ว สถานะยังขึ้นรอยืนยันอยู่ครับ", created_at=timezone.now() - timedelta(hours=2))

        demo = sched("EXP 9", 7)
        self.stdout.write(self.style.SUCCESS("สร้างข้อมูลตัวอย่างเรียบร้อย"))
        self.stdout.write(f"  สถานี {Station.objects.count()} · ขบวน {Train.objects.count()} · ตู้ {Carriage.objects.count()} · ที่นั่ง {Seat.objects.count()} · รอบเดินทาง {Schedule.objects.count()}")
        self.stdout.write(f"  การจอง {Booking.objects.count()} รายการ · ที่นั่งที่ถูกจองอยู่ {BookingSeat.objects.filter(active=True).count()} ที่")
        self.stdout.write(f"  รอบที่คนจองเยอะ: EXP 9 กรุงเทพอภิวัฒน์ → เชียงใหม่ วันที่ {demo.date}")
        self.stdout.write("  แอดมิน   admin@railspeed.th / Admin1234!   (เข้าที่ /manage/)")
        self.stdout.write("  ผู้ทดสอบ  test@railspeed.th  / Test1234!")
        self.stdout.write("  ผู้ใช้ 10 คน user01@example.com ... user10@example.com / User1234!")
