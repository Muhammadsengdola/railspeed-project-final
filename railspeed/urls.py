from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("django-admin/", admin.site.urls),  # optional Django admin (not the RailSpeed admin UI)
    path("", include("booking.urls")),
]
