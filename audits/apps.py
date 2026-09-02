from django.apps import AppConfig


class AuditsConfig(AppConfig):
    name = 'audits'

    def ready(self):
        import audits.signals  # noqa
        # Tolerate floating-point rounding in PDF table cell widths so
        # reportlab doesn't raise "negative availWidth" on tightly-packed
        # nested tables (xhtml2pdf generates these from the HTML template).
        # reportlab is a required runtime dependency of xhtml2pdf; this only
        # tunes its internal config and does not use reportlab directly.
        from reportlab import rl_config
        rl_config.allowTableBoundsErrors = 3
