from django.shortcuts import render

# Create your views here.
def show_cart(request):
    stores = [
        {
            "name": "Nama Toko",
            "items": [
                {"id": 1, "name": "Toples Kaca Bamboo Series", "variation": "Standar",
                 "price": 18000, "quantity": 1, "selected": True, "image": "img/toples.png"},
            ],
        },
        {
            "name": "Nama Toko",
            "items": [
                {"id": 2, "name": "Tote Bag Plain Series", "variation": "Standar",
                 "price": 27000, "quantity": 1, "selected": False, "image": "img/totebag.png"},
            ],
        }
    ]
    context = {"stores": stores, "total": 18000, "item_count": 2, "selected_count": 1}
    return render(request, "cart.html", context)

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