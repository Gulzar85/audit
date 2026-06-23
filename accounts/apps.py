from django.apps import AppConfig
from django.db.models.signals import m2m_changed


class AccountsConfig(AppConfig):
    name = 'accounts'

    def ready(self):
        User = self.get_model('User')
        from accounts.signals import validate_user_restaurants
        m2m_changed.connect(
            validate_user_restaurants, sender=User.restaurants.through
        )
