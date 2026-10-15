from django.contrib import admin

from .models import Booking, BookingSeat, CarType, Carriage, ContactMessage, Profile, Schedule, Station, Train

for model in (Station, Train, CarType, Carriage, Schedule, Booking, BookingSeat, ContactMessage, Profile):
    admin.site.register(model)
