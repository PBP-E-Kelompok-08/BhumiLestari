from django.urls import path
from . import views

app_name = "users"

urlpatterns = [
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('api/send-otp/', views.send_otp_api, name='send_otp_api'),
    path('logout/', views.logout_view, name='logout'),
    path('settings/', views.account_settings, name='account_settings'),
]