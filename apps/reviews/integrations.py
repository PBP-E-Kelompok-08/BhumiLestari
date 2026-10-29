"""Integrasi ulasan dengan produk dan pesanan yang sudah selesai."""


def ambil_produk(produk_id):
    """Return {"nama": str, "toko_id": int} atau None bila produk tidak ada.
    toko_id = id SellerProfile pemilik produk. produk_id berupa UUID."""
    from apps.products.models import Product

    p = Product.objects.filter(pk=produk_id).first()
    return {"nama": p.name, "toko_id": p.seller_id} if p else None


def pernah_membeli(user, produk_id):
    """True bila user punya pesanan SELESAI yang berisi produk tersebut."""
    from apps.checkout.models import OrderItem

    return OrderItem.objects.filter(
        order__buyer=user, order__status="selesai", product_id=produk_id
    ).exists()
