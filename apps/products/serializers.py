from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers

from .models import EcoFeature, Product
from .validators import (
    validate_file_content,
    validate_file_extension,
    validate_file_size,
)


def _validate_uploaded_file(uploaded_file, extensions):
    try:
        validate_file_size(uploaded_file)
        validate_file_extension(uploaded_file, extensions)
        validate_file_content(uploaded_file)
    except DjangoValidationError as error:
        raise serializers.ValidationError(error.messages) from error
    return uploaded_file


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
    rating = serializers.SerializerMethodField()
    review_count = serializers.SerializerMethodField()

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

    def get_rating(self, product):
        rating = getattr(product, "rating", None)
        return round(rating, 1) if rating is not None else None

    def get_review_count(self, product):
        return getattr(product, "review_count", 0)

    def get_image_url(self, product):
        if not product.image:
            return None
        request = self.context.get("request")
        try:
            url = product.image.url
        except ValueError:
            return None
        return request.build_absolute_uri(url) if request else url


class ProductSellerSerializer(ProductPublikSerializer):
    verification_document_uploaded = serializers.SerializerMethodField()

    class Meta(ProductPublikSerializer.Meta):
        fields = ProductPublikSerializer.Meta.fields + [
            "external_product_id",
            "verification_document_uploaded",
        ]
        read_only_fields = fields

    def get_verification_document_uploaded(self, product):
        return bool(product.verification_document)


class ProductCreateSerializer(serializers.ModelSerializer):
    eco_feature_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=EcoFeature.objects.all(),
        source="eco_features",
        write_only=True,
    )

    class Meta:
        model = Product
        fields = [
            "name",
            "description",
            "category",
            "materials",
            "origin",
            "eco_feature_ids",
            "price",
            "discount",
            "stock",
            "image",
            "verification_document",
        ]

    def validate_image(self, image):
        return _validate_uploaded_file(image, ["jpg", "jpeg", "png"])

    def validate_verification_document(self, document):
        return _validate_uploaded_file(
            document,
            ["pdf", "jpg", "jpeg", "png"],
        )

    @transaction.atomic
    def create(self, validated_data):
        eco_features = validated_data.pop("eco_features")
        seller = self.context["seller"]
        product = Product.objects.create(seller=seller, **validated_data)
        product.eco_features.set(eco_features)
        return product


class ProductUpdateSerializer(serializers.ModelSerializer):
    eco_feature_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=EcoFeature.objects.all(),
        source="eco_features",
        required=False,
        write_only=True,
    )

    class Meta:
        model = Product
        fields = [
            "name",
            "description",
            "category",
            "materials",
            "origin",
            "eco_feature_ids",
            "price",
            "discount",
            "stock",
            "image",
            "verification_document",
        ]

    def validate_image(self, image):
        return _validate_uploaded_file(image, ["jpg", "jpeg", "png"])

    def validate_verification_document(self, document):
        return _validate_uploaded_file(
            document,
            ["pdf", "jpg", "jpeg", "png"],
        )

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError(
                "Kirim setidaknya satu field produk yang ingin diperbarui."
            )
        return attrs

    @transaction.atomic
    def update(self, instance, validated_data):
        sensitive_fields = {
            "materials",
            "origin",
            "eco_features",
            "verification_document",
        }
        self.verification_resubmitted = bool(
            sensitive_fields.intersection(validated_data)
        )
        eco_features = validated_data.pop("eco_features", None)

        for field, value in validated_data.items():
            setattr(instance, field, value)
        if self.verification_resubmitted:
            instance.status = "pending"
            instance.verification_summary = ""
        instance.save()

        if eco_features is not None:
            instance.eco_features.set(eco_features)
        return instance
