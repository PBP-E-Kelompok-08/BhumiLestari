from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from .forms import ProductForm
from .models import Product

@login_required
def add_product(request):
    form = ProductForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        product = form.save(commit=False)
        product.seller = request.user.seller_profile
        product.save()
        return redirect("dashboard:show_dashboard_home")

    context = {
        "form": form, 
        "action_type": "Tambah"
    }
    
    return render(request, "product_form.html", context)


@login_required
def edit_product(request, pk):
    product = get_object_or_404(Product, pk=pk, seller=request.user.seller_profile)
    form = ProductForm(request.POST or None, request.FILES or None, instance=product)

    if request.method == "POST" and form.is_valid():
        product = form.save()
        if "certification" in form.changed_data:
            product.status = "pending"
        product.save()
        return redirect("dashboard:show_dashboard_home")

    context = {
        "form": form, 
        "action_type": "Edit"
    }
    
    return render(request, "product_form.html", context)