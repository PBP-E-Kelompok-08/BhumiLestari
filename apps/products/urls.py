from django.urls import path, include
from apps.products.views import *

from django.conf import settings
from django.conf.urls.static import static

app_name = "products"

urlpatterns = [

] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)