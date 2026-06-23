from django.urls import path

from . import views

app_name = 'restaurants'

urlpatterns = [
    path('', views.RestaurantListView.as_view(), name='restaurant_list'),
    path('<int:pk>/', views.RestaurantDetailView.as_view(), name='restaurant_detail'),
    path('regions/<int:pk>/', views.RegionDetailView.as_view(), name='region_detail'),
]
