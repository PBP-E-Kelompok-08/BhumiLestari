from django.shortcuts import render

# Create your views here.
def show_dashboard_home(request):
    user = request.user

    if not user.is_authenticated:
        name = "Tamu"
    elif user.role == "seller":
        profile = getattr(user, "seller_profile", None)
        name = profile.store_name
    else:
        name = user.full_name

    return render(request, "dashboard_home.html", {"name": name})