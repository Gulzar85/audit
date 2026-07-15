from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import Q, Avg
from django.views.generic import TemplateView, DetailView, ListView

from audits.models import Audit, CorrectiveAction
from .models import User


class ProfileView(LoginRequiredMixin, TemplateView):
    template_name = 'accounts/profile.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'My Profile'
        user = self.request.user

        if user.role == User.Roles.MANAGER:
            audit_qs = Audit.objects.visible_to(user)
        else:
            audit_qs = Audit.objects.filter(auditor=user, is_archived=False)
        ctx['audit_count'] = audit_qs.count()
        ctx['submitted_audit_count'] = audit_qs.filter(is_submitted=True).count()
        avg = audit_qs.filter(is_submitted=True).aggregate(avg=Avg('total_percentage'))['avg']
        ctx['avg_score'] = round(avg, 1) if avg else None

        ctx['recent_audits'] = audit_qs.select_related(
            'restaurant', 'template'
        ).order_by('-audit_date')[:5]

        ctx['restaurant_count'] = user.restaurants.count()
        if user.role == User.Roles.MANAGER:
            ca_qs = CorrectiveAction.objects.filter(
                audit__auditor__manager=user
            ).distinct()
        elif user.role == User.Roles.AUDITOR:
            ca_qs = CorrectiveAction.objects.filter(
                restaurant__in=user.restaurants.all()
            )
        else:
            ca_qs = CorrectiveAction.objects.filter(
                restaurant__in=user.restaurants.all()
            )
        ctx['open_ca_count'] = ca_qs.exclude(status__in=['COMPLETED', 'VERIFIED', 'CLOSED']).count()

        ctx['designation_name'] = user.designation.name if user.designation else None
        ctx['department_name'] = user.department.name if user.department else None

        if user.role == User.Roles.MANAGER:
            ctx['auditors'] = User.objects.filter(manager=user).select_related('designation')

        return ctx


class UserListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model = User
    template_name = 'accounts/user_list.html'
    context_object_name = 'users'
    paginate_by = 20
    permission_required = 'accounts.view_user'

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role == User.Roles.ADMIN:
            qs = User.objects.all()
        elif user.role == User.Roles.MANAGER:
            qs = User.objects.filter(manager=user)
        elif user.role == User.Roles.AUDITOR:
            qs = User.objects.filter(
                Q(role=User.Roles.AUDITOR) | Q(role=User.Roles.RESTAURANT_USER),
                restaurants__in=user.restaurants.all()
            ).distinct()
        else:
            qs = User.objects.filter(pk=user.pk)
        qs = qs.select_related('designation', 'department')
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
        ctx['title'] = 'Users'
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
        ctx['title'] = user_obj.get_full_name() or user_obj.username
        audits = Audit.objects.filter(auditor=user_obj, is_archived=False)
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
