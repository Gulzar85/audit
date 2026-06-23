from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import Q, Avg, Count
from django.views.generic import ListView, DetailView

from .models import Region, Restaurant


class RestaurantListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model = Restaurant
    template_name = 'restaurants/restaurant_list.html'
    context_object_name = 'restaurants'
    paginate_by = 20
    permission_required = 'restaurants.view_restaurant'

    def get_queryset(self):
        qs = Restaurant.objects.select_related('region').all()

        user = self.request.user
        if not user.is_superuser:
            qs = qs.filter(pk__in=user.restaurants.values_list('pk', flat=True))

        search = self.request.GET.get('q', '').strip()
        if search:
            qs = qs.filter(
                Q(name__icontains=search) |
                Q(code__icontains=search) |
                Q(city__icontains=search)
            )

        status = self.request.GET.get('status', '')
        if status in dict(Restaurant.Status.choices):
            qs = qs.filter(status=status)

        city = self.request.GET.get('city', '').strip()
        if city:
            qs = qs.filter(city__icontains=city)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['status_choices'] = Restaurant.Status.choices
        ctx['current_filters'] = {
            k: v for k, v in self.request.GET.items() if v
        }
        ctx['cities'] = Restaurant.objects.values_list('city', flat=True).distinct().order_by('city')
        return ctx


class RestaurantDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = Restaurant
    template_name = 'restaurants/restaurant_detail.html'
    context_object_name = 'restaurant'
    permission_required = 'restaurants.view_restaurant'

    def get_queryset(self):
        qs = Restaurant.objects.select_related('region').all()
        user = self.request.user
        if not user.is_superuser:
            qs = qs.filter(pk__in=user.restaurants.values_list('pk', flat=True))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        restaurant = self.object
        audits = restaurant.audits.select_related('template', 'auditor').filter(is_submitted=True).order_by('-audit_date')[:10]
        ctx['recent_audits'] = audits
        ctx['audit_count'] = restaurant.submitted_audit_count
        ctx['avg_score'] = restaurant.submitted_average_score
        ctx['latest_audit'] = restaurant.latest_audit
        return ctx


class RegionDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = Region
    template_name = 'restaurants/region_detail.html'
    context_object_name = 'region'
    permission_required = 'restaurants.view_region'
