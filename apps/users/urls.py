from django.urls import path
from . import views

from apps.users.views import *

app_name = "users"

urlpatterns = [
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('api/send-otp/', views.send_otp_api, name='send_otp_api'),
]