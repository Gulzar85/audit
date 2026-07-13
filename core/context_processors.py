from django.utils import timezone

from .models import BusinessInfo, Notification


def business_info(request):
    return {'business_info': BusinessInfo.load()}


def sidebar_badges(request):
    ctx = {}
    if request.user.is_authenticated:
        from audits.models import Audit, CorrectiveAction
        user = request.user
        qs = Audit.objects.visible_to(user)
        ctx['sidebar_badges'] = {
            'draft_count': qs.filter(is_submitted=False).count(),
        }
        ca_qs = CorrectiveAction.objects.visible_to(user)
        ctx['sidebar_badges']['overdue_ca'] = ca_qs.filter(
            deadline__lt=timezone.now().date()
        ).exclude(status__in=['COMPLETED', 'VERIFIED', 'CLOSED']).count()
        ctx['sidebar_badges']['unread_notifications'] = Notification.objects.filter(
            recipient=user, is_read=False
        ).count()
    else:
        ctx['sidebar_badges'] = {'draft_count': 0, 'overdue_ca': 0, 'unread_notifications': 0}
    return ctx
