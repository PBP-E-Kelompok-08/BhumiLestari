from django.db import transaction
from rest_framework import serializers

from apps.products.models import Product

from .models import Cart, CartItem


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
