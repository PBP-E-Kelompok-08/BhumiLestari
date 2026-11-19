from django.urls import path

from .api_views import (
    AccountDeleteAPIView,
    LoginAPIView,
    LogoutAPIView,
    PasswordChangeAPIView,
    PaymentMethodDetailAPIView,
    PaymentMethodListCreateAPIView,
    ProfileAPIView,
    RegisterAPIView,
    SendOTPAPIView,
)


app_name = "users_api"

urlpatterns = [
    path("otp/send/", SendOTPAPIView.as_view(), name="send-otp"),
    path("register/", RegisterAPIView.as_view(), name="register"),
    path("login/", LoginAPIView.as_view(), name="login"),
    path("logout/", LogoutAPIView.as_view(), name="logout"),
    path("profile/", ProfileAPIView.as_view(), name="profile"),
    path("password/", PasswordChangeAPIView.as_view(), name="password"),
    path(
        "payment-methods/",
        PaymentMethodListCreateAPIView.as_view(),
        name="payment-methods",
    ),
    path(
        "payment-methods/<int:payment_id>/",
        PaymentMethodDetailAPIView.as_view(),
        name="payment-method-detail",
    ),
    path(
        "account/delete/",
        AccountDeleteAPIView.as_view(),
        name="account-delete",
    ),
]

