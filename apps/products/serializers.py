from rest_framework import serializers

from .models import EcoFeature, Product


class EcoFeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = EcoFeature
        fields = ["id", "name"]
        read_only_fields = fields


class SellerRingkasSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    store_name = serializers.CharField(read_only=True)


class ProductPublikSerializer(serializers.ModelSerializer):
    seller = SellerRingkasSerializer(read_only=True)
    category_display = serializers.CharField(
        source="get_category_display",
        read_only=True,
    )
    materials = serializers.SerializerMethodField()
    eco_features = serializers.SerializerMethodField()
    price = serializers.IntegerField(read_only=True)
    final_price = serializers.IntegerField(read_only=True)
    image_url = serializers.SerializerMethodField()
    rating = serializers.FloatField(read_only=True, allow_null=True)
    review_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "description",
            "category",
            "category_display",
            "materials",
            "origin",
            "eco_features",
            "price",
            "discount",
            "final_price",
            "stock",
            "image_url",
            "status",
            "verification_summary",
            "seller",
            "rating",
            "review_count",
            "created_at",
        ]
        read_only_fields = fields

    def get_materials(self, product):
        return [
            material.strip()
            for material in product.materials.split(",")
            if material.strip()
        ]

    def get_eco_features(self, product):
        return sorted(feature.name for feature in product.eco_features.all())

    def get_image_url(self, product):
        if not product.image:
            return None
        request = self.context.get("request")
        try:
            url = product.image.url
        except ValueError:
            return None
        return request.build_absolute_uri(url) if request else url
