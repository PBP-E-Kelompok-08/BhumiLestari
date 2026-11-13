from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Cart, CartItem
from .permissions import IsBuyer
from .serializers import (
    CartItemCreateSerializer,
    CartItemSerializer,
    CartItemUpdateSerializer,
    CartSelectionSerializer,
)


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
