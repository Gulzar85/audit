from django import forms
from django.db import transaction
from django.contrib.auth import get_user_model
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Row, Column, HTML, Field, Div

from .models import Audit, AuditQuestionResponse, CorrectiveAction


class AuditForm(forms.ModelForm):
    class Meta:
        model = Audit
        fields = ['template', 'restaurant', 'audit_date',
                  'manager_on_duty', 'auditor']
        widgets = {
            'audit_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.attrs = {'novalidate': ''}

        for field_name in self.fields:
            self.fields[field_name].help_text = ''
            self.fields[field_name].label = ''

        self.fields['template'].empty_label = 'Select a template'
        self.fields['restaurant'].empty_label = 'Select a restaurant'
        self.fields['auditor'].empty_label = 'Select an auditor'

        if user and not user.is_superuser:
            self.fields['restaurant'].queryset = user.restaurants.all()
            self.fields['auditor'].queryset = self.fields['auditor'].queryset.filter(pk=user.pk)

        if user:
            self.fields['auditor'].initial = user

        self.helper.layout = Layout(
            HTML(
                '<div class="grid grid-cols-1 lg:grid-cols-2 gap-6">'
            ),
            Div(
                HTML(
                    '<div class="flex items-center gap-2 mb-4">'
                    '<i data-lucide="file-text" class="h-5 w-5 text-primary"></i>'
                    '<h3 class="font-semibold text-gray-800">Restaurant &amp; Template</h3>'
                    '</div>'
                ),
                Div(
                    Field('template', placeholder='Select audit template',
                          css_class='w-full rounded-lg border-gray-300 focus:border-primary focus:ring-2 focus:ring-primary/20'),
                    css_class='mb-4'
                ),
                Div(
                    Field('restaurant', placeholder='Select restaurant',
                          css_class='w-full rounded-lg border-gray-300 focus:border-primary focus:ring-2 focus:ring-primary/20'),
                    css_class='mb-4'
                ),
                css_class='bg-white rounded-xl border border-gray-200 p-5'
            ),
            Div(
                HTML(
                    '<div class="flex items-center gap-2 mb-4">'
                    '<i data-lucide="calendar-check" class="h-5 w-5 text-primary"></i>'
                    '<h3 class="font-semibold text-gray-800">Audit Details</h3>'
                    '</div>'
                ),
                Div(
                    Field('audit_date', placeholder='2026-06-16',
                          css_class='w-full rounded-lg border-gray-300 focus:border-primary focus:ring-2 focus:ring-primary/20'),
                    css_class='mb-4'
                ),
                Div(
                    Field('manager_on_duty', placeholder='e.g. Ali Khan',
                          css_class='w-full rounded-lg border-gray-300 focus:border-primary focus:ring-2 focus:ring-primary/20'),
                    css_class='mb-4'
                ),
                Div(
                    Field('auditor', placeholder='Select auditor',
                          css_class='w-full rounded-lg border-gray-300 focus:border-primary focus:ring-2 focus:ring-primary/20'),
                    css_class='mb-4'
                ),
                css_class='bg-white rounded-xl border border-gray-200 p-5'
            ),
            HTML('</div>'),
        )

    @transaction.atomic
    def save(self, commit=True):
        audit = super().save(commit=False)
        if commit:
            audit.save()
            self._generate_sections(audit)
        return audit

    def _generate_sections(self, audit):
        from .models import AuditSection, AuditQuestionResponse

        sections = audit.template.sections.all().prefetch_related('questions')
        for section in sections:
            audit_section = AuditSection.objects.create(
                audit=audit,
                section=section,
                possible_points=sum(
                    q.possible_points for q in section.questions.all()
                ),
            )
            for question in section.questions.all():
                AuditQuestionResponse.objects.create(
                    audit_section=audit_section,
                    question=question,
                )


class AuditScoreForm(forms.ModelForm):
    class Meta:
        model = AuditQuestionResponse
        fields = ['scored_points', 'comments', 'needs_corrective_action', 'is_na']
        widgets = {
            'comments': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.disable_csrf = True
        self.helper.layout = Layout(
            Row(
                Column('scored_points', css_class='w-24'),
                Column('is_na', css_class='w-32'),
                Column('needs_corrective_action', css_class='w-48'),
                css_class='flex items-end gap-4'
            ),
            'comments',
        )

    def clean_scored_points(self):
        value = self.cleaned_data['scored_points']
        if value is None:
            return 0
        return value

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('is_na'):
            cleaned['scored_points'] = 0
        return cleaned


class CorrectiveActionForm(forms.ModelForm):
    class Meta:
        model = CorrectiveAction
        fields = ['audit', 'question_response', 'description',
                  'risk_level', 'assigned_to', 'status', 'deadline', 'comments', 'evidence_image']
        widgets = {
            'deadline': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.Textarea(attrs={'rows': 3}),
            'comments': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        self.fields['audit'].empty_label = 'Select an audit'
        self.fields['question_response'].empty_label = 'Select a question'
        self.fields['question_response'].required = False
        self.fields['assigned_to'].empty_label = 'Select a user'
        self.fields['assigned_to'].required = False
        if user:
            qs = get_user_model().objects.filter(is_active=True)
            if not user.is_superuser:
                qs = qs.filter(restaurants__in=user.restaurants.all()).distinct()
            self.fields['assigned_to'].queryset = qs
            self.fields['assigned_to'].initial = user
        css = 'w-full rounded-xl border-slate-300 focus:border-red-400 focus:ring-2 focus:ring-red-200 outline-none'
        file_css = 'w-full rounded-xl border-slate-300 focus:border-red-400 focus:ring-2 focus:ring-red-200 outline-none file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-red-50 file:text-red-700 hover:file:bg-red-100'
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.attrs = {'novalidate': ''}
        self.helper.layout = Layout(
            Field('audit', css_class=css),
            Field('question_response', css_class=css),
            Field('description', css_class=css),
            Field('risk_level', css_class=css),
            Field('assigned_to', css_class=css),
            Field('status', css_class=css),
            Field('deadline', css_class=css),
            Field('comments', css_class=css),
            Field('evidence_image', css_class=file_css),
        )
