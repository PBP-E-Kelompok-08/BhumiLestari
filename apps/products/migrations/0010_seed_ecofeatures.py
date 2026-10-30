from django.db import migrations


def buat_ecofeatures(apps, schema_editor):
    EcoFeature = apps.get_model("products", "EcoFeature")
    features = [
        "100% Biodegradable",
        "Recycled Materials",
        "Zero Plastic Packaging",
        "Cruelty Free",
        "Locally Sourced",
        "Carbon Neutral",
        "Reusable & Refillable",
        "Chemical Free",
    ]
    for name in features:
        EcoFeature.objects.get_or_create(name=name)


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0009_product_created_at_product_verification_summary"),
    ]

    operations = [
        migrations.RunPython(buat_ecofeatures, migrations.RunPython.noop),
    ]
