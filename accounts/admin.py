from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from import_export.admin import ImportExportModelAdmin
from import_export import resources
from simple_history.admin import SimpleHistoryAdmin

from .models import Department, Designation, User


class UserResource(resources.ModelResource):
    class Meta:
        model = User
        fields = [
            'id', 'email', 'username', 'first_name', 'last_name',
            'role', 'designation', 'department', 'mobile_number',
            'email_notifications', 'is_active', 'is_staff', 'is_superuser'
        ]
        import_id_fields = ['email']
        skip_unchanged = True


class DesignationResource(resources.ModelResource):
    class Meta:
        model = Designation
        fields = ['id', 'name', 'slug', 'description', 'created_at', 'updated_at']
        import_id_fields = ['id']
        skip_unchanged = True


class DepartmentResource(resources.ModelResource):
    class Meta:
        model = Department
        fields = ['id', 'name', 'slug', 'description', 'created_at', 'updated_at']
        import_id_fields = ['id']
        skip_unchanged = True


@admin.register(Designation)
class DesignationAdmin(ImportExportModelAdmin, SimpleHistoryAdmin):
    resource_classes = [DesignationResource]
    list_display = ['name', 'slug', 'created_at']
    search_fields = ['name']
    prepopulated_fields = {'slug': ['name']}
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Department)
class DepartmentAdmin(ImportExportModelAdmin, SimpleHistoryAdmin):
    resource_classes = [DepartmentResource]
    list_display = ['name', 'slug', 'created_at']
    search_fields = ['name']
    prepopulated_fields = {'slug': ['name']}
    readonly_fields = ['created_at', 'updated_at']


@admin.register(User)
class UserAdmin(ImportExportModelAdmin, SimpleHistoryAdmin, BaseUserAdmin):
    resource_classes = [UserResource]
    list_display = [
        'email', 'username', 'get_full_name', 'role',
        'designation', 'department', 'email_notifications', 'is_active', 'is_admin'
    ]
    list_filter = ['role', 'is_active', 'is_staff', 'is_superuser', 'department', 'designation', 'email_notifications']
    list_display_links = ['email']
    search_fields = ['email', 'username', 'first_name', 'last_name', 'mobile_number']
    ordering = ['email']
    filter_horizontal = ['groups', 'user_permissions', 'restaurants']
    actions = ['enable_email_notifications', 'disable_email_notifications']

    readonly_fields = ['last_login', 'date_joined']

    fieldsets = [
        (
            'Login Credentials',
            {'fields': ['email', 'password']}
        ),
        (
            'Personal Info',
            {'fields': [('first_name', 'last_name'), 'username', 'mobile_number']}
        ),
        (
            'Role & Organization',
            {'fields': ['role', 'designation', 'department', 'manager', 'assigned_by']}
        ),
        (
            'Notifications',
            {'fields': ['email_notifications']}
        ),
        (
            'Restaurants',
            {'fields': ['restaurants']}
        ),
        (
            'Permissions',
            {
                'fields': [
                    'is_active', 'is_staff', 'is_superuser',
                    'groups', 'user_permissions'
                ],
                'classes': ['collapse']
            }
        ),
        (
            'Important Dates',
            {'fields': ['last_login', 'date_joined'], 'classes': ['collapse']}
        ),
    ]

    add_fieldsets = [
        (
            None,
            {
                'classes': ['wide'],
                'fields': [
                    'email', 'username', 'password1', 'password2',
                    'role', 'designation', 'department', 'manager',
                ],
            },
        ),
    ]

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        form.user = request.user
        return form

    @admin.action(description='Enable email notifications for selected users')
    def enable_email_notifications(self, request, queryset):
        updated = queryset.update(email_notifications=True)
        self.message_user(request, f'{updated} user(s) — email notifications enabled.')

    @admin.action(description='Disable email notifications for selected users')
    def disable_email_notifications(self, request, queryset):
        updated = queryset.update(email_notifications=False)
        self.message_user(request, f'{updated} user(s) — email notifications disabled.')
