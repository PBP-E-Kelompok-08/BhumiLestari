from django.shortcuts import render

# Create your views here.
def show_dashboard_home(request):
    return render(request, "dashboard_home.html")