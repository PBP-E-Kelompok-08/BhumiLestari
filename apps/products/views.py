import json
import requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from apps.users.models import SellerProfile
from .forms import ProductForm
from .models import Product

def kirim_ke_api(product):
    url = settings.MOCK_API_BASE_URL + "/api/products/"

    try:
        data = {
            "name": product.name,
            "seller_id": product.seller.external_id,
            "seller_name": product.seller.store_name,
            "materials": [m.strip().lower() for m in product.materials.split(",") if m.strip()],
            "origin": product.origin,
            "eco_features": list(product.eco_features.values_list("name", flat=True)),
        }

        with product.verification_document.open("rb") as file:
            response = requests.post(
                url,
                data={"data": json.dumps(data)},
                files={"verification_document": file},
                headers={"X-Mock-Api-Key": settings.MOCK_API_WRITE_TOKEN},
                timeout=15,
            )
        if response.status_code != 201:
            return False

        hasil = response.json()
        product.external_product_id = hasil["data"]["product_id"]
        product.save()
        return True
    except Exception:
        return False


def cek_status(product):
    if not product.external_product_id:
        kirim_ke_api(product)
        return

    url = settings.MOCK_API_BASE_URL + "/api/products/" + product.external_product_id + "/"

    try:
        response = requests.get(url, timeout=5)
        if response.status_code != 200:
            return

        verification = response.json()["data"]["verification"]
        if verification is None:
            return

        product.status = verification["status"]
        product.verification_summary = verification["summary"] or ""
        product.save()
    except Exception:
        return


def get_role(user):
    if not user.is_authenticated:
        return "guest"
    if user.is_superuser:
        return "admin"
    return user.role


@login_required
def add_product(request):
    profile = SellerProfile.objects.filter(user=request.user).first()
    if profile is None:
        return redirect("dashboard:show_dashboard_home")

    form = ProductForm(request.POST or None, request.FILES or None)

    if form.is_valid():
        form.instance.seller = profile
        product = form.save(commit=False)
        product.seller = profile
        product.save()
        form.save_m2m() # Untuk ngesave hasil checkbox yang eco features (Many to many field)
        kirim_ke_api(product)
        return redirect("dashboard:show_dashboard_home")

    context = {
        "form": form, 
        "product": None
    }

    return render(request, "product_form.html", context)


@login_required
def edit_product(request, pk):
    profile = SellerProfile.objects.filter(user=request.user).first()
    if profile is None:
        return redirect("dashboard:show_dashboard_home")

    product = get_object_or_404(Product, pk=pk, seller=profile)
    form = ProductForm(request.POST or None, request.FILES or None, instance=product)

    if form.is_valid():
        verifikasi_ulang = False
        for field in ["materials", "eco_features", "origin", "verification_document"]:
            if field in form.changed_data:
                verifikasi_ulang = True

        if verifikasi_ulang:
            form.instance.status = "pending"
            form.instance.verification_summary = ""

        product = form.save()

        if verifikasi_ulang:
            kirim_ke_api(product)

        return redirect("dashboard:show_dashboard_home")

    context = {
        "form": form, 
        "product": product
    }

    return render(request, "product_form.html", context)


@login_required
def delete_product(request, pk):
    if request.user.is_superuser:
        product = get_object_or_404(Product, pk=pk)
    else:
        profile = SellerProfile.objects.filter(user=request.user).first()
        product = get_object_or_404(Product, pk=pk, seller=profile)

    if request.method == "POST":
        product.delete()

    return redirect("dashboard:show_dashboard_home")


@login_required
def verification_queue(request):
    if not request.user.is_superuser:
        return redirect("dashboard:show_dashboard_home")
 
    status = request.GET.get("status", "")
    products = Product.objects.select_related("seller").order_by("-created_at")
    if status:
        products = products.filter(status=status)
 
    context = {
        "products": products,
        "status": status,
        "total_pending": Product.objects.filter(status="pending").count(),
        "total_verified": Product.objects.filter(status="verified").count(),
        "total_rejected": Product.objects.filter(status="rejected").count(),
    }
    return render(request, "verification_queue.html", context)
 

@login_required
def review_product_admin(request, pk):
    if not request.user.is_superuser or request.method != "POST":
        return redirect("dashboard:show_dashboard_home")
 
    product = get_object_or_404(Product, pk=pk)
    action = request.POST.get("action")
    alasan = request.POST.get("reason", "").strip()
 
    if action == "approve":
        product.status = "verified"
        product.verification_summary = ""
        product.save()
    elif action == "reject" and alasan:
        product.status = "rejected"
        product.verification_summary = alasan
        product.save()
 
    return redirect("products:verification_queue")
