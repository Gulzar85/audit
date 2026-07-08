from django.apps import AppConfig
from django.db.models.signals import m2m_changed


class AccountsConfig(AppConfig):
    name = 'accounts'

    def ready(self):
        User = self.get_model('User')
        # Import the full signals module so all @receiver decorators are registered:
        # - sync_role_to_group (post_save)
        # - log_failed_login (user_login_failed)
        # - validate_user_restaurants (m2m_changed, connected manually below)
        import accounts.signals  # noqa: F401
        from accounts.signals import validate_user_restaurants
        m2m_changed.connect(
            validate_user_restaurants, sender=User.restaurants.through
        )
