import uuid

from django.db import IntegrityError, transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView

from apps.users.models import SellerProfile, User

from . import integrations
from .models import FotoUlasan, UlasanToko
from .serializers import UlasanBuatSerializer, UlasanEditAPISerializer, UlasanPublikSerializer
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

    def get_permissions(self):
        permission_classes = [IsAuthenticated] if self.request.method == "POST" else [AllowAny]
        return [permission() for permission in permission_classes]

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

    def post(self, request, toko_id):
        toko = get_object_or_404(SellerProfile, pk=toko_id)
        if request.user.role != User.ROLE_BUYER:
            return Response(
                {"detail": "Hanya pembeli yang dapat menulis ulasan."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if toko.user_id == request.user.id:
            return Response(
                {"detail": "Anda tidak dapat mengulas toko sendiri."},
                status=status.HTTP_403_FORBIDDEN,
            )

        input_serializer = UlasanBuatSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data

        info_produk = integrations.ambil_produk(data["produk_id"])
        if info_produk is None:
            return Response(
                {"detail": "Produk tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if info_produk["toko_id"] != toko.id:
            return Response(
                {"detail": "Produk ini bukan milik toko tersebut."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not integrations.pernah_membeli(request.user, data["produk_id"]):
            return Response(
                {"detail": "Anda hanya dapat mengulas produk yang pernah Anda beli."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            with transaction.atomic():
                ulasan = UlasanToko.objects.create(
                    toko=toko,
                    pembeli=request.user,
                    produk_id=data["produk_id"],
                    nama_produk=info_produk["nama"],
                    rating=data["rating"],
                    komentar=data.get("komentar", ""),
                )
                for foto in data.get("foto", []):
                    FotoUlasan.objects.create(ulasan=ulasan, gambar=foto)
        except IntegrityError:
            return Response(
                {"detail": "Anda sudah mengulas produk ini."},
                status=status.HTTP_409_CONFLICT,
            )

        ulasan = (
            UlasanToko.objects.select_related("pembeli", "toko", "produk", "balasan")
            .prefetch_related("foto")
            .get(pk=ulasan.pk)
        )
        output_serializer = UlasanPublikSerializer(
            ulasan,
            context={"request": request},
        )
        return Response(
            {
                "ulasan": output_serializer.data,
                "ringkasan": ringkasan_toko(toko.id),
            },
            status=status.HTTP_201_CREATED,
        )


class DaftarUlasanSayaAPIView(APIView):
    permission_classes = [IsAuthenticated]
    pagination_class = UlasanPagination

    def get(self, request):
        queryset = (
            UlasanToko.objects.filter(pembeli=request.user)
            .select_related("pembeli", "toko", "produk", "balasan")
            .prefetch_related("foto")
            .order_by("-created_at")
        )

        paginator = self.pagination_class()
        halaman = paginator.paginate_queryset(queryset, request, view=self)
        serializer = UlasanPublikSerializer(
            halaman,
            many=True,
            context={"request": request},
        )

        return Response(
            {
                "count": paginator.page.paginator.count,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
                "ulasan": serializer.data,
            }
        )


class DetailUlasanAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, pk):
        return get_object_or_404(
            UlasanToko.objects.select_related("pembeli", "toko", "produk", "balasan")
            .prefetch_related("foto"),
            pk=pk,
        )

    def patch(self, request, pk):
        ulasan = self.get_object(pk)
        if ulasan.pembeli_id != request.user.id:
            return Response(
                {"detail": "Anda hanya dapat mengedit ulasan sendiri."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if ulasan.disembunyikan:
            return Response(
                {"detail": "Ulasan yang disembunyikan tidak dapat diedit."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not ulasan.bisa_diedit():
            return Response(
                {"detail": "Ulasan hanya dapat diedit dalam 7 hari setelah diposting."},
                status=status.HTTP_403_FORBIDDEN,
            )

        input_serializer = UlasanEditAPISerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data

        update_fields = ["diedit", "updated_at"]
        if "rating" in data:
            ulasan.rating = data["rating"]
            update_fields.append("rating")
        if "komentar" in data:
            ulasan.komentar = data["komentar"]
            update_fields.append("komentar")
        ulasan.diedit = True
        ulasan.save(update_fields=update_fields)

        output_serializer = UlasanPublikSerializer(
            ulasan,
            context={"request": request},
        )
        return Response(
            {
                "ulasan": output_serializer.data,
                "ringkasan": ringkasan_toko(ulasan.toko_id),
            }
        )

    def delete(self, request, pk):
        ulasan = self.get_object(pk)
        if ulasan.pembeli_id != request.user.id and not request.user.is_staff:
            return Response(
                {"detail": "Anda hanya dapat menghapus ulasan sendiri."},
                status=status.HTTP_403_FORBIDDEN,
            )
        ulasan.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
