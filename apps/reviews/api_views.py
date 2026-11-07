import uuid

from django.db.models import Count
from django.shortcuts import get_object_or_404
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.models import SellerProfile

from .models import UlasanToko
from .serializers import UlasanPublikSerializer
from .services import ringkasan_toko


URUTAN = {
    "terbaru": ("-created_at",),
    "tertinggi": ("-rating", "-created_at"),
    "terendah": ("rating", "-created_at"),
}


class UlasanPagination(PageNumberPagination):
    page_size = 5
    page_size_query_param = "page_size"
    max_page_size = 50


class DaftarUlasanTokoAPIView(APIView):
    permission_classes = [AllowAny]
    pagination_class = UlasanPagination

    def get(self, request, toko_id):
        toko = get_object_or_404(SellerProfile, pk=toko_id)
        queryset = (
            UlasanToko.objects.tampil()
            .filter(toko=toko)
            .select_related("pembeli", "toko", "produk", "balasan")
            .prefetch_related("foto")
        )

        rating = request.query_params.get("rating")
        if rating in {"1", "2", "3", "4", "5"}:
            queryset = queryset.filter(rating=int(rating))
        if request.query_params.get("foto") == "1":
            queryset = queryset.annotate(jumlah_foto_db=Count("foto")).filter(jumlah_foto_db__gt=0)

        produk = request.query_params.get("produk")
        try:
            produk_id = uuid.UUID(produk) if produk else None
        except (TypeError, ValueError):
            produk_id = None
        if produk_id:
            queryset = queryset.filter(produk_id=produk_id)

        if request.query_params.get("terverifikasi") == "1":
            queryset = queryset.filter(produk__status="verified")

        urutan = request.query_params.get("urut", "terbaru")
        queryset = queryset.order_by(*URUTAN.get(urutan, URUTAN["terbaru"]))

        paginator = self.pagination_class()
        halaman = paginator.paginate_queryset(queryset, request, view=self)
        serializer = UlasanPublikSerializer(
            halaman,
            many=True,
            context={"request": request},
        )

        return Response(
            {
                "toko": {"id": toko.id, "nama": toko.store_name},
                "ringkasan": ringkasan_toko(toko.id),
                "count": paginator.page.paginator.count,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
                "ulasan": serializer.data,
            }
        )
