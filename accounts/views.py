from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import Q, Avg, Count
from django.utils import timezone
from django.views.generic import TemplateView, DetailView, ListView

from audits.models import Audit, CorrectiveAction
from .models import User


class ProfileView(LoginRequiredMixin, TemplateView):
    template_name = 'accounts/profile.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'My Profile'
        user = self.request.user

        audits = Audit.objects.filter(auditor=user)
        ctx['audit_count'] = audits.count()
        ctx['submitted_audit_count'] = audits.filter(is_submitted=True).count()
        avg = audits.filter(is_submitted=True).aggregate(avg=Avg('total_percentage'))['avg']
        ctx['avg_score'] = round(avg, 1) if avg else None

        ctx['latest_audit'] = audits.select_related(
            'restaurant', 'template'
        ).order_by('-audit_date').first()

        ctx['restaurant_count'] = user.restaurants.count()
        ctx['open_ca_count'] = CorrectiveAction.objects.filter(
            restaurant__in=user.restaurants.all()
        ).exclude(status__in=['COMPLETED', 'VERIFIED', 'CLOSED']).count()

        ctx['designation_name'] = user.designation.name if user.designation else None
        ctx['department_name'] = user.department.name if user.department else None

        now = timezone.now()
        ctx['member_for_days'] = (now - user.date_joined).days if user.date_joined else 0
        return ctx


class UserListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model = User
    template_name = 'accounts/user_list.html'
    context_object_name = 'users'
    paginate_by = 20
    permission_required = 'accounts.view_user'

    def get_queryset(self):
        qs = User.objects.select_related('designation', 'department').all()
        search = self.request.GET.get('q', '').strip()
        if search:
            qs = qs.filter(
                Q(username__icontains=search) |
                Q(email__icontains=search) |
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search)
            )
        role = self.request.GET.get('role', '')
        if role and role in dict(User.Roles.choices):
            qs = qs.filter(role=role)
        return qs.order_by('username')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['role_choices'] = User.Roles.choices
        ctx['current_filters'] = {k: v for k, v in self.request.GET.items() if v}
        return ctx


class UserDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = User
    template_name = 'accounts/user_detail.html'
    context_object_name = 'user_obj'
    permission_required = 'accounts.view_user'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user_obj = self.object
        audits = Audit.objects.filter(auditor=user_obj)
        ctx['audit_count'] = audits.count()
        ctx['submitted_audit_count'] = audits.filter(is_submitted=True).count()
        avg = audits.filter(is_submitted=True).aggregate(avg=Avg('total_percentage'))['avg']
        ctx['avg_score'] = round(avg, 1) if avg else None
        ctx['restaurant_count'] = user_obj.restaurants.count()

        ctx['designation_name'] = user_obj.designation.name if user_obj.designation else None
        ctx['department_name'] = user_obj.department.name if user_obj.department else None

        ctx['recent_audits'] = audits.select_related(
            'restaurant', 'template'
        ).order_by('-created_at')[:5]
        return ctx
