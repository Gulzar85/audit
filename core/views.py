from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import ListView, View, TemplateView
from urllib.parse import urlparse

from .models import Notification, NotificationPreference


def _safe_redirect(url, fallback=None):
    """Redirect only to internal paths to prevent open redirect attacks."""
    if not url:
        return redirect(fallback or reverse('core:notifications'))
    parsed = urlparse(url)
    if parsed.netloc:
        return redirect(fallback or reverse('core:notifications'))
    return redirect(url)


class NotificationListView(LoginRequiredMixin, ListView):
    model = Notification
    template_name = 'core/notification_list.html'
    context_object_name = 'notifications'
    paginate_by = 20

    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user, is_archived=False)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Notifications'
        ctx['unread_count'] = Notification.objects.filter(
            recipient=self.request.user, is_read=False, is_archived=False
        ).count()
        return ctx


class NotificationMarkReadView(LoginRequiredMixin, View):
    def post(self, request, pk):
        n = get_object_or_404(Notification, pk=pk, recipient=request.user, is_archived=False)
        n.is_read = True
        n.save(update_fields=['is_read'])
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'ok': True})
        return _safe_redirect(n.link)


class NotificationArchiveView(LoginRequiredMixin, View):
    def post(self, request, pk):
        n = get_object_or_404(Notification, pk=pk, recipient=request.user, is_archived=False)
        n.is_archived = True
        n.save(update_fields=['is_archived'])
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'ok': True})
        return redirect('core:notifications')


class NotificationMarkAllReadView(LoginRequiredMixin, View):
    def post(self, request):
        Notification.objects.filter(recipient=request.user, is_read=False, is_archived=False).update(is_read=True)
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'ok': True})
        return redirect('core:notifications')


class NotificationCountView(LoginRequiredMixin, View):
    def get(self, request):
        count = Notification.objects.filter(recipient=request.user, is_read=False, is_archived=False).count()
        return JsonResponse({'count': count})


class NotificationSettingsView(LoginRequiredMixin, TemplateView):
    template_name = 'core/notification_settings.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        for choice in Notification.Type.choices:
            NotificationPreference.objects.get_or_create(
                user=user, notification_type=choice[0],
                defaults={'email_enabled': True},
            )
        prefs = NotificationPreference.objects.filter(user=user)
        pref_map = {p.notification_type: p for p in prefs}
        ctx['type_prefs'] = [
            (type_key, type_label, pref_map.get(type_key))
            for type_key, type_label in Notification.Type.choices
        ]
        ctx['title'] = 'Notification Settings'
        return ctx

    def post(self, request):
        user = request.user
        for choice in Notification.Type.choices:
            key = f'email_{choice[0]}'
            enabled = request.POST.get(key) == 'on'
            pref, _ = NotificationPreference.objects.get_or_create(
                user=user, notification_type=choice[0],
            )
            pref.email_enabled = enabled
            pref.save(update_fields=['email_enabled'])
        messages.success(request, 'Notification preferences updated.')
        return redirect('core:notification_settings')

