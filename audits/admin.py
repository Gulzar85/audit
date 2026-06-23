from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import (
    AuditTemplate, Section, Question,
    Audit, AuditSection, AuditQuestionResponse, CorrectiveAction
)


class AuditSectionInline(admin.TabularInline):
    model = AuditSection
    extra = 0
    readonly_fields = ['section', 'scored_points',
                       'possible_points', 'section_percentage', 'has_critical_failure']
    can_delete = False
    max_num = 0

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class CorrectiveActionInline(admin.TabularInline):
    model = CorrectiveAction
    extra = 0
    fields = ['risk_level', 'deadline', 'status', 'assigned_to']
    readonly_fields = ['risk_level', 'deadline', 'status', 'assigned_to']


@admin.register(AuditTemplate)
class AuditTemplateAdmin(SimpleHistoryAdmin):
    list_display = ['name', 'version', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['name']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Section)
class SectionAdmin(SimpleHistoryAdmin):
    list_display = ['name', 'template', 'order', 'created_at']
    list_filter = ['template']
    search_fields = ['name', 'template__name']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Question)
class QuestionAdmin(SimpleHistoryAdmin):
    list_display = ['order', 'section', 'possible_points',
                    'is_critical', 'truncated_text']
    list_filter = ['section__template', 'section', 'is_critical']
    search_fields = ['question_text']
    readonly_fields = ['created_at', 'updated_at']

    @admin.display(description='Question')
    def truncated_text(self, obj):
        return (obj.question_text[:72] + '...') if len(obj.question_text) > 75 else obj.question_text


@admin.register(Audit)
class AuditAdmin(SimpleHistoryAdmin):
    list_display = [
        'restaurant', 'audit_date', 'template', 'auditor',
        'grade', 'total_percentage', 'is_submitted', 'submitted_at'
    ]
    list_filter = ['grade', 'is_submitted', 'has_critical_failure', 'audit_date']
    search_fields = ['restaurant__name', 'restaurant__code',
                     'manager_on_duty', 'auditor__username']
    readonly_fields = [
        'total_percentage', 'grade', 'has_critical_failure',
        'total_scored', 'total_possible', 'created_at', 'updated_at'
    ]
    inlines = [AuditSectionInline, CorrectiveActionInline]
    fieldsets = [
        (
            'Restaurant & Template',
            {'fields': ['restaurant', 'template', 'audit_date']}
        ),
        (
            'Personnel',
            {'fields': ['manager_on_duty', 'auditor', 'auditor_signature']}
        ),
        (
            'Scoring',
            {'fields': [
                'total_scored', 'total_possible', 'total_percentage',
                'grade', 'has_critical_failure'
            ]}
        ),
        (
            'Submission',
            {'fields': ['is_submitted', 'submitted_at', 'previous_audit']}
        ),
        (
            'Timestamps',
            {'fields': ['created_at', 'updated_at'], 'classes': ['collapse']}
        ),
    ]


@admin.register(AuditQuestionResponse)
class AuditQuestionResponseAdmin(SimpleHistoryAdmin):
    list_display = ['audit_section', 'question', 'scored_points', 'is_na', 'needs_corrective_action']
    list_filter = ['is_na', 'needs_corrective_action', 'audit_section__audit']
    search_fields = ['question__question_text', 'audit_section__audit__restaurant__name']
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = [
        ('Response', {'fields': ['audit_section', 'question', 'scored_points']}),
        ('Flags', {'fields': ['is_na', 'needs_corrective_action']}),
        ('Evidence', {'fields': ['image']}),
        ('Notes', {'fields': ['comments']}),
        ('Timestamps', {'fields': ['created_at', 'updated_at'], 'classes': ['collapse']}),
    ]


@admin.register(CorrectiveAction)
class CorrectiveActionAdmin(SimpleHistoryAdmin):
    list_display = ['audit', 'risk_level', 'status', 'deadline',
                    'completion_date', 'is_overdue']
    list_filter = ['risk_level', 'status', 'deadline']
    search_fields = ['audit__restaurant__name', 'description']
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = [
        (
            'Details',
            {'fields': ['audit', 'restaurant', 'question_response']}
        ),
        (
            'Action',
            {'fields': ['description', 'risk_level', 'assigned_to']}
        ),
        (
            'Timeline',
            {'fields': ['deadline', 'status', 'completion_date', 'comments']}
        ),
        (
            'Evidence',
            {'fields': ['evidence_image']}
        ),
        (
            'Timestamps',
            {'fields': ['created_at', 'updated_at'], 'classes': ['collapse']}
        ),
    ]
