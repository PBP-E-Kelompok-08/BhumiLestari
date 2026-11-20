from django.urls import path
from . import views, api_views

app_name = "users"

urlpatterns = [
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('api/send-otp/', views.send_otp_api, name='send_otp_api'),
    path('logout/', views.logout_view, name='logout'),
    path('settings/', views.account_settings, name='account_settings'),

    # Endpoint JSON untuk aplikasi mobile (Flutter)
    path('auth/login/', api_views.login_mobile, name='login_mobile'),
    path('auth/register/', api_views.register_mobile, name='register_mobile'),
    path('auth/logout/', api_views.logout_mobile, name='logout_mobile'),
    path('auth/send-otp/', api_views.send_otp_mobile, name='send_otp_mobile'),
]
