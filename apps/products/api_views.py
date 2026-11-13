from django.db.models import Avg, Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import EcoFeature, Product
from .permissions import IsSeller
from .serializers import (
    EcoFeatureSerializer,
    ProductCreateSerializer,
    ProductPublikSerializer,
    ProductSellerSerializer,
    ProductUpdateSerializer,
)
from .views import kirim_ke_api


URUTAN_PRODUK = {
    "terbaru": ("-created_at",),
    "termurah": ("price", "-created_at"),
    "termahal": ("-price", "-created_at"),
    "rating": ("-rating", "-review_count", "-created_at"),
}


def _produk_dengan_detail(queryset):
    return (
        queryset
        .select_related("seller")
        .prefetch_related("eco_features")
        .annotate(
            rating=Avg(
                "ulasan__rating",
                filter=Q(ulasan__disembunyikan=False),
            ),
            review_count=Count(
                "ulasan",
                filter=Q(ulasan__disembunyikan=False),
                distinct=True,
            ),
        )
    )


def _produk_publik():
    return _produk_dengan_detail(Product.objects.filter(status="verified"))


class ProductPagination(PageNumberPagination):
    page_size = 12
    page_size_query_param = "page_size"
    max_page_size = 50

    def get_paginated_response(self, data):
        return Response(
            {
                "count": self.page.paginator.count,
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
                "products": data,
            }
        )


class ProductListAPIView(APIView):
    permission_classes = [AllowAny]
    pagination_class = ProductPagination

    def get(self, request):
        products = _produk_publik()

        query = request.query_params.get("q", "").strip()
        if query:
            products = products.filter(
                Q(name__icontains=query)
                | Q(description__icontains=query)
                | Q(materials__icontains=query)
            )

        category = request.query_params.get("category", "").strip()
        if category:
            products = products.filter(category=category)

        seller_id = request.query_params.get("seller_id", "").strip()
        if seller_id:
            products = (
                products.filter(seller_id=int(seller_id))
                if seller_id.isdigit()
                else products.none()
            )

        eco_feature = request.query_params.get("eco_feature", "").strip()
        if eco_feature:
            products = products.filter(
                eco_features__name__iexact=eco_feature
            ).distinct()

        urutan = request.query_params.get("urut", "terbaru")
        products = products.order_by(*URUTAN_PRODUK.get(urutan, URUTAN_PRODUK["terbaru"]))

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(products, request, view=self)
        serializer = ProductPublikSerializer(
            page,
            many=True,
            context={"request": request},
        )
        return paginator.get_paginated_response(serializer.data)


class ProductDetailAPIView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, product_id):
        product = get_object_or_404(_produk_publik(), pk=product_id)
        serializer = ProductPublikSerializer(
            product,
            context={"request": request},
        )
        return Response({"data": serializer.data})


class ProductMineAPIView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]
    pagination_class = ProductPagination

    def get(self, request):
        products = _produk_dengan_detail(
            Product.objects.filter(seller=request.user.seller_profile)
        )

        product_status = request.query_params.get("status", "").strip()
        valid_statuses = {choice[0] for choice in Product.STATUS_CHOICES}
        if product_status:
            products = (
                products.filter(status=product_status)
                if product_status in valid_statuses
                else products.none()
            )

        query = request.query_params.get("q", "").strip()
        if query:
            products = products.filter(
                Q(name__icontains=query)
                | Q(description__icontains=query)
                | Q(materials__icontains=query)
            )

        products = products.order_by("-created_at")
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(products, request, view=self)
        serializer = ProductSellerSerializer(
            page,
            many=True,
            context={"request": request},
        )
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        input_serializer = ProductCreateSerializer(
            data=request.data,
            context={"seller": request.user.seller_profile},
        )
        input_serializer.is_valid(raise_exception=True)
        product = input_serializer.save()

        mock_api_synced = kirim_ke_api(product)
        product = get_object_or_404(
            _produk_dengan_detail(Product.objects.all()),
            pk=product.pk,
        )
        output_serializer = ProductSellerSerializer(
            product,
            context={"request": request},
        )
        return Response(
            {
                "product": output_serializer.data,
                "mock_api_synced": mock_api_synced,
            },
            status=status.HTTP_201_CREATED,
        )


class ProductMineDetailAPIView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]

    def get_object(self, request, product_id):
        return get_object_or_404(
            _produk_dengan_detail(
                Product.objects.filter(seller=request.user.seller_profile)
            ),
            pk=product_id,
        )

    def get(self, request, product_id):
        product = self.get_object(request, product_id)
        serializer = ProductSellerSerializer(
            product,
            context={"request": request},
        )
        return Response({"product": serializer.data})

    def patch(self, request, product_id):
        product = self.get_object(request, product_id)
        input_serializer = ProductUpdateSerializer(
            product,
            data=request.data,
            partial=True,
        )
        input_serializer.is_valid(raise_exception=True)
        product = input_serializer.save()

        verification_resubmitted = input_serializer.verification_resubmitted
        mock_api_synced = (
            kirim_ke_api(product) if verification_resubmitted else None
        )
        product = self.get_object(request, product_id)
        output_serializer = ProductSellerSerializer(
            product,
            context={"request": request},
        )
        return Response(
            {
                "product": output_serializer.data,
                "verification_resubmitted": verification_resubmitted,
                "mock_api_synced": mock_api_synced,
            }
        )

    def delete(self, request, product_id):
        product = self.get_object(request, product_id)
        deleted_id = str(product.pk)
        product.delete()
        return Response(
            {
                "detail": "Produk berhasil dihapus.",
                "deleted_id": deleted_id,
            }
        )


class EcoFeatureListAPIView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        features = EcoFeature.objects.order_by("name")
        serializer = EcoFeatureSerializer(features, many=True)
        return Response(
            {
                "count": features.count(),
                "eco_features": serializer.data,
            }
        )
