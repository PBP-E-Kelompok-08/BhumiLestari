from django.db import transaction
from rest_framework import serializers

from apps.products.models import Product

from .models import Cart, CartItem, Order, OrderItem


class CartSellerSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    store_name = serializers.CharField(read_only=True)


class CartProductSerializer(serializers.ModelSerializer):
    seller = CartSellerSerializer(read_only=True)
    price = serializers.IntegerField(read_only=True)
    final_price = serializers.IntegerField(read_only=True)
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "price",
            "discount",
            "final_price",
            "stock",
            "status",
            "image_url",
            "seller",
        ]
        read_only_fields = fields

    def get_image_url(self, product):
        if not product.image:
            return None
        try:
            url = product.image.url
        except ValueError:
            return None
        request = self.context.get("request")
        return request.build_absolute_uri(url) if request else url


class CartItemSerializer(serializers.ModelSerializer):
    product = CartProductSerializer(read_only=True)
    line_total = serializers.SerializerMethodField()

    class Meta:
        model = CartItem
        fields = [
            "id",
            "product",
            "quantity",
            "is_selected",
            "line_total",
            "added_at",
        ]
        read_only_fields = fields

    def get_line_total(self, item):
        return int(item.product.final_price) * item.quantity


class CartItemCreateSerializer(serializers.Serializer):
    product_id = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.filter(status="verified"),
        source="product",
    )
    quantity = serializers.IntegerField(min_value=1, default=1)

    @transaction.atomic
    def create(self, validated_data):
        user = self.context["request"].user
        requested_product = validated_data["product"]
        product = Product.objects.select_for_update().get(pk=requested_product.pk)
        cart, _ = Cart.objects.get_or_create(user=user)
        item = CartItem.objects.select_for_update().filter(
            cart=cart,
            product=product,
        ).first()
        current_quantity = item.quantity if item else 0
        new_quantity = current_quantity + validated_data["quantity"]

        if product.status != "verified":
            raise serializers.ValidationError(
                {"product_id": "Produk sudah tidak tersedia."}
            )
        if new_quantity > product.stock:
            raise serializers.ValidationError(
                {"quantity": f"Stok tidak mencukupi (sisa {product.stock})."}
            )

        if item is None:
            item = CartItem.objects.create(
                cart=cart,
                product=product,
                quantity=new_quantity,
            )
        else:
            item.quantity = new_quantity
            item.save(update_fields=["quantity"])
        return item


class CartItemUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CartItem
        fields = ["quantity", "is_selected"]
        extra_kwargs = {
            "quantity": {"required": False, "min_value": 1},
            "is_selected": {"required": False},
        }

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError(
                "Kirim quantity atau is_selected yang ingin diperbarui."
            )
        quantity = attrs.get("quantity")
        if quantity is not None and quantity > self.instance.product.stock:
            raise serializers.ValidationError(
                {
                    "quantity": (
                        f"Stok tidak mencukupi "
                        f"(sisa {self.instance.product.stock})."
                    )
                }
            )
        return attrs


class CartSelectionSerializer(serializers.Serializer):
    selected_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=True,
    )


class CheckoutCreateSerializer(serializers.Serializer):
    recipient_name = serializers.CharField(max_length=100)
    phone = serializers.CharField(max_length=20)
    shipping_address = serializers.CharField()
    shipping_method = serializers.ChoiceField(choices=Order.SHIPPING_CHOICES)
    payment_method = serializers.ChoiceField(choices=Order.PAYMENT_CHOICES)


class OrderItemSerializer(serializers.ModelSerializer):
    product_id = serializers.UUIDField(read_only=True, allow_null=True)
    line_total = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = [
            "id",
            "product_id",
            "product_name",
            "price",
            "quantity",
            "line_total",
        ]
        read_only_fields = fields

    def get_line_total(self, item):
        return item.price * item.quantity


class OrderSerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()
    total_price = serializers.SerializerMethodField()
    shipping_method_display = serializers.CharField(
        source="get_shipping_method_display",
        read_only=True,
    )
    payment_method_display = serializers.CharField(
        source="get_payment_method_display",
        read_only=True,
    )
    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    class Meta:
        model = Order
        fields = [
            "id",
            "store_name",
            "recipient_name",
            "phone",
            "shipping_address",
            "shipping_method",
            "shipping_method_display",
            "payment_method",
            "payment_method_display",
            "shipping_cost",
            "total_price",
            "status",
            "status_display",
            "created_at",
            "items",
        ]
        read_only_fields = fields

    def get_items(self, order):
        items = list(order.items.all())
        request = self.context.get("request")
        user = request.user if request else None
        if user and getattr(user, "role", None) == "seller":
            if not order.seller_id or order.seller.user_id != user.id:
                items = [
                    item
                    for item in items
                    if item.product
                    and item.product.seller.user_id == user.id
                ]
        return OrderItemSerializer(items, many=True).data

    def get_total_price(self, order):
        request = self.context.get("request")
        user = request.user if request else None
        if user and getattr(user, "role", None) == "seller":
            return sum(
                item["line_total"]
                for item in self.get_items(order)
            )
        return order.total_price


class OrderStatusActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["ship", "complete"])
