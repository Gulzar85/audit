from django.contrib.auth import views as auth_views
from django.urls import path, include

from . import views
from .forms import LoginForm, CustomPasswordResetForm, CustomSetPasswordForm, CustomPasswordChangeForm
from core.security import rate_limit

app_name = 'accounts'

# Apply rate limiting to login view (max 5 attempts per 5 minutes)
login_view = rate_limit('login', max_requests=5, window=300)(
    auth_views.LoginView.as_view(
        authentication_form=LoginForm,
        template_name='registration/login.html',
    )
)

# Apply rate limiting to password reset (max 3 attempts per 1 hour)
password_reset_view = rate_limit('password_reset', max_requests=3, window=3600)(
    auth_views.PasswordResetView.as_view(
        form_class=CustomPasswordResetForm,
        template_name='registration/password_reset_form.html',
    )
)

urlpatterns = [
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('', views.UserListView.as_view(), name='user_list'),
    path('<int:pk>/', views.UserDetailView.as_view(), name='user_detail'),
    path('login/', login_view, name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('password_change/', auth_views.PasswordChangeView.as_view(
        form_class=CustomPasswordChangeForm,
        template_name='registration/password_change_form.html',
    ), name='password_change'),
    path('password_change/done/', auth_views.PasswordChangeDoneView.as_view(
        template_name='registration/password_change_done.html',
    ), name='password_change_done'),
    path('password_reset/', password_reset_view, name='password_reset'),
    path('password_reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='registration/password_reset_done.html',
    ), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        form_class=CustomSetPasswordForm,
        template_name='registration/password_reset_confirm.html',
    ), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(
        template_name='registration/password_reset_complete.html',
    ), name='password_reset_complete'),
]
