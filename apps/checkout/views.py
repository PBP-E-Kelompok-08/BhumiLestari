from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.checkout.models import Cart


def get_cart_data(request):
    cart, _ = Cart.objects.get_or_create(user=request.user)
    cart_items = cart.items.select_related("product", "product__seller")

    stores = {}
    for ci in cart_items:
        product = ci.product
        store = stores.setdefault(
            product.seller_id, {"name": product.seller.store_name, "items": []}
        )
        store["items"].append({
            "id": ci.pk,
            "name": product.name,
            "variation": "Standar",
            "price": int(product.price),
            "discount": getattr(product, 'discount', 0),
            "final_price": int(getattr(product, 'final_price', product.price)),
            "quantity": ci.quantity,
            "selected": ci.is_selected,
            "image_url": product.image.url if product.image else "",
            "stock": product.stock,
        })
    return list(stores.values())


@login_required(login_url="users:login")
def show_cart(request):
    stores = get_cart_data(request)
    
    total = 0
    item_count = 0
    selected_count = 0
    
    for store in stores:
        for item in store["items"]:
            item_count += item["quantity"]
            if item["selected"]:
                total += item["final_price"] * item["quantity"]
                selected_count += 1

    # 3. Kirim data asli ke dalam halaman cart.html
    context = {
        "stores": stores, 
        "total": total, 
        "item_count": item_count, 
        "selected_count": selected_count
    }
    return render(request, "cart.html", context)


@login_required(login_url="users:login")
def show_checkout(request):
    context = {
        "recipient_name": "Nama Penerima",
        "address": "Alamat pengiriman",
        "shipping_options": ["Reguler", "Kargo", "Express", "Same Day"],
        "payment_options": ["E-Wallet", "QRIS", "Transfer Bank", "Cash On Delivery"],
        "items_total": 18000,
        "shipping_cost": 5000,
        "grand_total": 23000,
        "item_count": 2,
    }
    return render(request, "checkout.html", context)
