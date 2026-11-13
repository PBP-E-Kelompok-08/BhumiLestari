from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.models import SellerProfile
from apps.reviews.services import laporan_ulasan

from .permissions import IsSeller, IsSellerOrAdmin
from .serializers import (
    SalesReportQuerySerializer,
    SalesReportSerializer,
    SellerSummarySerializer,
)
from .views import _ringkasan_penjual, _statistik_penjualan


class SellerSummaryAPIView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]

    def get(self, request):
        profile = get_object_or_404(SellerProfile, user=request.user)
        summary = _ringkasan_penjual(profile)
        serializer = SellerSummarySerializer({
            "store_id": profile.pk,
            "store_name": profile.store_name,
            "product_count": summary["jumlah_produk"],
            "order_count": summary["jumlah_pesanan"],
            "monthly_revenue": summary["pendapatan_bulan"],
            "reviews": summary["ulasan"],
            "revenue_chart": summary["grafik"],
            "best_selling_products": summary["produk_terlaris"],
        })
        return Response(serializer.data)


class SalesReportAPIView(APIView):
    permission_classes = [IsAuthenticated, IsSellerOrAdmin]

    def get(self, request):
        query_serializer = SalesReportQuerySerializer(
            data={"period": request.query_params.get("period", "bulanan")}
        )
        query_serializer.is_valid(raise_exception=True)
        period = query_serializer.validated_data["period"]

        role = "admin" if request.user.is_superuser else "seller"
        profile = None
        if role == "seller":
            profile = get_object_or_404(SellerProfile, user=request.user)

        sales = _statistik_penjualan(profile, period)
        serializer = SalesReportSerializer({
            "role": role,
            "period": sales["periode"],
            "revenue": sales["pendapatan"],
            "average_order_value": sales["rata_pesanan"],
            "growth": sales["pertumbuhan"],
            "best_selling_products": sales["produk_terlaris"],
            "reviews": laporan_ulasan(
                role,
                toko=profile,
                periode=period,
            ),
        })
        return Response(serializer.data)
