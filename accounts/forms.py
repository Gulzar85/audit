from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm, PasswordResetForm, SetPasswordForm, PasswordChangeForm
)
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Field, HTML, Div


class LoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.attrs = {'novalidate': ''}
        self.helper.layout = Layout(
            Div(
                HTML('<i data-lucide="user" class="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 group-focus-within:text-primary transition-colors"></i>'),
                Field('username', placeholder='Enter your username',
                      css_class='w-full pl-10 pr-4 py-3 rounded-xl border border-gray-300 focus:border-primary focus:ring-2 focus:ring-primary outline-none transition-all text-sm bg-white/50'),
                css_class='relative group'
            ),
            Div(
                HTML('<i data-lucide="lock" class="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 group-focus-within:text-primary transition-colors"></i>'),
                Field('password', placeholder='Enter your password',
                      css_class='w-full pl-10 pr-4 py-3 rounded-xl border border-gray-300 focus:border-primary focus:ring-2 focus:ring-primary outline-none transition-all text-sm bg-white/50'),
                css_class='relative group'
            ),
        )


class CustomPasswordResetForm(PasswordResetForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.attrs = {'novalidate': ''}
        self.helper.layout = Layout(
            Div(
                HTML('<i data-lucide="mail" class="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 group-focus-within:text-primary transition-colors"></i>'),
                Field('email', placeholder='Enter your email address',
                      css_class='w-full pl-10 pr-4 py-3 rounded-xl border border-gray-300 focus:border-primary focus:ring-2 focus:ring-primary outline-none transition-all text-sm bg-white/50'),
                css_class='relative group'
            ),
        )


class CustomSetPasswordForm(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.attrs = {'novalidate': ''}
        self.helper.layout = Layout(
            Div(
                HTML('<i data-lucide="key" class="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 group-focus-within:text-primary transition-colors"></i>'),
                Field('new_password1', placeholder='Enter new password',
                      css_class='w-full pl-10 pr-4 py-3 rounded-xl border border-gray-300 focus:border-primary focus:ring-2 focus:ring-primary outline-none transition-all text-sm bg-white/50'),
                css_class='relative group mb-4'
            ),
            Div(
                HTML('<i data-lucide="key" class="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 group-focus-within:text-primary transition-colors"></i>'),
                Field('new_password2', placeholder='Confirm new password',
                      css_class='w-full pl-10 pr-4 py-3 rounded-xl border border-gray-300 focus:border-primary focus:ring-2 focus:ring-primary outline-none transition-all text-sm bg-white/50'),
                css_class='relative group'
            ),
        )


class CustomPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.attrs = {'novalidate': ''}
        self.helper.layout = Layout(
            Div(
                HTML('<i data-lucide="lock" class="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 group-focus-within:text-primary transition-colors"></i>'),
                Field('old_password', placeholder='Enter current password',
                      css_class='w-full pl-10 pr-4 py-3 rounded-xl border border-gray-300 focus:border-primary focus:ring-2 focus:ring-primary outline-none transition-all text-sm bg-white/50'),
                css_class='relative group mb-4'
            ),
            Div(
                HTML('<i data-lucide="key" class="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 group-focus-within:text-primary transition-colors"></i>'),
                Field('new_password1', placeholder='Enter new password',
                      css_class='w-full pl-10 pr-4 py-3 rounded-xl border border-gray-300 focus:border-primary focus:ring-2 focus:ring-primary outline-none transition-all text-sm bg-white/50'),
                css_class='relative group mb-4'
            ),
            Div(
                HTML('<i data-lucide="key" class="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 group-focus-within:text-primary transition-colors"></i>'),
                Field('new_password2', placeholder='Confirm new password',
                      css_class='w-full pl-10 pr-4 py-3 rounded-xl border border-gray-300 focus:border-primary focus:ring-2 focus:ring-primary outline-none transition-all text-sm bg-white/50'),
                css_class='relative group'
            ),
        )
