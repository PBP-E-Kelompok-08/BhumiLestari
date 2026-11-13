from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Cart, CartItem, Order
from .permissions import IsBuyer
from .serializers import (
    CartItemCreateSerializer,
    CartItemSerializer,
    CartItemUpdateSerializer,
    CartSelectionSerializer,
    CheckoutCreateSerializer,
    OrderSerializer,
)
from .views import PAYMENT, SHIPPING, _create_order


def _cart_items(cart):
    return cart.items.select_related("product", "product__seller").order_by(
        "-added_at"
    )


def _cart_summary(cart):
    items = list(_cart_items(cart))
    return {
        "line_count": len(items),
        "cart_count": sum(item.quantity for item in items),
        "selected_count": sum(
            item.quantity for item in items if item.is_selected
        ),
        "selected_total": sum(
            int(item.product.final_price) * item.quantity
            for item in items
            if item.is_selected
        ),
    }


class CartAPIView(APIView):
    permission_classes = [IsAuthenticated, IsBuyer]

    def get(self, request):
        cart, _ = Cart.objects.get_or_create(user=request.user)
        items = _cart_items(cart)
        serializer = CartItemSerializer(
            items,
            many=True,
            context={"request": request},
        )
        return Response(
            {
                **_cart_summary(cart),
                "items": serializer.data,
            }
        )


class CartItemCreateAPIView(APIView):
    permission_classes = [IsAuthenticated, IsBuyer]

    def post(self, request):
        input_serializer = CartItemCreateSerializer(
            data=request.data,
            context={"request": request},
        )
        input_serializer.is_valid(raise_exception=True)
        item = input_serializer.save()
        output_serializer = CartItemSerializer(
            item,
            context={"request": request},
        )
        return Response(
            {
                "item": output_serializer.data,
                **_cart_summary(item.cart),
            },
            status=status.HTTP_201_CREATED,
        )


class CartItemDetailAPIView(APIView):
    permission_classes = [IsAuthenticated, IsBuyer]

    def get_object(self, request, item_id):
        return get_object_or_404(
            CartItem.objects.select_related("product", "product__seller"),
            pk=item_id,
            cart__user=request.user,
        )

    def patch(self, request, item_id):
        item = self.get_object(request, item_id)
        input_serializer = CartItemUpdateSerializer(
            item,
            data=request.data,
            partial=True,
        )
        input_serializer.is_valid(raise_exception=True)
        item = input_serializer.save()
        output_serializer = CartItemSerializer(
            item,
            context={"request": request},
        )
        return Response(
            {
                "item": output_serializer.data,
                **_cart_summary(item.cart),
            }
        )

    def delete(self, request, item_id):
        item = self.get_object(request, item_id)
        cart = item.cart
        deleted_id = item.pk
        item.delete()
        return Response(
            {
                "detail": "Item berhasil dihapus dari keranjang.",
                "deleted_id": deleted_id,
                **_cart_summary(cart),
            }
        )


class CartSelectionAPIView(APIView):
    permission_classes = [IsAuthenticated, IsBuyer]

    def patch(self, request):
        serializer = CartSelectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        selected_ids = serializer.validated_data["selected_ids"]
        cart, _ = Cart.objects.get_or_create(user=request.user)
        cart.items.filter(pk__in=selected_ids).update(is_selected=True)
        cart.items.exclude(pk__in=selected_ids).update(is_selected=False)
        return Response(_cart_summary(cart))


class CheckoutSummaryAPIView(APIView):
    permission_classes = [IsAuthenticated, IsBuyer]

    def get(self, request):
        shipping_method = request.query_params.get(
            "shipping_method",
            "reguler",
        )
        if shipping_method not in SHIPPING:
            return Response(
                {"shipping_method": ["Metode pengiriman tidak valid."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cart, _ = Cart.objects.get_or_create(user=request.user)
        selected_items = list(_cart_items(cart).filter(is_selected=True))
        items_total = sum(
            int(item.product.final_price) * item.quantity
            for item in selected_items
        )
        item_count = sum(item.quantity for item in selected_items)
        store_count = len(
            {item.product.seller_id for item in selected_items}
        )
        shipping_cost = SHIPPING[shipping_method][1] * store_count
        serializer = CartItemSerializer(
            selected_items,
            many=True,
            context={"request": request},
        )
        return Response(
            {
                "recipient_defaults": {
                    "recipient_name": request.user.full_name or "",
                    "phone": request.user.phone or "",
                    "shipping_address": request.user.address or "",
                },
                "shipping_method": shipping_method,
                "shipping_options": [
                    {"key": key, "label": value[0], "cost": value[1]}
                    for key, value in SHIPPING.items()
                ],
                "payment_options": [
                    {"key": key, "label": value}
                    for key, value in PAYMENT.items()
                ],
                "items_total": items_total,
                "item_count": item_count,
                "store_count": store_count,
                "shipping_cost": shipping_cost,
                "grand_total": items_total + shipping_cost,
                "items": serializer.data,
            }
        )


class CheckoutCreateAPIView(APIView):
    permission_classes = [IsAuthenticated, IsBuyer]

    def post(self, request):
        serializer = CheckoutCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cart, _ = Cart.objects.get_or_create(user=request.user)
        if not cart.items.filter(is_selected=True).exists():
            return Response(
                {"detail": "Tidak ada barang yang dipilih."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data
        try:
            orders = _create_order(
                request.user,
                data["recipient_name"],
                data["phone"],
                data["shipping_address"],
                data["shipping_method"],
                data["payment_method"],
            )
        except ValueError as error:
            return Response(
                {"detail": str(error)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        order_ids = [order.pk for order in orders]
        created_orders = (
            Order.objects.filter(pk__in=order_ids)
            .select_related("seller")
            .prefetch_related("items")
            .order_by("id")
        )
        output_serializer = OrderSerializer(created_orders, many=True)
        return Response(
            {
                "count": len(order_ids),
                "orders": output_serializer.data,
            },
            status=status.HTTP_201_CREATED,
        )
