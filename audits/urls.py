from django.urls import path

from . import views

app_name = 'audits'

urlpatterns = [
    path('', views.AuditListView.as_view(), name='list'),
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),
    path('export/', views.DashboardExportView.as_view(), name='export'),
    path('create/', views.AuditCreateView.as_view(), name='create'),
    path('templates/', views.AuditTemplateListView.as_view(), name='template_list'),
    path('templates/<int:pk>/', views.AuditTemplateDetailView.as_view(), name='template_detail'),
    path('<int:pk>/', views.AuditDetailView.as_view(), name='detail'),
    path('<int:pk>/score/', views.AuditScoreView.as_view(), name='score'),
    path('<int:pk>/result/', views.AuditResultView.as_view(), name='result'),
    path('<int:pk>/result/pdf/', views.AuditReportPdfView.as_view(), name='result_pdf'),
    path('<int:pk>/submit/', views.AuditSubmitView.as_view(), name='submit'),
    path('<int:pk>/submit-json/', views.AuditSubmitJSONView.as_view(), name='submit_json'),
    path('<int:pk>/delete/', views.AuditDeleteView.as_view(), name='delete'),
    path('save-response/', views.SaveResponseView.as_view(), name='save_response'),
    path('fill-remaining/', views.FillRemainingView.as_view(), name='fill_remaining'),
    path('corrective-actions/', views.CorrectiveActionListView.as_view(), name='corrective_actions'),
    path('corrective-actions/create/', views.CorrectiveActionCreateView.as_view(), name='corrective_action_create'),
    path('corrective-actions/<int:pk>/', views.CorrectiveActionUpdateView.as_view(), name='corrective_action_edit'),
    path('corrective-actions/<int:pk>/complete/', views.CorrectiveActionCompleteView.as_view(), name='corrective_action_complete'),
    path('corrective-actions/<int:pk>/delete/', views.CorrectiveActionDeleteView.as_view(), name='corrective_action_delete'),
    path('ajax/audit-responses/<int:audit_pk>/', views.AuditQuestionResponsesJSONView.as_view(), name='audit_responses_json'),
]
