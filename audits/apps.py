from django.apps import AppConfig


class AuditsConfig(AppConfig):
    name = 'audits'

    def ready(self):
        import audits.signals  # noqa
