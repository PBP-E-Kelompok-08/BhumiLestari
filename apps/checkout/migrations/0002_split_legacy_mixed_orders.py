from django.db import migrations


def split_legacy_mixed_orders(apps, schema_editor):
    """Ubah pesanan lama campuran menjadi satu pesanan untuk setiap toko."""
    Order = apps.get_model("checkout", "Order")
    OrderItem = apps.get_model("checkout", "OrderItem")
    SellerProfile = apps.get_model("users", "SellerProfile")

    legacy_orders = Order.objects.filter(seller_id__isnull=True)
    for order in legacy_orders.iterator():
        items = list(
            OrderItem.objects.filter(order_id=order.pk).select_related("product__seller")
        )
        if not items:
            continue

        groups = {}
        for item in items:
            seller_id = getattr(item.product, "seller_id", None)
            if seller_id is None:
                # Produk yang sudah hilang tidak dapat dipetakan ke toko secara aman.
                groups = {}
                break
            groups.setdefault(seller_id, []).append(item)

        if not groups:
            continue

        store_names = dict(
            SellerProfile.objects.filter(pk__in=groups).values_list("pk", "store_name")
        )
        if len(store_names) != len(groups):
            continue

        grouped_items = sorted(groups.items())
        items_total = sum(item.price * item.quantity for item in items)
        # Pertahankan total historis. Biaya di luar item (umumnya ongkir lama)
        # ditempatkan pada pesanan pertama agar tidak terhitung dua kali.
        extra_cost = max(order.total_price - items_total, 0)
        original_created_at = order.created_at

        for index, (seller_id, seller_items) in enumerate(grouped_items):
            subtotal = sum(item.price * item.quantity for item in seller_items)
            shipping_cost = extra_cost if index == 0 else 0

            if index == 0:
                target = order
                target.seller_id = seller_id
                target.store_name = store_names[seller_id]
                target.shipping_cost = shipping_cost
                target.total_price = subtotal + shipping_cost
                target.save(
                    update_fields=["seller", "store_name", "shipping_cost", "total_price"]
                )
            else:
                target = Order.objects.create(
                    buyer_id=order.buyer_id,
                    seller_id=seller_id,
                    store_name=store_names[seller_id],
                    recipient_name=order.recipient_name,
                    phone=order.phone,
                    shipping_address=order.shipping_address,
                    shipping_method=order.shipping_method,
                    payment_method=order.payment_method,
                    shipping_cost=shipping_cost,
                    total_price=subtotal + shipping_cost,
                    status=order.status,
                )
                Order.objects.filter(pk=target.pk).update(created_at=original_created_at)
                OrderItem.objects.filter(
                    pk__in=[item.pk for item in seller_items]
                ).update(order_id=target.pk)


class Migration(migrations.Migration):
    dependencies = [
        ("checkout", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(split_legacy_mixed_orders, migrations.RunPython.noop),
    ]
