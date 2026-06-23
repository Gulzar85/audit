import csv
import json

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from decimal import Decimal
from django.db import transaction
from django.db.models import Q, Count, Avg, F, Sum, FloatField, Value, ExpressionWrapper
from django.db.models.functions import TruncMonth, Coalesce
from django.forms import modelformset_factory
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, get_object_or_404, reverse
from django.template.loader import get_template
from django.utils import timezone
from django.views.generic import ListView, CreateView, DetailView, UpdateView, TemplateView, View

from core.models import Notification
from .forms import AuditForm, AuditScoreForm, CorrectiveActionForm
from .utils import notify_restaurant_users, notify_auditor_and_manager
from .models import Audit, AuditTemplate, AuditSection, AuditQuestionResponse, CorrectiveAction


class AuditListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model = Audit
    template_name = 'audits/audit_list.html'
    context_object_name = 'audits'
    paginate_by = 20
    permission_required = 'audits.view_audit'

    def get_queryset(self):
        qs = Audit.objects.select_related(
            'restaurant', 'template', 'auditor'
        ).all()

        user = self.request.user
        if not user.is_superuser:
            qs = qs.filter(
                Q(auditor=user) |
                Q(restaurant__in=user.restaurants.all())
            )

        search = self.request.GET.get('q', '').strip()
        if search:
            qs = qs.filter(
                Q(restaurant__name__icontains=search) |
                Q(restaurant__code__icontains=search) |
                Q(manager_on_duty__icontains=search)
            )

        status = self.request.GET.get('status', '')
        if status == 'submitted':
            qs = qs.filter(is_submitted=True)
        elif status == 'draft':
            qs = qs.filter(is_submitted=False)

        grade = self.request.GET.get('grade', '')
        if grade in dict(Audit.Grade.choices):
            qs = qs.filter(grade=grade)

        restaurant_id = self.request.GET.get('restaurant', '')
        if restaurant_id and restaurant_id.isdigit():
            qs = qs.filter(restaurant_id=int(restaurant_id))

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Audits'
        ctx['grade_choices'] = Audit.Grade.choices
        ctx['current_filters'] = {
            k: v for k, v in self.request.GET.items() if v and k != 'page'
        }
        return ctx


class AuditCreateView(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    model = Audit
    form_class = AuditForm
    template_name = 'audits/audit_form.html'
    permission_required = 'audits.add_audit'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'New Audit'
        return ctx

    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, 'Audit created successfully.')
        return redirect('audits:score', pk=self.object.pk)


class AuditDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = Audit
    template_name = 'audits/audit_detail.html'
    context_object_name = 'audit'
    permission_required = 'audits.view_audit'

    def get_queryset(self):
        qs = Audit.objects.select_related(
            'restaurant', 'template', 'auditor'
        ).prefetch_related(
            'audit_sections__section',
            'audit_sections__responses__question',
        )
        user = self.request.user
        if not user.is_superuser:
            qs = qs.filter(
                Q(auditor=user) |
                Q(restaurant__in=user.restaurants.all())
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = f'Audit: {self.object.restaurant.name}'
        return ctx


class AuditScoreView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    model = Audit
    template_name = 'audits/audit_score.html'
    permission_required = 'audits.change_audit'
    fields = []

    def get_queryset(self):
        qs = Audit.objects.all()
        user = self.request.user
        if not user.is_superuser:
            qs = qs.filter(
                Q(auditor=user) |
                Q(restaurant__in=user.restaurants.all())
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        audit = self.object
        sections = audit.audit_sections.select_related('section').prefetch_related(
            'responses__question'
        ).order_by('section__order')

        section_formsets = []
        sections_json = []
        for sec in sections:
            responses = sec.responses.all().select_related('question')
            FormSet = modelformset_factory(
                AuditQuestionResponse,
                form=AuditScoreForm,
                extra=0,
                can_delete=False,
            )
            formset = FormSet(
                queryset=responses,
                prefix=f'section_{sec.pk}',
            )
            section_formsets.append({
                'section': sec,
                'formset': formset,
            })

            resp_data = []
            for r in responses:
                resp_data.append({
                    'id': r.pk,
                    'scored': float(r.scored_points or 0),
                    'max': r.question.possible_points or 0,
                    'is_na': r.is_na,
                    'is_critical': r.question.is_critical,
                    'comments': r.comments or '',
                    'needs_ca': r.needs_corrective_action,
                    'is_answered': r.is_answered,
                })
            sections_json.append({
                'id': sec.pk,
                'name': sec.section.name,
                'responses': resp_data,
            })

        ctx['section_formsets'] = section_formsets
        ctx['sections_json'] = json.dumps(sections_json)
        ctx['title'] = f'Score: {audit.restaurant.name}'
        return ctx

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        audit = self.object

        if audit.is_submitted:
            messages.warning(request, 'This audit has already been submitted.')
            return redirect('audits:result', pk=audit.pk)

        sections = audit.audit_sections.all()
        formsets = []
        all_valid = True

        for sec in sections:
            responses = sec.responses.all()
            FormSet = modelformset_factory(
                AuditQuestionResponse,
                form=AuditScoreForm,
                extra=0,
                can_delete=False,
            )
            formset = FormSet(
                request.POST,
                queryset=responses,
                prefix=f'section_{sec.pk}',
            )
            formsets.append({'section': sec, 'formset': formset})
            if not formset.is_valid():
                all_valid = False

        if all_valid:
            for f in formsets:
                saved = f['formset'].save()
                for instance in saved:
                    if not instance.is_answered:
                        instance.is_answered = True
                        instance.save(update_fields=['is_answered'])
            audit.calculate_totals()
            audit.is_submitted = True
            audit.save()
            if audit.auditor:
                Notification.objects.create(
                    recipient=audit.auditor,
                    notification_type=Notification.Type.AUDIT_SUBMITTED,
                    title=f'Audit submitted for {audit.restaurant.name}',
                    message=f'Grade: {audit.get_grade_display()} ({audit.total_percentage:.1f}%)',
                    link=reverse('audits:result', args=[audit.pk]),
                )
            notify_restaurant_users(
                Notification.Type.AUDIT_SUBMITTED,
                f'Audit Completed: {audit.restaurant.name}',
                f'{audit.restaurant.name} scored {audit.total_percentage:.1f}% (Grade {audit.get_grade_display()}).',
                reverse('audits:result', args=[audit.pk]),
                audit.restaurant,
            )
            messages.success(request, 'Audit scores saved and submitted successfully.')
            return redirect('audits:result', pk=audit.pk)

        ctx = self.get_context_data()
        ctx['section_formsets'] = formsets
        ctx['title'] = f'Score: {audit.restaurant.name}'
        messages.error(request, 'Please correct the errors below.')
        return self.render_to_response(ctx)


class AuditResultView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = Audit
    template_name = 'audits/audit_result.html'
    context_object_name = 'audit'
    permission_required = 'audits.view_audit'

    def get_queryset(self):
        qs = Audit.objects.select_related(
            'restaurant', 'template', 'auditor'
        ).prefetch_related(
            'audit_sections__section',
            'audit_sections__responses__question',
        )
        user = self.request.user
        if not user.is_superuser:
            qs = qs.filter(
                Q(auditor=user) |
                Q(restaurant__in=user.restaurants.all())
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = f'Results: {self.object.restaurant.name}'
        return ctx


class AuditReportPdfView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = Audit
    permission_required = 'audits.view_audit'

    def get_queryset(self):
        qs = Audit.objects.select_related(
            'restaurant', 'template', 'auditor', 'previous_audit'
        ).prefetch_related(
            'audit_sections__section',
            'audit_sections__responses__question',
            'corrective_actions',
        )
        user = self.request.user
        if not user.is_superuser:
            qs = qs.filter(
                Q(auditor=user) |
                Q(restaurant__in=user.restaurants.all())
            )
        return qs

    def render_to_response(self, context, **response_kwargs):
        from weasyprint import HTML
        from core.models import BusinessInfo
        audit = self.object
        template = get_template('audits/audit_report_pdf.html')
        html_str = template.render({
            'audit': audit,
            'corrective_actions': audit.corrective_actions.all(),
            'business_info': BusinessInfo.load(),
        })

        pdf = HTML(string=html_str).write_pdf()

        filename = f'audit_{audit.restaurant.code}_{audit.audit_date}.pdf'.replace('/', '-')
        response = HttpResponse(pdf, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


class AuditTemplateListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model = AuditTemplate
    template_name = 'audits/template_list.html'
    context_object_name = 'templates'
    paginate_by = 20
    permission_required = 'audits.view_audittemplate'

    def get_queryset(self):
        qs = AuditTemplate.objects.annotate(
            section_count=Count('sections', distinct=True),
            question_count=Count('sections__questions', distinct=True),
            audit_count=Count('audits', distinct=True),
        ).order_by('-created_at', '-pk')
        search = self.request.GET.get('q', '').strip()
        if search:
            qs = qs.filter(name__icontains=search)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['current_filters'] = {k: v for k, v in self.request.GET.items() if v}
        return ctx


class AuditTemplateDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = AuditTemplate
    template_name = 'audits/template_detail.html'
    context_object_name = 'template'
    permission_required = 'audits.view_audittemplate'

    def get_queryset(self):
        return AuditTemplate.objects.prefetch_related(
            'sections__questions',
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        sections = self.object.sections.all()
        ctx['sections'] = sections
        ctx['total_questions'] = sum(s.questions.count() for s in sections)
        ctx['total_points'] = sum(
            q.possible_points for s in sections for q in s.questions.all()
        )
        return ctx


class DashboardView(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    template_name = 'audits/dashboard.html'
    permission_required = 'audits.view_audit'

    def _base_qs(self):
        user = self.request.user
        qs = Audit.objects.all()
        if not user.is_superuser:
            qs = qs.filter(
                Q(auditor=user) |
                Q(restaurant__in=user.restaurants.all())
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Dashboard'

        template_id = self.request.GET.get('template', '')
        ctx['selected_template'] = int(template_id) if template_id and template_id.isdigit() else 0
        ctx['templates'] = AuditTemplate.objects.values('id', 'name').order_by('name')
        selected_template_id = ctx['selected_template']
        selected_tpl = None
        if selected_template_id:
            try:
                selected_tpl = AuditTemplate.objects.get(pk=selected_template_id)
            except AuditTemplate.DoesNotExist:
                pass
        ctx['selected_template_name'] = selected_tpl.name if selected_tpl else ''

        qs = self._base_qs()
        if selected_template_id:
            qs = qs.filter(template_id=selected_template_id)

        ctx['total_audits'] = qs.count()
        ctx['submitted_audits'] = qs.filter(is_submitted=True).count()
        ctx['draft_audits'] = qs.filter(is_submitted=False).count()

        submitted = qs.filter(is_submitted=True)
        avg = submitted.aggregate(avg=Avg('total_percentage'))['avg']
        ctx['avg_score'] = round(avg, 1) if avg else 0

        ca_qs = CorrectiveAction.objects.all()
        user = self.request.user
        if not user.is_superuser:
            ca_qs = ca_qs.filter(restaurant__in=user.restaurants.all())
        if selected_template_id:
            ca_qs = ca_qs.filter(audit__template_id=selected_template_id)
        ctx['open_ca'] = ca_qs.filter(completed=False).count()
        ctx['overdue_ca'] = ca_qs.filter(completed=False, deadline__lt=timezone.now().date()).count()

        grade_counts = submitted.values('grade').annotate(count=Count('grade')).order_by('grade')
        submitted_count = submitted.count()
        ctx['grade_distribution'] = {
            g['grade']: {
                'count': g['count'],
                'pct': round(g['count'] / submitted_count * 100, 1) if submitted_count else 0,
            } for g in grade_counts
        }

        ctx['recent_audits'] = qs.select_related(
            'restaurant', 'template', 'auditor'
        ).order_by('-created_at')[:5]

        ctx['recent_ca'] = ca_qs.select_related(
            'restaurant'
        ).order_by('-created_at')[:5]

        # Score trends by month (last 6 months)
        six_months_ago = timezone.now() - timezone.timedelta(days=180)
        monthly = submitted.filter(
            submitted_at__gte=six_months_ago
        ).annotate(
            month=TruncMonth('audit_date')
        ).values('month').annotate(
            avg_score=Avg('total_percentage')
        ).order_by('month')
        ctx['score_trends'] = {
            'labels': json.dumps([m['month'].strftime('%b') if m['month'] else '' for m in monthly]),
            'data': json.dumps([round(m['avg_score'], 1) if m['avg_score'] else 0 for m in monthly]),
        } if monthly else None

        # --- Section-wise Analytics ---
        submitted_audit_ids = submitted.values_list('id', flat=True)

        # 1. Section Performance Overview
        section_perf = (
            AuditSection.objects.filter(audit_id__in=submitted_audit_ids)
            .values('section_id', 'section__name')
            .annotate(
                avg_pct=Avg('section_percentage'),
                audit_count=Count('audit', distinct=True),
            )
            .order_by('-avg_pct')
        )
        ctx['section_performance'] = json.dumps([
            {
                'name': s['section__name'],
                'avg': float(round(s['avg_pct'], 1)) if s['avg_pct'] else 0,
                'count': s['audit_count'],
            }
            for s in section_perf
        ])

        # 2. Points Deducted by Section
        section_ded = (
            AuditSection.objects.filter(audit_id__in=submitted_audit_ids)
            .values('section_id', 'section__name')
            .annotate(
                total_possible=Coalesce(Sum('possible_points'), Value(Decimal('0.00'))),
                total_scored=Coalesce(Sum('scored_points'), Value(Decimal('0.00'))),
            )
            .order_by('section__name')
        )
        ctx['section_deductions'] = json.dumps([
            {
                'name': s['section__name'],
                'possible': float(s['total_possible']),
                'scored': float(s['total_scored']),
                'deducted': float(s['total_possible'] - s['total_scored']),
            }
            for s in section_ded
        ])

        # 3. Section Trend Over Time
        sections_for_trend = list(
            AuditSection.objects.filter(
                audit_id__in=submitted_audit_ids,
                audit__submitted_at__gte=six_months_ago,
            )
            .annotate(month=TruncMonth('audit__audit_date'))
            .values('month', 'section__name')
            .annotate(avg_pct=Avg('section_percentage'))
            .order_by('month', 'section__name')
        )
        trend_by_section = {}
        all_months_set = set()
        for row in sections_for_trend:
            name = row['section__name']
            label = row['month'].strftime('%b %Y') if row['month'] else ''
            if name not in trend_by_section:
                trend_by_section[name] = {}
            trend_by_section[name][label] = float(round(row['avg_pct'], 1)) if row['avg_pct'] else None
            all_months_set.add(label)
        all_months = sorted(all_months_set, key=lambda m: m.split()[-1] + m.split()[0] if m else '')
        ctx['section_trend_series'] = json.dumps([
            {
                'name': sec,
                'data': [trend_by_section[sec].get(m, None) for m in all_months],
            }
            for sec in trend_by_section
        ])
        ctx['section_trend_months'] = json.dumps(all_months)

        # 4. Most Frequent Findings (deductions leaderboard)
        freq_findings = (
            AuditQuestionResponse.objects.filter(
                audit_section__audit_id__in=submitted_audit_ids,
                scored_points=0,
            )
            .values('question_id', 'question__question_text', 'question__section__name')
            .annotate(
                deduction_count=Count('id', distinct=True),
            )
            .order_by('-deduction_count')[:15]
        )
        ctx['frequent_findings'] = json.dumps([
            {
                'text': f['question__question_text'][:80],
                'section': f['question__section__name'],
                'count': f['deduction_count'],
            }
            for f in freq_findings
        ])
        ctx['submitted_audit_count'] = submitted.count()

        return ctx


class DashboardExportView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = 'audits.view_audit'

    def get(self, request):
        user = request.user
        qs = Audit.objects.select_related('restaurant', 'template', 'auditor').all()
        if not user.is_superuser:
            qs = qs.filter(
                Q(auditor=user) |
                Q(restaurant__in=user.restaurants.all())
            )

        from_date = request.GET.get('from_date', '')
        to_date = request.GET.get('to_date', '')
        if from_date:
            qs = qs.filter(audit_date__gte=from_date)
        if to_date:
            qs = qs.filter(audit_date__lte=to_date)

        resp = HttpResponse(content_type='text/csv')
        resp['Content-Disposition'] = 'attachment; filename="audits_export.csv"'
        writer = csv.writer(resp)
        writer.writerow(['Restaurant', 'Template', 'Audit Date', 'Manager on Duty',
                         'Auditor', 'Score', 'Grade', 'Status', 'Submitted At'])
        for a in qs:
            writer.writerow([
                a.restaurant.name,
                a.template.name,
                a.audit_date,
                a.manager_on_duty,
                a.auditor.get_full_name() or a.auditor.username if a.auditor else '',
                f'{a.total_percentage:.1f}' if a.total_percentage else '',
                a.grade,
                'Submitted' if a.is_submitted else 'Draft',
                a.submitted_at.strftime('%Y-%m-%d %H:%M') if a.submitted_at else '',
            ])
        return resp


class CorrectiveActionListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model = CorrectiveAction
    template_name = 'audits/correctiveaction_list.html'
    context_object_name = 'actions'
    paginate_by = 20
    permission_required = 'audits.view_correctiveaction'

    def get_queryset(self):
        qs = CorrectiveAction.objects.select_related(
            'audit', 'restaurant', 'question_response__question'
        ).all()

        user = self.request.user
        if not user.is_superuser:
            qs = qs.filter(restaurant__in=user.restaurants.all())

        status = self.request.GET.get('status', 'open')
        if status == 'open':
            qs = qs.filter(completed=False)
        elif status == 'completed':
            qs = qs.filter(completed=True)

        risk = self.request.GET.get('risk', '')
        if risk in dict(CorrectiveAction.RiskLevel.choices):
            qs = qs.filter(risk_level=risk)

        restaurant_id = self.request.GET.get('restaurant', '')
        if restaurant_id and restaurant_id.isdigit():
            qs = qs.filter(restaurant_id=int(restaurant_id))

        overdue = self.request.GET.get('overdue', '')
        if overdue == '1':
            qs = qs.filter(deadline__lt=timezone.now().date(), completed=False)

        return qs.order_by('completed', 'deadline')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Corrective Actions'
        ctx['risk_choices'] = CorrectiveAction.RiskLevel.choices
        ctx['status_choices'] = [
            ('open', 'Open'),
            ('completed', 'Completed'),
            ('all', 'All'),
        ]
        ctx['current_filters'] = {k: v for k, v in self.request.GET.items() if v}
        return ctx


class CorrectiveActionCompleteView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = 'audits.change_correctiveaction'

    def _get_action_or_404(self, request, pk):
        qs = CorrectiveAction.objects.all()
        user = request.user
        if not user.is_superuser:
            qs = qs.filter(restaurant__in=user.restaurants.all())
        return get_object_or_404(qs, pk=pk)

    def post(self, request, pk):
        action = self._get_action_or_404(request, pk)
        was_completed = action.completed
        action.completed = not action.completed
        action.save()
        msg = 'completed' if action.completed else 'reopened'
        if action.completed and not was_completed:
            link = reverse('audits:corrective_action_edit', args=[action.pk])
            if action.audit.auditor:
                notify_auditor_and_manager(
                    Notification.Type.CA_COMPLETED,
                    f'Corrective Action Completed: {action.restaurant.name}',
                    f'A {action.get_risk_level_display()} corrective action has been completed for {action.restaurant.name}.',
                    link,
                    action.audit.auditor,
                )
        messages.success(request, f'Corrective action {msg}.')
        return redirect('audits:corrective_actions')


class CorrectiveActionCreateView(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    model = CorrectiveAction
    form_class = CorrectiveActionForm
    template_name = 'audits/correctiveaction_form.html'
    permission_required = 'audits.add_correctiveaction'

    def get_initial(self):
        initial = super().get_initial()
        audit_pk = self.request.GET.get('audit')
        if audit_pk:
            initial['audit'] = audit_pk
        return initial

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        audit_pk = self.request.GET.get('audit')
        if audit_pk:
            qs = Audit.objects.all()
            user = self.request.user
            if not user.is_superuser:
                qs = qs.filter(
                    Q(auditor=user) |
                    Q(restaurant__in=user.restaurants.all())
                )
            audit = qs.filter(pk=audit_pk).first()
            if audit:
                kwargs['instance'] = CorrectiveAction(audit=audit, restaurant=audit.restaurant)
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Create Corrective Action'
        return ctx

    def get_success_url(self):
        return reverse('audits:corrective_actions')


class CorrectiveActionUpdateView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    model = CorrectiveAction
    form_class = CorrectiveActionForm
    template_name = 'audits/correctiveaction_form.html'
    permission_required = 'audits.change_correctiveaction'
    context_object_name = 'action'

    def get_queryset(self):
        qs = CorrectiveAction.objects.all()
        user = self.request.user
        if not user.is_superuser:
            qs = qs.filter(restaurant__in=user.restaurants.all())
        return qs

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Edit Corrective Action'
        ctx['editing'] = True
        return ctx

    def form_valid(self, form):
        messages.success(self.request, 'Corrective action updated successfully.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('audits:corrective_actions')


class CorrectiveActionDeleteView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = 'audits.delete_correctiveaction'

    def get_queryset(self):
        qs = CorrectiveAction.objects.all()
        user = self.request.user
        if not user.is_superuser:
            qs = qs.filter(restaurant__in=user.restaurants.all())
        return qs

    def post(self, request, pk):
        qs = self.get_queryset()
        action = get_object_or_404(qs, pk=pk)
        action.delete()
        messages.success(request, 'Corrective action deleted.')
        return redirect('audits:corrective_actions')


class AuditSubmitView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = 'audits.change_audit'

    def _get_audit_or_404(self, request, pk):
        qs = Audit.objects.all()
        user = request.user
        if not user.is_superuser:
            qs = qs.filter(
                Q(auditor=user) |
                Q(restaurant__in=user.restaurants.all())
            )
        return get_object_or_404(qs, pk=pk)

    @transaction.atomic
    def post(self, request, pk):
        audit = self._get_audit_or_404(request, pk)

        if audit.is_submitted:
            messages.warning(request, 'Audit is already submitted.')
            return redirect('audits:detail', pk=pk)

        audit.calculate_totals()
        audit.is_submitted = True
        audit.save()

        messages.success(request, 'Audit submitted successfully.')
        return redirect('audits:result', pk=pk)


class AuditDeleteView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = 'audits.delete_audit'

    def get_queryset(self):
        qs = Audit.objects.all()
        user = self.request.user
        if not user.is_superuser:
            qs = qs.filter(
                Q(auditor=user) |
                Q(restaurant__in=user.restaurants.all())
            )
        return qs

    def post(self, request, pk):
        qs = self.get_queryset()
        audit = get_object_or_404(qs, pk=pk)
        audit.delete()
        messages.success(request, 'Audit deleted successfully.')
        return redirect('audits:list')


class SaveResponseView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = 'audits.change_audit'

    @transaction.atomic
    def post(self, request):
        response_id = request.POST.get('response_id')
        if not response_id:
            return JsonResponse({'success': False, 'message': 'Missing response_id'}, status=400)

        qs = AuditQuestionResponse.objects.select_related(
            'audit_section__audit', 'question'
        )
        user = request.user
        if not user.is_superuser:
            qs = qs.filter(
                Q(audit_section__audit__auditor=user) |
                Q(audit_section__audit__restaurant__in=user.restaurants.all())
            )
        resp = get_object_or_404(qs, pk=response_id)

        if resp.audit_section.audit.is_submitted:
            return JsonResponse({'success': False, 'message': 'Audit already submitted'}, status=400)

        scored_points = request.POST.get('scored_points')
        comments = request.POST.get('comments', '')
        is_na = request.POST.get('is_na') == 'true'
        needs_ca = request.POST.get('needs_ca') == 'true'

        if scored_points is not None:
            try:
                scored_points = Decimal(scored_points)
            except Exception:
                return JsonResponse({'success': False, 'message': 'Invalid score'}, status=400)
            max_points = resp.question.possible_points or Decimal('0')
            if scored_points > max_points:
                return JsonResponse({'success': False, 'message': f'Score cannot exceed {max_points}'}, status=400)
            resp.scored_points = scored_points

        resp.comments = comments
        resp.is_na = is_na
        resp.needs_corrective_action = needs_ca

        resp.is_answered = True

        if is_na:
            resp.scored_points = Decimal('0.00')
            resp.comments = ''
            resp.needs_corrective_action = False

        resp.save()

        sec = resp.audit_section
        sec.calculate_section_score()
        sec.audit.calculate_totals()

        responses = sec.responses.all()
        total = responses.filter(is_na=False).count()
        answered = responses.filter(is_na=False, is_answered=True).count()

        return JsonResponse({
            'success': True,
            'section_progress': {str(sec.pk): {'answered': answered, 'total': total}},
        })


class FillRemainingView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = 'audits.change_audit'

    @transaction.atomic
    def post(self, request):
        audit_id = request.POST.get('audit_id')
        section_id = request.POST.get('section_id')

        if not audit_id:
            return JsonResponse({'success': False, 'message': 'Missing audit_id'}, status=400)

        qs = Audit.objects.all()
        user = request.user
        if not user.is_superuser:
            qs = qs.filter(
                Q(auditor=user) |
                Q(restaurant__in=user.restaurants.all())
            )
        audit = get_object_or_404(qs, pk=audit_id)

        if audit.is_submitted:
            return JsonResponse({'success': False, 'message': 'Audit already submitted'}, status=400)

        sections = audit.audit_sections.all()
        if section_id:
            sections = sections.filter(pk=section_id)

        filled_count = 0
        filled_responses = {}
        section_progress = {}

        for sec in sections:
            responses = sec.responses.filter(scored_points=0, is_na=False)
            for r in responses:
                r.scored_points = r.question.possible_points or Decimal('0.00')
                r.is_answered = True
                r.save()
                filled_count += 1
                filled_responses[str(r.pk)] = float(r.scored_points)

            sec.calculate_section_score()

            total = sec.responses.filter(is_na=False).count()
            answered = sec.responses.filter(is_na=False, is_answered=True).count()
            section_progress[str(sec.pk)] = {'answered': answered, 'total': total}

        audit.calculate_totals()

        return JsonResponse({
            'success': True,
            'message': f'Filled {filled_count} question(s) to max score',
            'filled_count': filled_count,
            'filled_responses': filled_responses,
            'section_progress': section_progress,
        })


class AuditSubmitJSONView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = 'audits.change_audit'

    def post(self, request, pk):
        qs = Audit.objects.all()
        user = request.user
        if not user.is_superuser:
            qs = qs.filter(
                Q(auditor=user) |
                Q(restaurant__in=user.restaurants.all())
            )
        audit = get_object_or_404(qs, pk=pk)

        if audit.is_submitted:
            return JsonResponse({'success': False, 'message': 'Audit already submitted'}, status=400)

        audit.calculate_totals()
        audit.is_submitted = True
        audit.save()

        if audit.auditor:
            Notification.objects.create(
                recipient=audit.auditor,
                notification_type=Notification.Type.AUDIT_SUBMITTED,
                title=f'Audit submitted for {audit.restaurant.name}',
                message=f'Grade: {audit.get_grade_display()} ({audit.total_percentage:.1f}%)',
                link=reverse('audits:result', args=[audit.pk]),
            )
        notify_restaurant_users(
            Notification.Type.AUDIT_SUBMITTED,
            f'Audit Completed: {audit.restaurant.name}',
            f'{audit.restaurant.name} scored {audit.total_percentage:.1f}% (Grade {audit.get_grade_display()}).',
            reverse('audits:result', args=[audit.pk]),
            audit.restaurant,
        )

        return JsonResponse({
            'success': True,
            'redirect_url': reverse('audits:result', args=[audit.pk]),
        })


class AuditQuestionResponsesJSONView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = 'audits.view_auditquestionresponse'

    def get(self, request, audit_pk):
        qs = AuditQuestionResponse.objects.filter(
            audit_section__audit__pk=audit_pk,
        ).select_related('question', 'audit_section__section').order_by('audit_section__section__order', 'question__order')
        data = [{
            'id': r.pk,
            'label': f'{r.audit_section.section.name} → {r.question.question_text[:60]}',
        } for r in qs]
        return JsonResponse({'responses': data})
