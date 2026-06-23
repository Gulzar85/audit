from django.contrib.auth import get_user_model
from django.db import models
from simple_history.models import HistoricalRecords


class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class BusinessInfo(models.Model):
    history = HistoricalRecords()
    company_name = models.CharField(
        max_length=255, default='McDonald\'s Pakistan')
    tagline = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    logo = models.ImageField(upload_to='logo/', blank=True)
    favicon = models.ImageField(upload_to='favicon/', blank=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)

    primary_color = models.CharField(max_length=7, default='#DA291C')
    secondary_color = models.CharField(max_length=7, default='#FFC72C')
    accent_color = models.CharField(max_length=7, default='#27251F')

    class Meta:
        verbose_name = "Business Info"
        verbose_name_plural = "Business Info"

    def __str__(self):
        return self.company_name

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class SocialMedia(models.Model):
    history = HistoricalRecords()
    PLATFORMS = [
        ('facebook', 'Facebook'),
        ('instagram', 'Instagram'),
        ('twitter', 'Twitter / X'),
        ('linkedin', 'LinkedIn'),
        ('youtube', 'YouTube'),
        ('tiktok', 'TikTok'),
        ('whatsapp', 'WhatsApp'),
    ]
    business = models.ForeignKey(
        BusinessInfo, on_delete=models.CASCADE, related_name='social_media'
    )
    platform = models.CharField(max_length=20, choices=PLATFORMS)
    url = models.URLField()
    icon_class = models.CharField(
        max_length=50, blank=True,
        help_text="CSS class for icon (e.g. 'fab fa-facebook')"
    )
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "Social Media Link"
        verbose_name_plural = "Social Media Links"
        ordering = ['order']

    def __str__(self):
        return f"{dict(self.PLATFORMS).get(self.platform, self.platform)}"


User = get_user_model()


class Notification(BaseModel):
    class Type(models.TextChoices):
        AUDIT_SUBMITTED = 'audit_submitted', 'Audit Submitted'
        CA_CREATED = 'ca_created', 'Corrective Action Created'
        CA_COMPLETED = 'ca_completed', 'Corrective Action Completed'

    recipient = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='notifications')
    notification_type = models.CharField(
        max_length=30, choices=Type.choices)
    title = models.CharField(max_length=255)
    message = models.TextField()
    link = models.CharField(max_length=500, blank=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"

    def __str__(self):
        return f"[{self.get_notification_type_display()}] {self.title}"
