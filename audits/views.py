import csv
import json
import logging
import re

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import ValidationError
from decimal import Decimal, InvalidOperation
from django.db import transaction
from django.db.models import Q, Count, Avg, Case, When, F, Sum, Value, Subquery, IntegerField
from django.db.models.functions import TruncMonth, Coalesce
from django.forms import modelformset_factory
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, get_object_or_404, reverse
from django.template.loader import get_template
from django.utils import timezone
from django.views.generic import ListView, CreateView, DetailView, UpdateView, TemplateView, View
import datetime

from core.models import BusinessInfo, Notification
from core.security import rate_limit, log_security_event
from .forms import AuditForm, AuditScoreForm, CorrectiveActionForm
from .utils import notify_restaurant_users, notify_auditor_and_manager, auto_generate_corrective_actions
from .models import Audit, AuditTemplate, AuditSection, AuditQuestionResponse, CorrectiveAction

logger = logging.getLogger(__name__)



class AuditListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model = Audit
    template_name = 'audits/audit_list.html'
    context_object_name = 'audits'
    paginate_by = 20
    permission_required = 'audits.view_audit'

    def get_queryset(self):
        qs = Audit.objects.select_related(
            'restaurant', 'template', 'auditor'
        ).visible_to(self.request.user)

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

        return qs.order_by('-audit_date', '-created_at', '-pk')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Audits'
        ctx['grade_choices'] = Audit.Grade.choices
        ctx['current_filters'] = {
            k: v for k, v in self.request.GET.items() if v and k != 'page'
        }
        ctx['has_active_filters'] = any(k != 'page' for k in self.request.GET)
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
        cleaned = form.cleaned_data
        duplicate = Audit.objects.filter(
            template=cleaned.get('template'),
            restaurant=cleaned.get('restaurant'),
            audit_date=cleaned.get('audit_date'),
            is_archived=False,
        ).exists()
        if duplicate:
            return self.render_to_response(self.get_context_data(
                form=form,
                duplicate_error={
                    'restaurant': cleaned['restaurant'].name,
                    'template': cleaned['template'].name,
                    'audit_date': cleaned['audit_date'],
                },
            ))
        self.object = form.save()
        logger.info('Audit %s created for %s by %s', self.object.pk, self.object.restaurant, self.request.user)
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
        ).visible_to(self.request.user)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = f'Audit: {self.object.restaurant.name}'
        ctx['corrective_actions'] = self.object.corrective_actions.select_related(
            'assigned_to', 'restaurant'
        ).order_by('-created_at')
        return ctx


class AuditScoreView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    model = Audit
    template_name = 'audits/audit_score.html'
    permission_required = 'audits.change_audit'
    fields = []

    def get_queryset(self):
        qs = Audit.objects.visible_to(self.request.user)
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
            responses = sec.responses.all()
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
                photo_url = None
                if r.image:
                    try:
                        photo_url = r.image.url
                    except Exception:
                        photo_url = None
                resp_data.append({
                    'id': r.pk,
                    'scored': float(r.scored_points or 0),
                    'max': r.question.possible_points or 0,
                    'is_na': r.is_na,
                    'is_critical': r.question.is_critical,
                    'comments': r.comments or '',
                    'needs_ca': r.needs_corrective_action,
                    'is_answered': r.is_answered,
                    'photo_url': photo_url,
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
        audit = type(self.object).objects.select_for_update().get(pk=self.object.pk)

        if audit.is_submitted:
            messages.warning(request, 'This audit has already been submitted.')
            return redirect('audits:result', pk=audit.pk)

        sections = audit.audit_sections.prefetch_related('responses__question').all()
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
            all_instances = []
            for f in formsets:
                instances = f['formset'].save(commit=False)
                for instance in instances:
                    if not instance.is_answered:
                        instance.is_answered = True
                    all_instances.append(instance)

            if all_instances:
                AuditQuestionResponse.objects.bulk_update(
                    all_instances,
                    ['scored_points', 'comments', 'needs_corrective_action',
                     'is_na', 'image', 'is_answered']
                )

            for sec in audit.audit_sections.all():
                sec.calculate_section_score()

            audit.calculate_totals()
            audit.is_submitted = True
            audit.save()
            logger.info('Audit %s submitted via score form — grade %s (%.1f%%)', audit.pk, audit.get_grade_display(), audit.total_percentage)
            try:
                auto_generate_corrective_actions(audit)
            except Exception:
                logger.exception("auto_generate_corrective_actions failed for audit %s", audit.pk)
            try:
                email_context = {
                    'subject': f'Audit Completed: {audit.restaurant.name}',
                    'restaurant_name': audit.restaurant.name,
                    'score': audit.total_percentage or 0,
                    'grade': audit.grade,
                    'audit_date': audit.audit_date,
                    'template_name': audit.template.name,
                    'template_version': audit.template.version,
                    'auditor_name': audit.auditor.get_full_name() or audit.auditor.username if audit.auditor else 'N/A',
                    'result_url': request.build_absolute_uri(reverse('audits:result', args=[audit.pk])),
                    'company_name': BusinessInfo.load().company_name,
                }
                extra_recipients = [audit.auditor, audit.auditor.manager] if audit.auditor and audit.auditor.manager else [audit.auditor] if audit.auditor else None
                notify_restaurant_users(
                    Notification.Type.AUDIT_SUBMITTED,
                    f'Audit Completed: {audit.restaurant.name}',
                    f'{audit.restaurant.name} scored {audit.total_percentage:.1f}% (Grade {audit.get_grade_display()}).',
                    reverse('audits:result', args=[audit.pk]),
                    audit.restaurant,
                    email_context=email_context,
                    extra_recipients=extra_recipients,
                )
            except Exception:
                logger.exception("Email notification failed for audit %s", audit.pk)
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
        ).visible_to(self.request.user)
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
        ).visible_to(self.request.user)
        return qs

    def render_to_response(self, context, **response_kwargs):
        from xhtml2pdf import pisa
        from core.models import BusinessInfo
        from django.utils.text import slugify
        import re
        audit = self.object
        template = get_template('audits/audit_report_pdf.html')

        def abs_url(url):
            if not url:
                return None
            if url.startswith('http'):
                return url
            req = self.request
            return req.build_absolute_uri(url) if req else url

        for sec in audit.audit_sections.all():
            for resp in sec.responses.all():
                if resp.image:
                    try:
                        resp.pdf_image_url = abs_url(resp.image.url)
                    except Exception:
                        resp.pdf_image_url = None

        # Compute summary stats
        passed = failed = partial = na = total_answered = 0
        for sec in audit.audit_sections.all():
            for resp in sec.responses.all():
                if not resp.is_answered:
                    continue
                total_answered += 1
                if resp.is_na:
                    na += 1
                elif resp.scored_points == resp.question.possible_points:
                    passed += 1
                elif resp.scored_points == 0:
                    failed += 1
                else:
                    partial += 1

        total_questions = sum(
            len(sec.responses.all()) for sec in audit.audit_sections.all())

        # Duration
        duration = None
        if audit.submitted_at and audit.created_at:
            duration = audit.submitted_at - audit.created_at

        html_str = template.render({
            'audit': audit,
            'corrective_actions': audit.corrective_actions.all(),
            'business_info': BusinessInfo.load(),
            'summary': {
                'total': total_questions,
                'answered': total_answered,
                'passed': passed,
                'failed': failed,
                'partial': partial,
                'na': na,
            },
            'duration': duration,
        })

        # Sanitize filename to prevent path traversal and special characters
        restaurant_code = re.sub(r'[^\w\-.]', '', audit.restaurant.code)
        audit_date = audit.audit_date.isoformat()
        filename = f'audit_{restaurant_code}_{audit_date}.pdf'
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        pisa.CreatePDF(html_str, dest=response, encoding='utf-8')
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
        ctx['title'] = 'Audit Templates'
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
        ctx['title'] = self.object.name
        ctx['sections'] = sections
        ctx['total_questions'] = sum(len(list(s.questions.all())) for s in sections)
        ctx['total_points'] = sum(
            q.possible_points for s in sections for q in s.questions.all()
        )
        return ctx


class DashboardView(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    template_name = 'audits/dashboard.html'
    permission_required = 'audits.view_audit'

    def _base_qs(self):
        return Audit.objects.visible_to(self.request.user)

    def get_context_data(self, **kwargs):
        template_id = self.request.GET.get('template', '')
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Dashboard'

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

        ca_qs = CorrectiveAction.objects.visible_to(self.request.user)
        if selected_template_id:
            ca_qs = ca_qs.filter(audit__template_id=selected_template_id)
        ctx['open_ca'] = ca_qs.exclude(status__in=['COMPLETED', 'VERIFIED', 'CLOSED']).count()
        ctx['overdue_ca'] = ca_qs.filter(deadline__lt=timezone.now().date()).exclude(status__in=['COMPLETED', 'VERIFIED', 'CLOSED']).count()

        # CA aging buckets
        now = timezone.now()
        thirty_days_ago = now - timezone.timedelta(days=30)
        fourteen_days_ago = now - timezone.timedelta(days=14)
        seven_days_ago = now - timezone.timedelta(days=7)
        open_cas = ca_qs.exclude(status__in=['COMPLETED', 'VERIFIED', 'CLOSED'])
        ctx['ca_aging'] = {
            'critical': open_cas.filter(created_at__lte=thirty_days_ago).count(),
            'over_14': open_cas.filter(
                created_at__gt=thirty_days_ago,
                created_at__lte=fourteen_days_ago,
            ).count(),
            '7_14': open_cas.filter(
                created_at__gt=fourteen_days_ago,
                created_at__lte=seven_days_ago,
            ).count(),
            '0_7': open_cas.filter(created_at__gte=seven_days_ago).count(),
        }
        ctx['ca_aging_labels'] = json.dumps(['Critical', '14-30d', '7-14d', '0-7d'])
        ctx['ca_aging_data'] = json.dumps([
            ctx['ca_aging']['critical'],
            ctx['ca_aging']['over_14'],
            ctx['ca_aging']['7_14'],
            ctx['ca_aging']['0_7'],
        ])

        # Monthly close rate (last 6 months)
        six_months_ago = now - timezone.timedelta(days=180)
        monthly_closed = (
            CorrectiveAction.objects.filter(
                restaurant__in=ca_qs.values('restaurant'),
                status__in=['COMPLETED', 'VERIFIED', 'CLOSED'],
                updated_at__gte=six_months_ago,
            )
            .annotate(month=TruncMonth('updated_at'))
            .values('month')
            .annotate(count=Count('id'))
            .order_by('month')
        )
        monthly_close_map = {
            m['month'].strftime('%b %Y'): m['count']
            for m in monthly_closed if m['month']
        }
        current_month = now.replace(day=1)
        last_six_months = []
        for _ in range(6):
            last_six_months.insert(0, current_month)
            current_month = (current_month - datetime.timedelta(days=1)).replace(day=1)
        ctx['ca_monthly_close'] = json.dumps([
            {
                'month': month.strftime('%b'),
                'count': monthly_close_map.get(month.strftime('%b %Y'), 0),
            }
            for month in last_six_months
        ])

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
            'labels': [m['month'].strftime('%b') if m['month'] else '' for m in monthly],
            'data': [round(m['avg_score'], 1) if m['avg_score'] else 0 for m in monthly],
        } if monthly else None

        # --- Section-wise Analytics ---
        submitted_audit_ids = Subquery(submitted.values('pk'))

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

        # 5. Region Score Comparison
        region_scores = (
            submitted.values('restaurant__region__name')
            .annotate(avg=Avg('total_percentage'), count=Count('id'))
            .order_by('-avg')
        )
        ctx['region_scores'] = json.dumps([
            {
                'name': r['restaurant__region__name'] or 'Unassigned',
                'avg': float(round(r['avg'], 1)) if r['avg'] else 0,
                'count': r['count'],
            }
            for r in region_scores
        ])

        # 6. Top/Bottom 5 Restaurants by avg score
        restaurant_avg = (
            submitted.values('restaurant_id', 'restaurant__name')
            .annotate(
                avg=Avg('total_percentage'),
                count=Count('id')
            )
            .filter(count__gte=2)
            .order_by('-avg')
        )

        top5 = list(restaurant_avg[:5])
        bottom5 = list(reversed(restaurant_avg.order_by('avg')[:5]))

        ctx['top5_restaurants'] = json.dumps([
            {
                'name': r['restaurant__name'],
                'avg': round(float(r['avg']), 1) if r['avg'] else 0,
                'count': r['count'],
            }
            for r in top5
        ])

        ctx['bottom5_restaurants'] = json.dumps([
            {
                'name': r['restaurant__name'],
                'avg': round(float(r['avg']), 1) if r['avg'] else 0,
                'count': r['count'],
            }
            for r in bottom5
        ])

        # 7. Grade Trend by Restaurant (last 6 months)
        restaurant_trend_qs = list(
            AuditSection.objects.filter(
                audit_id__in=submitted_audit_ids,
                audit__submitted_at__gte=six_months_ago,
            )
            .annotate(month=TruncMonth('audit__audit_date'))
            .values('month', 'audit__restaurant__name')
            .annotate(avg_pct=Avg('section_percentage'))
            .order_by('month', 'audit__restaurant__name')
        )
        trend_by_restaurant = {}
        all_rest_months = set()
        for row in restaurant_trend_qs:
            name = row['audit__restaurant__name']
            label = row['month'].strftime('%b %Y') if row['month'] else ''
            if name not in trend_by_restaurant:
                trend_by_restaurant[name] = {}
            trend_by_restaurant[name][label] = float(round(row['avg_pct'], 1)) if row['avg_pct'] else None
            all_rest_months.add(label)
        sorted_rest_months = sorted(all_rest_months, key=lambda m: m.split()[-1] + m.split()[0] if m else '')
        ctx['restaurant_trend_series'] = json.dumps([
            {
                'name': name,
                'data': [trend_by_restaurant[name].get(m, None) for m in sorted_rest_months],
            }
            for name in trend_by_restaurant
        ])
        ctx['restaurant_trend_months'] = json.dumps(sorted_rest_months)

        # Bundle all chart data into a single JSON blob for the static JS to consume
        chart_data = {
            'scoreTrends': ctx.get('score_trends'),
            'gradeDistribution': list(ctx.get('grade_distribution', {}).items()),
            'avgScore': ctx.get('avg_score'),
            'sectionPerformance': json.loads(ctx.get('section_performance', '[]')),
            'sectionDeductions': json.loads(ctx.get('section_deductions', '[]')),
            'sectionTrendSeries': json.loads(ctx.get('section_trend_series', '[]')),
            'sectionTrendMonths': json.loads(ctx.get('section_trend_months', '[]')),
            'frequentFindings': json.loads(ctx.get('frequent_findings', '[]')),
            'caAgingData': json.loads(ctx.get('ca_aging_data', '[]')),
            'caAgingLabels': json.loads(ctx.get('ca_aging_labels', '[]')),
            'caMonthlyClose': json.loads(ctx.get('ca_monthly_close', '[]')),
            'regionScores': json.loads(ctx.get('region_scores', '[]')),
            'top5Restaurants': json.loads(ctx.get('top5_restaurants', '[]')),
            'bottom5Restaurants': json.loads(ctx.get('bottom5_restaurants', '[]')),
            'restaurantTrendSeries': json.loads(ctx.get('restaurant_trend_series', '[]')),
            'restaurantTrendMonths': json.loads(ctx.get('restaurant_trend_months', '[]')),
        }
        ctx['chart_data'] = chart_data

        return ctx


class DashboardExportView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = 'audits.view_audit'

    def get(self, request):
        qs = Audit.objects.select_related('restaurant', 'template', 'auditor').visible_to(request.user)

        from_date = request.GET.get('from_date', '')
        to_date = request.GET.get('to_date', '')
        if from_date:
            qs = qs.filter(audit_date__gte=from_date)
        if to_date:
            qs = qs.filter(audit_date__lte=to_date)

        def sanitize_csv_field(value):
            if not value:
                return value
            value = str(value)
            if value and value[0] in ('=', '+', '-', '@', '\t', '\n', '\r'):
                return "'" + value
            return value

        resp = HttpResponse(content_type='text/csv')
        resp['Content-Disposition'] = 'attachment; filename="audits_export.csv"'
        writer = csv.writer(resp)
        writer.writerow(['Restaurant', 'Template', 'Audit Date', 'Manager on Duty',
                         'Auditor', 'Score', 'Grade', 'Status', 'Submitted At'])
        for a in qs.iterator():
            writer.writerow([
                sanitize_csv_field(a.restaurant.name),
                sanitize_csv_field(a.template.name),
                a.audit_date,
                sanitize_csv_field(a.manager_on_duty),
                sanitize_csv_field(a.auditor.get_full_name() or a.auditor.username) if a.auditor else '',
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

    STATUS_PRIORITY = {
        'OPEN': 0,
        'IN_PROGRESS': 1,
        'COMPLETED': 2,
        'VERIFIED': 3,
        'CLOSED': 4,
    }

    def get_queryset(self):
        qs = CorrectiveAction.objects.select_related(
            'audit', 'restaurant', 'question_response__question'
        ).visible_to(self.request.user)

        status = self.request.GET.get('status', 'open')
        if status == 'open':
            qs = qs.exclude(status__in=['COMPLETED', 'VERIFIED', 'CLOSED'])
        elif status == 'completed':
            qs = qs.filter(status__in=['COMPLETED', 'VERIFIED', 'CLOSED'])

        risk = self.request.GET.get('risk', '')
        if risk in dict(CorrectiveAction.RiskLevel.choices):
            qs = qs.filter(risk_level=risk)

        restaurant_id = self.request.GET.get('restaurant', '')
        if restaurant_id and restaurant_id.isdigit():
            qs = qs.filter(restaurant_id=int(restaurant_id))

        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(description__icontains=q) |
                Q(restaurant__name__icontains=q) |
                Q(assigned_to__username__icontains=q) |
                Q(assigned_to__first_name__icontains=q) |
                Q(assigned_to__last_name__icontains=q)
            )

        overdue = self.request.GET.get('overdue', '')
        if overdue == '1':
            qs = qs.filter(deadline__lt=timezone.now().date()).exclude(status__in=['COMPLETED', 'VERIFIED', 'CLOSED'])

        priority = Case(
            *[When(status=status_key, then=Value(i)) for status_key, i in self.STATUS_PRIORITY.items()],
            default=Value(99),
            output_field=IntegerField(),
        )
        return qs.annotate(_status_priority=priority).order_by('_status_priority', 'deadline')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Corrective Actions'
        ctx['risk_choices'] = CorrectiveAction.RiskLevel.choices
        filters = {k: v for k, v in self.request.GET.items() if v and k != 'page'}
        ctx['current_filters'] = filters
        ctx['has_active_filters'] = any((k, v) != ('status', 'open') for k, v in filters.items())
        return ctx


class CorrectiveActionCompleteView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = 'audits.change_correctiveaction'

    def _get_action_or_404(self, request, pk):
        return get_object_or_404(CorrectiveAction.objects.visible_to(request.user), pk=pk)

    @transaction.atomic
    def post(self, request, pk):
        action = CorrectiveAction.objects.select_for_update().get(pk=self._get_action_or_404(request, pk).pk)
        user = request.user

        try:
            if action.status in (action.Status.COMPLETED, action.Status.VERIFIED, action.Status.CLOSED):
                action.transition_to(action.Status.OPEN, request.user)
                msg = 'reopened'
            elif action.status in (action.Status.OPEN, action.Status.IN_PROGRESS):
                action.transition_to(action.Status.COMPLETED, request.user)
                msg = 'completed'
            else:
                # Guard against future state additions
                msg = 'updated'
        except ValidationError as e:
            messages.error(request, e.messages[0])
            return redirect('audits:corrective_actions')

        action.save()

        if msg == 'completed':
            link = reverse('audits:corrective_action_edit', args=[action.pk])
            email_context = {
                'subject': f'CA Completed: {action.restaurant.name}',
                'restaurant_name': action.restaurant.name,
                'risk_level': action.get_risk_level_display(),
                'description': action.description,
                'completed_by': user.get_full_name() or user.username,
                'deadline': action.deadline,
                'ca_url': request.build_absolute_uri(link),
            }
            if action.audit and action.audit.auditor:
                notify_auditor_and_manager(
                    Notification.Type.CA_COMPLETED,
                    f'Corrective Action Completed: {action.restaurant.name}',
                    f'A {action.get_risk_level_display()} corrective action has been completed for {action.restaurant.name}.',
                    link,
                    action.audit.auditor,
                    email_context=email_context,
                )

        messages.success(request, f'Corrective action {msg}.')
        return redirect('audits:corrective_actions')


class CorrectiveActionVerifyView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = 'audits.verify_correctiveaction'

    def _get_action_or_404(self, request, pk):
        return get_object_or_404(CorrectiveAction.objects.visible_to(request.user), pk=pk)

    @transaction.atomic
    def post(self, request, pk):
        action = CorrectiveAction.objects.select_for_update().get(pk=self._get_action_or_404(request, pk).pk)
        user = request.user

        try:
            action.transition_to(action.Status.VERIFIED, request.user)
        except ValidationError as e:
            messages.error(request, e.messages[0])
            return redirect('audits:corrective_actions')

        action.save()

        link = reverse('audits:corrective_action_edit', args=[action.pk])
        email_context = {
            'subject': f'CA Verified: {action.restaurant.name}',
            'restaurant_name': action.restaurant.name,
            'risk_level': action.get_risk_level_display(),
            'description': action.description,
            'verified_by': user.get_full_name() or user.username,
            'deadline': action.deadline,
            'ca_url': request.build_absolute_uri(link),
        }
        extra_recipients = [action.assigned_to] if action.assigned_to else []
        if action.audit.auditor and action.audit.auditor.manager:
            extra_recipients.append(action.audit.auditor.manager)
        notify_restaurant_users(
            Notification.Type.CA_VERIFIED,
            f'Corrective Action Verified: {action.restaurant.name}',
            f'A {action.get_risk_level_display()} corrective action has been verified for {action.restaurant.name}.',
            link,
            action.restaurant,
            email_context=email_context,
            extra_recipients=extra_recipients or None,
        )

        messages.success(request, 'Corrective action verified successfully.')
        return redirect('audits:corrective_actions')


class CorrectiveActionCloseView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = 'audits.verify_correctiveaction'

    def _get_action_or_404(self, request, pk):
        return get_object_or_404(CorrectiveAction.objects.visible_to(request.user), pk=pk)

    @transaction.atomic
    def post(self, request, pk):
        action = CorrectiveAction.objects.select_for_update().get(pk=self._get_action_or_404(request, pk).pk)
        user = request.user

        try:
            action.transition_to(action.Status.CLOSED, request.user)
        except ValidationError as e:
            messages.error(request, e.messages[0])
            return redirect('audits:corrective_actions')

        action.save()

        link = reverse('audits:corrective_action_edit', args=[action.pk])
        email_context = {
            'subject': f'CA Closed: {action.restaurant.name}',
            'restaurant_name': action.restaurant.name,
            'risk_level': action.get_risk_level_display(),
            'description': action.description,
            'closed_by': user.get_full_name() or user.username,
            'deadline': action.deadline,
            'ca_url': request.build_absolute_uri(link),
        }
        extra_recipients = [action.assigned_to] if action.assigned_to else []
        if action.audit.auditor and action.audit.auditor.manager:
            extra_recipients.append(action.audit.auditor.manager)
        notify_restaurant_users(
            Notification.Type.CA_CLOSED,
            f'Corrective Action Closed: {action.restaurant.name}',
            f'A {action.get_risk_level_display()} corrective action has been closed for {action.restaurant.name}.',
            link,
            action.restaurant,
            email_context=email_context,
            extra_recipients=extra_recipients or None,
        )
        if action.audit and action.audit.auditor:
            notify_auditor_and_manager(
                Notification.Type.CA_CLOSED,
                f'Corrective Action Closed: {action.restaurant.name}',
                f'A {action.get_risk_level_display()} corrective action has been closed for {action.restaurant.name}.',
                link,
                action.audit.auditor,
                email_context=email_context,
            )

        messages.success(request, 'Corrective action closed successfully.')
        return redirect('audits:corrective_actions')


class CorrectiveActionDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = CorrectiveAction
    template_name = 'audits/correctiveaction_detail.html'
    context_object_name = 'action'
    permission_required = 'audits.view_correctiveaction'

    def get_queryset(self):
        return CorrectiveAction.objects.select_related(
            'audit__template', 'audit__auditor',
            'restaurant', 'assigned_to',
            'question_response__question__section',
        ).visible_to(self.request.user)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        action = self.object
        ctx['title'] = f'CA: {action.restaurant.name} — {action.description[:60]}'

        # Build timeline from django-simple-history records
        history = action.history.all().order_by('history_date', 'history_id')
        timeline = []
        previous_status = None
        status_labels = dict(CorrectiveAction.Status.choices)
        for h in history:
            entry = {
                'date': h.history_date,
                'user': h.history_user,
                'type': h.history_type,
                'status': h.status,
                'status_display': status_labels.get(h.status, h.status),
                'changed_fields': h.get_changed_fields() if hasattr(h, 'get_changed_fields') else [],
            }
            # Detect status transitions
            if h.status != previous_status and previous_status is not None:
                entry['from_status'] = previous_status
                entry['to_status'] = h.status
                entry['from_status_display'] = status_labels.get(previous_status, previous_status)
                entry['to_status_display'] = status_labels.get(h.status, h.status)
                entry['is_status_change'] = True
            else:
                entry['is_status_change'] = False
            previous_status = h.status
            timeline.append(entry)

        ctx['timeline'] = list(reversed(timeline))  # newest first
        ctx['audit'] = action.audit
        return ctx


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
            audit = Audit.objects.visible_to(self.request.user).filter(pk=audit_pk).first()
            if audit:
                kwargs['instance'] = CorrectiveAction(audit=audit, restaurant=audit.restaurant)
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Create Corrective Action'
        return ctx

    def form_valid(self, form):
        response = super().form_valid(form)
        logger.info('CorrectiveAction %s created by %s', self.object.pk, self.request.user)
        messages.success(self.request, 'Corrective action created successfully.')
        return response

    def get_success_url(self):
        return reverse('audits:corrective_actions')


class CorrectiveActionUpdateView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    model = CorrectiveAction
    form_class = CorrectiveActionForm
    template_name = 'audits/correctiveaction_form.html'
    permission_required = 'audits.change_correctiveaction'
    context_object_name = 'action'

    def dispatch(self, request, *args, **kwargs):
        qs = self.get_queryset()
        obj = get_object_or_404(qs, pk=kwargs.get('pk'))
        if not request.user.has_perm('audits.verify_correctiveaction') and obj.status in (obj.Status.VERIFIED, obj.Status.CLOSED):
            messages.error(request, 'You cannot edit a verified or closed corrective action.')
            return redirect('audits:corrective_actions')
        return super().dispatch(request, *args, **kwargs)


    def get_queryset(self):
        return CorrectiveAction.objects.visible_to(self.request.user)

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
        logger.info('CorrectiveAction %s updated by %s', form.instance.pk, self.request.user)
        messages.success(self.request, 'Corrective action updated successfully.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('audits:corrective_actions')


class CorrectiveActionDeleteView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = 'audits.delete_correctiveaction'

    def get_queryset(self):
        return CorrectiveAction.objects.visible_to(self.request.user)

    def post(self, request, pk):
        qs = self.get_queryset()
        action = get_object_or_404(qs, pk=pk)
        user = request.user
        # Closed actions are kept for the audit trail (only admins can remove them)
        if action.status == 'CLOSED' and user.role != 'admin' and not user.is_superuser:
            messages.error(request, 'Closed corrective actions cannot be deleted.')
            return redirect('audits:corrective_actions')
        logger.info('CorrectiveAction %s deleted by %s', pk, request.user)
        action.delete()
        messages.success(request, 'Corrective action deleted.')
        return redirect('audits:corrective_actions')


class AuditSubmitView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = 'audits.change_audit'

    def _get_audit_or_404(self, request, pk):
        return get_object_or_404(Audit.objects.visible_to(request.user), pk=pk)

    @transaction.atomic
    def post(self, request, pk):
        audit = self._get_audit_or_404(request, pk)
        # Lock row to prevent race condition on submission
        audit = type(audit).objects.select_for_update().get(pk=audit.pk)

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
        return Audit.objects.visible_to(self.request.user)

    def post(self, request, pk):
        qs = self.get_queryset()
        audit = get_object_or_404(qs, pk=pk)
        if request.user.is_superuser:
            audit.delete()
            logger.info('Audit %s hard-deleted by superuser %s', pk, request.user)
            messages.success(request, 'Audit deleted permanently.')
            return redirect('audits:list')
        audit = type(audit).objects.select_for_update().get(pk=audit.pk)
        if audit.is_submitted:
            messages.warning(request, 'Submitted audits cannot be deleted. Archive them instead.')
            return redirect('audits:detail', pk=pk)
        audit.is_archived = True
        audit.save(update_fields=['is_archived', 'updated_at'])
        logger.info('Audit %s archived (soft-deleted) by %s', pk, request.user)
        messages.success(request, 'Audit archived successfully.')
        return redirect('audits:list')



class SaveResponseView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = 'audits.change_audit'

    @transaction.atomic
    def post(self, request):
        # Rate limiting
        from core.security import check_suspicious_activity

        if check_suspicious_activity(request, 'save_response', threshold=100):
            return JsonResponse(
                {
                    'success': False,
                    'message': 'Too many requests. Please try again later.'
                },
                status=429
            )

        response_id = request.POST.get('response_id')
        if not response_id:
            return JsonResponse(
                {
                    'success': False,
                    'message': 'Missing response_id'
                },
                status=400
            )

        qs = AuditQuestionResponse.objects.select_related(
            'audit_section__audit',
            'question'
        )

        user = request.user

        if not user.is_superuser:
            role = getattr(user, 'role', None)
            if role == user.Roles.AUDITOR:
                qs = qs.filter(audit_section__audit__auditor=user)
            elif role == user.Roles.RESTAURANT_USER:
                qs = qs.filter(
                    audit_section__audit__restaurant__in=user.restaurants.all(),
                    audit_section__audit__is_submitted=True,
                )
            else:
                qs = qs.filter(
                    Q(audit_section__audit__auditor=user) |
                    Q(audit_section__audit__restaurant__in=user.restaurants.all()) |
                    Q(audit_section__audit__auditor__manager=user)
                )

        resp = get_object_or_404(qs, pk=response_id)

        if resp.audit_section.audit.is_submitted:
            return JsonResponse(
                {
                    'success': False,
                    'message': 'Audit already submitted'
                },
                status=400
            )

        scored_points = request.POST.get('scored_points')
        comments = request.POST.get('comments', '').strip()
        is_na = request.POST.get('is_na') == 'true'
        needs_ca = request.POST.get('needs_ca') == 'true'

        interaction_detected = False

        # -----------------------------
        # Score (Pass / Fail / Manual)
        # -----------------------------
        if scored_points not in (None, ''):
            interaction_detected = True

            try:
                scored_points = Decimal(scored_points)
            except InvalidOperation:
                return JsonResponse(
                    {
                        'success': False,
                        'message': 'Invalid score'
                    },
                    status=400
                )

            max_points = resp.question.possible_points or Decimal('0')

            if scored_points < 0 or scored_points > max_points:
                return JsonResponse(
                    {
                        'success': False,
                        'message': f'Score cannot exceed {max_points}'
                    },
                    status=400
                )

            resp.scored_points = scored_points

        # -----------------------------
        # Comment
        # -----------------------------
        if comments:
            interaction_detected = True

        resp.comments = comments

        # -----------------------------
        # Photo
        # -----------------------------
        if 'image' in request.FILES:
            interaction_detected = True
            resp.image = request.FILES['image']

        # -----------------------------
        # N/A
        # -----------------------------
        if is_na:
            interaction_detected = True
            resp.scored_points = Decimal('0.00')
            resp.needs_corrective_action = False

        resp.is_na = is_na

        # -----------------------------
        # Corrective Action
        # -----------------------------
        if needs_ca and not is_na:
            interaction_detected = True

        resp.needs_corrective_action = needs_ca and not is_na

        # -----------------------------
        # Final Answered Status
        # -----------------------------
        resp.is_answered = interaction_detected and not is_na

        resp.save()

        # Recalculate section score
        sec = resp.audit_section
        sec.calculate_section_score()

        responses = sec.responses.all()

        total = responses.filter(is_na=False).count()
        answered = responses.filter(
            is_na=False,
            is_answered=True
        ).count()

        photo_url = None
        if resp.image:
            try:
                photo_url = resp.image.url
            except Exception:
                pass

        return JsonResponse({
            'success': True,
            'photo_url': photo_url,
            'section_progress': {
                str(sec.pk): {
                    'answered': answered,
                    'total': total
                }
            }
        })


class FillRemainingView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = 'audits.change_audit'

    @transaction.atomic
    def post(self, request):
        # Rate limiting: prevent abuse
        from core.security import check_suspicious_activity
        if check_suspicious_activity(request, 'fill_remaining', threshold=50):
            return JsonResponse(
                {'success': False, 'message': 'Too many requests. Please try again later.'},
                status=429
            )
        
        audit_id = request.POST.get('audit_id')
        section_id = request.POST.get('section_id')

        if not audit_id:
            return JsonResponse({'success': False, 'message': 'Missing audit_id'}, status=400)

        audit = get_object_or_404(Audit.objects.visible_to(request.user), pk=audit_id)
        # Lock row
        audit = type(audit).objects.select_for_update().get(pk=audit.pk)

        if audit.is_submitted:
            return JsonResponse({'success': False, 'message': 'Audit already submitted'}, status=400)

        filled_count = 0
        filled_responses = {}
        section_progress = {}
        section_ids = set()

        unanswered = AuditQuestionResponse.objects.filter(
            audit_section__audit=audit,
            is_answered=False,
            is_na=False,
        ).select_related('question', 'audit_section')
        if section_id:
            unanswered = unanswered.filter(audit_section_id=section_id)

        for r in unanswered:
            r.scored_points = r.question.possible_points or Decimal('0.00')
            r.is_answered = True
            filled_count += 1
            filled_responses[str(r.pk)] = float(r.scored_points)
            section_ids.add(r.audit_section_id)

        if filled_count:
            AuditQuestionResponse.objects.bulk_update(
                list(unanswered), ['scored_points', 'is_answered']
            )

        for sec_id in section_ids:
            sec = AuditSection.objects.get(pk=sec_id)
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


class ClearAllResponsesView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = 'audits.change_audit'

    @transaction.atomic
    def post(self, request):
        from core.security import check_suspicious_activity
        if check_suspicious_activity(request, 'clear_all', threshold=20):
            return JsonResponse(
                {'success': False, 'message': 'Too many requests. Please try again later.'},
                status=429
            )

        audit_id = request.POST.get('audit_id')
        if not audit_id:
            return JsonResponse({'success': False, 'message': 'Missing audit_id'}, status=400)

        audit = get_object_or_404(Audit.objects.visible_to(request.user), pk=audit_id)
        audit = type(audit).objects.select_for_update().get(pk=audit.pk)

        if audit.is_submitted:
            return JsonResponse({'success': False, 'message': 'Audit already submitted'}, status=400)

        affected = AuditQuestionResponse.objects.filter(
            audit_section__audit=audit,
            is_na=False,
        )

        count = affected.update(
            scored_points=Decimal('0.00'),
            comments='',
            needs_corrective_action=False,
            is_answered=False,
            image=None,
        )

        section_ids = set(
            affected.values_list('audit_section_id', flat=True)
        )
        section_progress = {}
        for sec_id in section_ids:
            sec = AuditSection.objects.get(pk=sec_id)
            sec.calculate_section_score()
            total = sec.responses.filter(is_na=False).count()
            answered = sec.responses.filter(is_na=False, is_answered=True).count()
            section_progress[str(sec.pk)] = {'answered': answered, 'total': total}

        audit.calculate_totals()

        return JsonResponse({
            'success': True,
            'message': f'Cleared {count} response(s)',
            'cleared_count': count,
            'section_progress': section_progress,
        })


class AuditSubmitJSONView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = 'audits.change_audit'

    def post(self, request, pk):
        # Rate limiting: critical operation
        from core.security import check_suspicious_activity, log_security_event
        if check_suspicious_activity(request, 'audit_submit', threshold=30):
            log_security_event(
                'AUDIT_SUBMIT_RATE_LIMITED',
                request.user,
                f'Audit {pk}',
                severity='WARNING'
            )
            return JsonResponse(
                {'success': False, 'message': 'Too many requests. Please try again later.'},
                status=429
            )
        
        audit = get_object_or_404(Audit.objects.visible_to(request.user), pk=pk)
        # Lock row to prevent race condition on submission
        audit = type(audit).objects.select_for_update().get(pk=audit.pk)

        if audit.is_submitted:
            return JsonResponse({'success': False, 'message': 'Audit already submitted'}, status=400)

        audit.calculate_totals()
        audit.is_submitted = True
        audit.save()
        logger.info('Audit %s submitted — grade %s (%.1f%%)', audit.pk, audit.get_grade_display(), audit.total_percentage)
        try:
            auto_generate_corrective_actions(audit)
        except Exception:
            logger.exception("auto_generate_corrective_actions failed for audit %s", audit.pk)
        try:
            email_context = {
                'subject': f'Audit Completed: {audit.restaurant.name}',
                'restaurant_name': audit.restaurant.name,
                'score': audit.total_percentage,
                'grade': audit.get_grade_display(),
                'audit_date': audit.audit_date,
                'template_name': audit.template.name,
                'template_version': audit.template.version,
                'auditor_name': audit.auditor.get_full_name() or audit.auditor.username if audit.auditor else 'N/A',
                'result_url': request.build_absolute_uri(reverse('audits:result', args=[audit.pk])),
            }
            extra_recipients = [audit.auditor, audit.auditor.manager] if audit.auditor and audit.auditor.manager else [audit.auditor] if audit.auditor else None
            notify_restaurant_users(
                Notification.Type.AUDIT_SUBMITTED,
                f'Audit Completed: {audit.restaurant.name}',
                f'{audit.restaurant.name} scored {audit.total_percentage:.1f}% (Grade {audit.get_grade_display()}).',
                reverse('audits:result', args=[audit.pk]),
                audit.restaurant,
                email_context=email_context,
                extra_recipients=extra_recipients,
            )
        except Exception:
            logger.exception("Email notification failed for audit %s", audit.pk)

        return JsonResponse({
            'success': True,
            'redirect_url': reverse('audits:result', args=[audit.pk]),
        })


class AuditQuestionResponsesJSONView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = 'audits.view_auditquestionresponse'

    def get(self, request, audit_pk):
        qs = AuditQuestionResponse.objects.filter(
            audit_section__audit__pk=audit_pk,
            audit_section__audit__is_archived=False,
        ).select_related('question', 'audit_section__section').order_by('audit_section__section__order', 'question__order')

        user = request.user
        if not user.is_superuser and getattr(user, 'role', None) != user.Roles.ADMIN:
            role = getattr(user, 'role', None)
            if role == user.Roles.AUDITOR:
                qs = qs.filter(audit_section__audit__auditor=user)
            elif role == user.Roles.RESTAURANT_USER:
                qs = qs.filter(
                    audit_section__audit__restaurant__in=user.restaurants.all(),
                    audit_section__audit__is_submitted=True,
                )
            else:
                qs = qs.filter(
                    Q(audit_section__audit__auditor=user) |
                    Q(audit_section__audit__restaurant__in=user.restaurants.all()) |
                    Q(audit_section__audit__auditor__manager=user)
                )

        data = [{
            'id': r.pk,
            'label': f'{r.audit_section.section.name} → {r.question.question_text[:60]}',
        } for r in qs]
        return JsonResponse({'responses': data})


class AuditUsersJSONView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = 'audits.view_correctiveaction'

    def get(self, request, audit_pk):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        from audits.models import Audit
        audit = get_object_or_404(Audit.objects.visible_to(request.user), pk=audit_pk)
        qs = User.objects.filter(is_active=True, restaurants=audit.restaurant).distinct()
        user = request.user
        if not user.is_superuser and getattr(user, 'role', None) != user.Roles.ADMIN:
            qs = qs.filter(
                Q(restaurants__in=user.restaurants.all()) |
                Q(restaurants=audit.restaurant, role=User.Roles.RESTAURANT_USER)
            )
        data = [{
            'id': u.pk,
            'label': u.get_full_name() or u.username,
        } for u in qs.order_by('username')]
        return JsonResponse({'users': data})
