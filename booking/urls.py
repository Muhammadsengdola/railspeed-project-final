from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import ai_chat, api
from . import manage_views as m
from . import views as v

router = DefaultRouter()
router.register("stations", api.StationViewSet)
router.register("car-types", api.CarTypeViewSet)
router.register("trains", api.TrainViewSet)
router.register("schedules", api.ScheduleViewSet, basename="schedule")
router.register("bookings", api.BookingViewSet, basename="booking")

urlpatterns = [
    path("", v.home, name="home"),
    path("search/", v.search, name="search"),
    path("trip/<int:schedule_id>/seats/", v.seats, name="seats"),
    path("booking/<int:booking_id>/passengers/", v.passengers, name="passengers"),
    path("booking/<int:booking_id>/pay/", v.pay, name="pay"),
    path("booking/<int:booking_id>/", v.ticket, name="ticket"),
    path("booking/<int:booking_id>/cancel/", v.cancel_booking, name="cancel_booking"),
    path("booking/<int:booking_id>/slip/", v.slip, name="slip"),
    path("my-bookings/", v.my_bookings, name="my_bookings"),
    path("login/", v.login_view, name="login"),
    path("register/", v.register, name="register"),
    path("logout/", v.logout_view, name="logout"),
    path("profile/", v.profile, name="profile"),
    path("contact/", v.contact, name="contact"),
    path("api/chat/", ai_chat.api_chat, name="api_chat"),
    # REST API (browse it at /api/)
    path("api/auth/token/", api.obtain_token, name="api_token"),
    path("api/me/", api.me, name="api_me"),
    path("api/", include(router.urls)),
    # admin side
    path("manage/login/", m.manage_login, name="manage_login"),
    path("manage/logout/", m.manage_logout, name="manage_logout"),
    path("manage/", m.dashboard, name="manage_dashboard"),
    path("manage/bookings/", m.bookings, name="manage_bookings"),
    path("manage/bookings/<int:booking_id>/status/", m.booking_status, name="manage_booking_status"),
    path("manage/bookings/<int:booking_id>/edit/", m.booking_edit, name="manage_booking_edit"),
    path("manage/trains/<int:train_id>/cars/", m.train_cars, name="manage_train_cars"),
    path("manage/trains/<int:train_id>/cars/<int:car_id>/delete/", m.train_car_delete, name="manage_train_car_delete"),
    path("manage/users/", m.users, name="manage_users"),
    path("manage/users/<int:user_id>/toggle/", m.user_toggle, name="manage_user_toggle"),
    path("manage/admins/", m.admins, name="manage_admins"),
    path("manage/admins/<int:user_id>/delete/", m.admin_delete, name="manage_admin_delete"),
    path("manage/messages/", m.contact_messages, name="manage_messages"),
    path("manage/messages/<int:pk>/read/", m.message_read, name="manage_message_read"),
    path("manage/<str:kind>/", m.crud_list, name="manage_crud"),
    path("manage/<str:kind>/<int:pk>/delete/", m.crud_delete, name="manage_crud_delete"),
]