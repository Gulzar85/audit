from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import Q, Count, Avg, Prefetch
from django.views.generic import ListView, DetailView

from .models import Region, Restaurant


class RestaurantListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model = Restaurant
    template_name = 'restaurants/restaurant_list.html'
    context_object_name = 'restaurants'
    paginate_by = 20
    permission_required = 'restaurants.view_restaurant'

    def _base_qs(self):
        qs = Restaurant.objects.filter(is_archived=False)
        user = self.request.user
        if not user.is_superuser:
            qs = qs.filter(pk__in=user.restaurants.values_list('pk', flat=True))
        return qs

    def get_queryset(self):
        qs = self._base_qs().select_related('region')

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

        region = self.request.GET.get('region', '').strip()
        if region:
            qs = qs.filter(region__pk=region)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Restaurants'
        ctx['status_choices'] = Restaurant.Status.choices
        ctx['current_filters'] = {
            k: v for k, v in self.request.GET.items() if v
        }
        visible = self._base_qs()
        ctx['cities'] = visible.values_list('city', flat=True).distinct().order_by('city')
        region_counts = {
            rc['region_id']: rc['restaurant_count']
            for rc in visible.values('region_id').annotate(
                restaurant_count=Count('id'))
        }
        regions = list(Region.objects.filter(pk__in=region_counts).order_by('name'))
        for region in regions:
            region.restaurant_count = region_counts.get(region.pk, 0)
        ctx['regions'] = regions
        return ctx


class RestaurantDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = Restaurant
    template_name = 'restaurants/restaurant_detail.html'
    context_object_name = 'restaurant'
    permission_required = 'restaurants.view_restaurant'

    def get_queryset(self):
        qs = Restaurant.objects.select_related('region').filter(is_archived=False)
        user = self.request.user
        if not user.is_superuser:
            qs = qs.filter(pk__in=user.restaurants.values_list('pk', flat=True))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        restaurant = self.object
        ctx['title'] = f'Restaurant: {restaurant.name}'
        audits = restaurant.audits.visible_to(self.request.user).filter(
            is_submitted=True, is_archived=False)
        ctx['recent_audits'] = audits.select_related(
            'template', 'auditor').order_by('-audit_date')[:10]
        ctx['audit_count'] = audits.count()
        ctx['avg_score'] = audits.aggregate(
            avg_score=Avg('total_percentage'))['avg_score']
        ctx['latest_audit'] = audits.order_by('-audit_date').first()
        return ctx


class RegionDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = Region
    template_name = 'restaurants/region_detail.html'
    context_object_name = 'region'
    permission_required = 'restaurants.view_region'

    def get_queryset(self):
        user = self.request.user
        restaurants = Restaurant.objects.filter(is_archived=False).select_related('region')
        if not user.is_superuser:
            restaurants = restaurants.filter(pk__in=user.restaurants.values_list('pk', flat=True))
        return Region.objects.prefetch_related(
            Prefetch('restaurants', queryset=restaurants)
        ).annotate(
            restaurant_count=Count('restaurants', filter=Q(restaurants__is_archived=False))
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = f'Region: {self.object.name}'
        return ctx
