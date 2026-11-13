from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.models import SellerProfile

from .permissions import IsSeller
from .serializers import SellerSummarySerializer
from .views import _ringkasan_penjual


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
