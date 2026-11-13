from rest_framework import serializers


class RevenueChartSerializer(serializers.Serializer):
    label = serializers.CharField()
    date = serializers.DateField(source="tanggal")
    revenue = serializers.IntegerField(source="nilai")
    height_percentage = serializers.IntegerField(source="tinggi")
    is_highest = serializers.BooleanField(source="tertinggi")


class BestSellingProductSerializer(serializers.Serializer):
    product_id = serializers.UUIDField(allow_null=True)
    product_name = serializers.CharField()
    units_sold = serializers.IntegerField(source="terjual")
    revenue = serializers.IntegerField(source="pendapatan")


class SellerSummarySerializer(serializers.Serializer):
    store_id = serializers.IntegerField()
    store_name = serializers.CharField()
    product_count = serializers.IntegerField()
    order_count = serializers.IntegerField()
    monthly_revenue = serializers.IntegerField()
    reviews = serializers.DictField()
    revenue_chart = RevenueChartSerializer(many=True)
    best_selling_products = BestSellingProductSerializer(many=True)
