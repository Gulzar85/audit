from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.contrib.auth import get_user_model
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Row, Column, HTML, Field, Div

from .models import Audit, AuditQuestionResponse, CorrectiveAction, validate_uploaded_image


class AuditForm(forms.ModelForm):
    class Meta:
        model = Audit
        fields = ['template', 'restaurant', 'audit_date',
                  'manager_on_duty', 'auditor', 'auditor_signature', 'auditee_signature']
        widgets = {
            'audit_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        self.user = user
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.attrs = {'novalidate': ''}
        self.helper.form_show_labels = False

        for field_name in self.fields:
            self.fields[field_name].help_text = ''

        label_css = 'block text-xs font-bold uppercase tracking-widest text-slate-500 mb-1.5'
        input_css = 'w-full px-3.5 py-2.5 rounded-xl border border-slate-300 bg-white text-sm text-slate-900 focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none transition-all placeholder:text-slate-400'

        self.fields['template'].empty_label = 'Select a template'
        self.fields['restaurant'].empty_label = 'Select a restaurant'
        self.fields['auditor'].empty_label = 'Select an auditor'

        if user:
            if not user.is_superuser:
                self.fields['restaurant'].queryset = user.restaurants.all()
                self.fields['auditor'].queryset = self.fields['auditor'].queryset.filter(pk=user.pk)
                self.fields['auditor'].disabled = True
            self.fields['auditor'].initial = user

        self.helper.layout = Layout(
            HTML(
                '<div class="grid grid-cols-1 lg:grid-cols-2 gap-5">'
            ),
            Div(
                HTML(
                    '<div class="flex items-center gap-2.5 mb-5 pb-3 border-b border-slate-100">'
                    '<div class="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">'
                    '<i data-lucide="store" class="w-4 h-4 text-primary"></i></div>'
                    '<div><h3 class="text-sm font-bold text-slate-800">Restaurant &amp; Template</h3>'
                    '<p class="text-[11px] text-slate-400">Select the location and checklist</p></div></div>'
                ),
                Div(
                    HTML('<label class="' + label_css + '">Template <span class="text-danger">*</span></label>'),
                    Field('template', css_class=input_css),
                    css_class='mb-4'
                ),
                Div(
                    HTML('<label class="' + label_css + '">Restaurant <span class="text-danger">*</span></label>'),
                    Field('restaurant', css_class=input_css),
                    css_class='mb-4'
                ),
                css_class='bg-white rounded-2xl border border-slate-200/80 p-5 shadow-sm'
            ),
            Div(
                HTML(
                    '<div class="flex items-center gap-2.5 mb-5 pb-3 border-b border-slate-100">'
                    '<div class="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">'
                    '<i data-lucide="clipboard-check" class="w-4 h-4 text-primary"></i></div>'
                    '<div><h3 class="text-sm font-bold text-slate-800">Audit Details</h3>'
                    '<p class="text-[11px] text-slate-400">Date, personnel and signatures</p></div></div>'
                ),
                Div(
                    HTML('<label class="' + label_css + '">Audit Date <span class="text-danger">*</span></label>'),
                    Field('audit_date', css_class=input_css),
                    css_class='mb-4'
                ),
                Div(
                    HTML('<label class="' + label_css + '">Manager on Duty <span class="text-danger">*</span></label>'),
                    Field('manager_on_duty', css_class=input_css, placeholder='e.g. John Smith'),
                    css_class='mb-4'
                ),
                Div(
                    HTML('<label class="' + label_css + '">Auditor</label>'),
                    Field('auditor', css_class=input_css),
                    css_class='mb-4'
                ),
                css_class='bg-white rounded-2xl border border-slate-200/80 p-5 shadow-sm'
            ),
            HTML('</div>'),
        )

    def clean(self):
        cleaned_data = super().clean()
        restaurant = cleaned_data.get('restaurant')
        
        # Validate that non-superuser can access the selected restaurant
        if self.user and not self.user.is_superuser and restaurant:
            if restaurant not in self.user.restaurants.all():
                self.add_error('restaurant', 'You do not have permission to access this restaurant.')
        
        return cleaned_data

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
        fields = ['scored_points', 'comments', 'needs_corrective_action', 'is_na', 'image']
        widgets = {
            'comments': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
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
        self.user = user
        self.fields['audit'].empty_label = 'Select an audit'
        self.fields['question_response'].empty_label = 'Select a question'
        self.fields['question_response'].required = False
        self.fields['assigned_to'].empty_label = 'Select a user'
        self.fields['assigned_to'].required = False
        if user:
            from .models import Audit, AuditQuestionResponse
            qs = get_user_model().objects.filter(is_active=True)
            if not user.is_superuser:
                qs = qs.filter(restaurants__in=user.restaurants.all()).distinct()
                self.fields['audit'].queryset = Audit.objects.filter(
                    restaurant__in=user.restaurants.all(), is_archived=False
                )
                self.fields['question_response'].queryset = AuditQuestionResponse.objects.filter(
                    audit_section__audit__restaurant__in=user.restaurants.all()
                ).select_related('question', 'audit_section__section')
            self.fields['assigned_to'].queryset = qs
            self.fields['assigned_to'].initial = user

            # Restaurant users: lock sensitive fields on existing CAs
            if user.role == 'restaurant_user' and self.instance.pk:
                for field in ('audit', 'question_response', 'risk_level', 'assigned_to', 'status'):
                    self.fields[field].disabled = True
                self.fields['description'].disabled = True
        css = 'w-full rounded-xl border-slate-300 focus:border-red-400 focus:ring-2 focus:ring-red-200 outline-none'
        file_css = 'w-full rounded-xl border-slate-300 focus:border-red-400 focus:ring-2 focus:ring-red-200 outline-none file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-red-50 file:text-red-700 hover:file:bg-red-100'
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.attrs = {'novalidate': ''}
        self.helper.layout = Layout(
            HTML(
                '<div class="grid grid-cols-1 lg:grid-cols-2 gap-6">'
            ),
            Div(
                HTML(
                    '<div class="flex items-center gap-2 mb-4">'
                    '<i data-lucide="search" class="h-5 w-5 text-primary"></i>'
                    '<h3 class="font-semibold text-gray-800">Audit &amp; Question</h3>'
                    '</div>'
                ),
                Div(Field('audit', css_class=css), css_class='mb-4'),
                Div(Field('question_response', css_class=css, attrs={'data-initial': ''}), css_class='mb-4'),
                css_class='glass rounded-xl p-5'
            ),
            Div(
                HTML(
                    '<div class="flex items-center gap-2 mb-4">'
                    '<i data-lucide="align-left" class="h-5 w-5 text-primary"></i>'
                    '<h3 class="font-semibold text-gray-800">Action Details</h3>'
                    '</div>'
                ),
                Div(Field('description', css_class=css + ' resize-vertical min-h-[80px]'), css_class='mb-4'),
                Div(Field('risk_level', css_class=css), css_class='mb-4'),
                Div(Field('status', css_class=css), css_class='mb-4'),
                css_class='glass rounded-xl p-5'
            ),
            HTML('</div>'),
            HTML(
                '<div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-6">'
            ),
            Div(
                HTML(
                    '<div class="flex items-center gap-2 mb-4">'
                    '<i data-lucide="user-check" class="h-5 w-5 text-primary"></i>'
                    '<h3 class="font-semibold text-gray-800">Assignment</h3>'
                    '</div>'
                ),
                Div(Field('assigned_to', css_class=css), css_class='mb-4'),
                Div(Field('deadline', css_class=css + ' [color-scheme:light]'), css_class='mb-4'),
                css_class='glass rounded-xl p-5'
            ),
            Div(
                HTML(
                    '<div class="flex items-center gap-2 mb-4">'
                    '<i data-lucide="paperclip" class="h-5 w-5 text-primary"></i>'
                    '<h3 class="font-semibold text-gray-800">Additional</h3>'
                    '</div>'
                ),
                Div(Field('comments', css_class=css + ' resize-vertical'), css_class='mb-4'),
                Div(Field('evidence_image', css_class=file_css), css_class='mb-4'),
                css_class='glass rounded-xl p-5'
            ),
            HTML('</div>'),
        )

    def clean_evidence_image(self):
        file = self.cleaned_data.get('evidence_image')
        if file:
            validate_uploaded_image(file)
        return file

    def clean_status(self):
        status = self.cleaned_data.get('status')
        if not self.instance.pk:
            return status

        previous = CorrectiveAction.objects.get(pk=self.instance.pk).status
        user = getattr(self, 'user', None)

        VALID_TRANSITIONS = {
            CorrectiveAction.Status.OPEN: {'IN_PROGRESS', 'COMPLETED'},
            CorrectiveAction.Status.IN_PROGRESS: {'COMPLETED'},
            CorrectiveAction.Status.COMPLETED: {'VERIFIED'},
            CorrectiveAction.Status.VERIFIED: {'CLOSED'},
            CorrectiveAction.Status.CLOSED: set(),
        }

        if status != previous:
            allowed = VALID_TRANSITIONS.get(previous, set()) | {'OPEN'}
            if status not in allowed:
                raise ValidationError(
                    f'Cannot change from {previous} to {status}. '
                    f'Allowed: {", ".join(sorted(allowed))}'
                )

            # Restaurant users cannot set VERIFIED or CLOSED
            if user and user.role == 'restaurant_user' and status in ('VERIFIED', 'CLOSED'):
                raise ValidationError(
                    'Restaurant users cannot verify or close corrective actions.'
                )

        return status

    def clean(self):
        cleaned_data = super().clean()
        from django.utils import timezone

        deadline = cleaned_data.get('deadline')
        if self.instance.pk is None:  # Only enforce on creation
            if deadline and deadline < timezone.now().date():
                self.add_error('deadline', 'Deadline cannot be in the past.')

        return cleaned_data
