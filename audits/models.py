import logging
import os
from decimal import Decimal

from django.core.validators import MinValueValidator, MaxValueValidator, FileExtensionValidator
from django.db import models
from django.db.models import Q, UniqueConstraint, CheckConstraint
from django.db.models.functions import NullIf
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model
from simple_history.models import HistoricalRecords

from core.models import BaseModel
from restaurants.models import Restaurant

User = get_user_model()
logger = logging.getLogger(__name__)

ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
ALLOWED_IMAGE_MIMETYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/bmp'}
MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5 MB


def validate_uploaded_image(file):
    import struct
    from PIL import Image
    from io import BytesIO
    from django.core.exceptions import ValidationError

    if file.size > MAX_UPLOAD_SIZE:
        raise ValidationError(
            f'File size must be under 5 MB. Current size: {file.size / 1024 / 1024:.1f} MB'
        )

    ext = os.path.splitext(str(file.name))[1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValidationError(
            f'Unsupported file extension "{ext}". Allowed: {", ".join(sorted(ALLOWED_IMAGE_EXTENSIONS))}'
        )

    # Validate actual image content using PIL
    try:
        file.seek(0)
        img = Image.open(BytesIO(file.read()))
        img.verify()
        file.seek(0)
    except Exception:
        raise ValidationError('The file is not a valid image.')

    # Validate MIME type
    if hasattr(file, 'content_type') and file.content_type:
        if file.content_type not in ALLOWED_IMAGE_MIMETYPES:
            raise ValidationError(f'Invalid image type: {file.content_type}')

# -----------------------------
# Audit Template Engine
# -----------------------------


class AuditTemplate(BaseModel):
    history = HistoricalRecords()
    name = models.CharField(max_length=255, unique=True,
                            verbose_name=_("Audit Template Name"))
    description = models.TextField(blank=True, verbose_name=_("Description"))
    version = models.CharField(
        max_length=50, blank=True, default="1.0", verbose_name=_("Version"))
    is_active = models.BooleanField(default=True, verbose_name=_("Is Active"))

    class Meta:
        verbose_name = _("Audit Template")
        verbose_name_plural = _("Audit Templates")
        ordering = ["-created_at", "-pk"]
        db_table = "audits_audittemplate"
        indexes = [models.Index(fields=["version"])]

    def __str__(self) -> str:
        return f"{self.name} (v{self.version})"

    def get_absolute_url(self):
        return reverse('audits:template_detail', kwargs={'pk': self.pk})


class Section(BaseModel):
    history = HistoricalRecords()
    template = models.ForeignKey(
        AuditTemplate, on_delete=models.CASCADE, related_name="sections")
    name = models.CharField(max_length=255, verbose_name=_("Section Name"))
    description = models.TextField(
        blank=True, verbose_name=_("Section Description"))
    order = models.PositiveIntegerField(verbose_name=_(
        "Section Order"), validators=[MinValueValidator(1)])

    class Meta:
        verbose_name = _("Section")
        verbose_name_plural = _("Sections")
        ordering = ["order"]
        db_table = "audits_section"
        constraints = [UniqueConstraint(
            fields=["template", "order"], name="unique_template_section_order")]
        indexes = [models.Index(fields=["template", "order"])]

    def __str__(self) -> str:
        return f"{self.name} (Template: {self.template.name})"


class Question(BaseModel):
    history = HistoricalRecords()
    section = models.ForeignKey(
        Section, on_delete=models.CASCADE, related_name="questions")
    question_text = models.TextField(verbose_name=_("Question Text"))
    possible_points = models.PositiveIntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(100)])
    is_critical = models.BooleanField(default=False)
    critical_failure_condition = models.CharField(max_length=255, blank=True)
    order = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    class Meta:
        verbose_name = _("Question")
        verbose_name_plural = _("Questions")
        ordering = ["order"]
        db_table = "audits_question"
        constraints = [
            UniqueConstraint(fields=["section", "order"],
                             name="unique_section_question_order"),
        ]
        indexes = [models.Index(fields=["section", "order"])]

    def __str__(self) -> str:
        truncated_q = (self.question_text[:47] + '...') if len(
            self.question_text) > 50 else self.question_text
        return f"Q{self.order}: {truncated_q}"


# -----------------------------
# Audit Execution
# -----------------------------
class AuditQuerySet(models.QuerySet):
    def visible_to(self, user):
        if user.is_superuser:
            return self.filter(is_archived=False)
        return self.filter(
            Q(auditor=user) |
            Q(restaurant__in=user.restaurants.all()) |
            Q(auditor__manager=user),
            is_archived=False,
        )


class Audit(BaseModel):
    objects = AuditQuerySet.as_manager()
    history = HistoricalRecords()

    class Grade(models.TextChoices):
        A = 'A', _('A (96.0 - 100)')
        B = 'B', _('B (90.0 - 95.9)')
        C = 'C', _('C (80.0 - 89.9)')
        F = 'F', _('F (Less than 80)')

    template = models.ForeignKey(
        AuditTemplate, on_delete=models.CASCADE, related_name="audits")
    restaurant = models.ForeignKey(
        Restaurant, on_delete=models.CASCADE, related_name="audits")
    audit_date = models.DateField()
    manager_on_duty = models.CharField(max_length=255)
    auditor = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="audits")
    auditor_signature = models.CharField(max_length=255, blank=True)
    auditee_signature = models.CharField(max_length=255, blank=True)

    total_scored = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total_possible = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'))

    total_percentage = models.GeneratedField(
        expression=models.ExpressionWrapper(
            models.F('total_scored') * 100.0 /
            NullIf(models.F('total_possible'), 0),
            output_field=models.FloatField()
        ),
        output_field=models.FloatField(),
        db_persist=True,
        verbose_name=_("Total Percentage")
    )

    grade = models.CharField(max_length=1, choices=Grade, blank=True)
    has_critical_failure = models.BooleanField(default=False)

    previous_audit = models.OneToOneField(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="next_audit")

    is_submitted = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(null=True, blank=True)
    is_archived = models.BooleanField(default=False, db_index=True,
        help_text=_("Soft-delete: mark as archived instead of deleting"))

    class Meta:
        verbose_name = _("Audit")
        verbose_name_plural = _("Audits")
        ordering = ["-audit_date"]
        db_table = "audits_audit"
        indexes = [
            models.Index(fields=["audit_date"]),
            models.Index(fields=["restaurant", "audit_date"]),
        ]
        constraints = [UniqueConstraint(
            fields=["template", "restaurant", "audit_date"],
            condition=Q(is_archived=False),
            name="unique_template_restaurant_auditdate_active")]

    def __str__(self) -> str:
        return f"{self.restaurant.name} - {self.audit_date}"

    def save(self, *args, **kwargs):
        if self.is_submitted and not self.submitted_at:
            self.submitted_at = timezone.now()
        super().save(*args, **kwargs)

    def calculate_totals(self) -> bool:
        try:
            sections = self.audit_sections.all()  # type: ignore
            total_scored = sum(
                (section.scored_points for section in sections), Decimal('0.00'))
            total_possible = sum(
                (section.possible_points for section in sections), Decimal('0.00'))

            self.total_scored = total_scored
            self.total_possible = total_possible
            self.has_critical_failure = any(
                section.has_critical_failure for section in sections)

            percentage = float(total_scored * 100 /
                               total_possible) if total_possible else 0
            self.grade = 'F' if self.has_critical_failure else self.calculate_normal_grade(
                percentage)

            self.save(update_fields=[
                      'total_scored', 'total_possible', 'grade', 'has_critical_failure', 'updated_at'])
            return True
        except Exception:
            logger.exception(
                "Error calculating audit totals for Audit id=%s", self.pk)
            return False

    def calculate_normal_grade(self, percentage: float) -> str:
        if percentage >= 96:
            return 'A'
        if percentage >= 90:
            return 'B'
        if percentage >= 80:
            return 'C'
        return 'F'


class AuditSection(BaseModel):
    history = HistoricalRecords()
    audit = models.ForeignKey(
        Audit, on_delete=models.CASCADE, related_name="audit_sections")
    section = models.ForeignKey(
        Section, on_delete=models.CASCADE, related_name="audit_entries")
    scored_points = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal('0.00'))
    possible_points = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal('0.00'))
    section_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0.00'))
    has_critical_failure = models.BooleanField(default=False)

    class Meta:
        verbose_name = _("Audit Section")
        verbose_name_plural = _("Audit Sections")
        constraints = [UniqueConstraint(
            fields=['audit', 'section'], name='unique_audit_section')]

    def __str__(self) -> str:
        return f"{self.audit} - {self.section.name}"

    def calculate_section_score(self) -> None:
        try:
            responses = [r for r in self.responses.select_related(  # type: ignore
                'question').all() if r.is_answered]

            total_possible = sum(
                (Decimal(r.question.possible_points or 0)
                 for r in responses if not r.is_na),
                Decimal('0.00')
            )
            total_scored = sum(
                (Decimal(r.scored_points or 0)
                 for r in responses if not r.is_na and r.scored_points is not None),
                Decimal('0.00')
            )

            self.possible_points = total_possible
            self.scored_points = total_scored
            self.has_critical_failure = any(
                r.question.is_critical and Decimal(
                    r.scored_points or 0) == Decimal('0.00')
                for r in responses if not r.is_na
            )

            if total_possible > Decimal('0.00'):
                percentage = (total_scored / total_possible) * Decimal('100')
                self.section_percentage = percentage.quantize(Decimal('0.01'))
            else:
                self.section_percentage = Decimal('0.00')

            self.save(update_fields=[
                      'possible_points', 'scored_points', 'section_percentage', 'has_critical_failure'])
        except Exception:
            logger.exception(
                "Error calculating section score for AuditSection id=%s", self.pk)


class AuditQuestionResponse(BaseModel):
    history = HistoricalRecords()
    audit_section = models.ForeignKey(
        AuditSection, on_delete=models.CASCADE, related_name="responses")
    question = models.ForeignKey(
        Question, on_delete=models.CASCADE, related_name="question_responses")
    scored_points = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal(
        '0.00'), validators=[MinValueValidator(0)])
    comments = models.TextField(blank=True)
    needs_corrective_action = models.BooleanField(default=False)
    is_answered = models.BooleanField(
        default=False,
        verbose_name=_("Answered"),
        help_text=_(
            "Whether this question has been answered/scored")
    )
    is_na = models.BooleanField(
        default=False,
        verbose_name=_("Not Applicable"),
        help_text=_(
            "Mark this question as Not Applicable (excluded from scoring)")
    )
    image = models.ImageField(
        upload_to='audit_evidence/%Y/%m/',
        blank=True, null=True,
        verbose_name=_("Evidence Photo"),
        help_text=_("Upload a photo as evidence for this response"),
        validators=[validate_uploaded_image]
    )

    class Meta:
        verbose_name = _("Question Response")
        verbose_name_plural = _("Question Responses")
        constraints = [UniqueConstraint(
            fields=['audit_section', 'question'], name='unique_audit_section_question')]

    def __str__(self) -> str:
        return f"{self.audit_section} - {self.question.question_text[:30]}"


class CorrectiveActionQuerySet(models.QuerySet):
    def visible_to(self, user):
        if user.is_superuser:
            return self
        return self.filter(
            Q(restaurant__in=user.restaurants.all()) |
            Q(audit__auditor__manager=user)
        )


class CorrectiveAction(BaseModel):
    objects = CorrectiveActionQuerySet.as_manager()
    history = HistoricalRecords()

    class RiskLevel(models.TextChoices):
        LOW = 'LOW', _('Low')
        MEDIUM = 'MEDIUM', _('Medium')
        HIGH = 'HIGH', _('High')
        CRITICAL = 'CRITICAL', _('Critical')

    class Status(models.TextChoices):
        OPEN = 'OPEN', _('Open')
        IN_PROGRESS = 'IN_PROGRESS', _('In Progress')
        COMPLETED = 'COMPLETED', _('Completed')
        VERIFIED = 'VERIFIED', _('Verified')
        CLOSED = 'CLOSED', _('Closed')

    audit = models.ForeignKey(
        Audit, on_delete=models.CASCADE, related_name="corrective_actions")
    restaurant = models.ForeignKey(
        Restaurant, on_delete=models.CASCADE, related_name="corrective_actions", db_index=True)
    question_response = models.ForeignKey(
        AuditQuestionResponse, on_delete=models.CASCADE, null=True, blank=True, related_name="corrective_actions")
    description = models.TextField()
    risk_level = models.CharField(max_length=10, choices=RiskLevel)
    assigned_to = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_cas')
    status = models.CharField(max_length=20, choices=Status, default=Status.OPEN)
    deadline = models.DateField()
    completion_date = models.DateField(null=True, blank=True)
    comments = models.TextField(blank=True)
    evidence_image = models.ImageField(
        upload_to='corrective_action_evidence/%Y/%m/',
        blank=True, null=True,
        verbose_name=_("Evidence Photo"),
        help_text=_("Upload proof of completion"),
        validators=[validate_uploaded_image]
    )

    class Meta:
        verbose_name = _("Corrective Action")
        verbose_name_plural = _("Corrective Actions")
        ordering = ['-created_at']
        indexes = [models.Index(fields=['restaurant', 'status'])]

    def __str__(self) -> str:
        return f"{self.audit} - {self.risk_level}"

    @property
    def completed(self) -> bool:
        return self.status in (self.Status.COMPLETED, self.Status.VERIFIED, self.Status.CLOSED)

    @property
    def is_overdue(self) -> bool:
        if self.completed:
            return False
        return self.deadline < timezone.now().date()

    @property
    def days_remaining(self):
        if self.completed:
            return None
        return (self.deadline - timezone.now().date()).days

    def save(self, *args, **kwargs):
        if not self.restaurant and self.audit:
            self.restaurant = self.audit.restaurant

        if self.completed and not self.completion_date:
            self.completion_date = timezone.now().date()
        elif not self.completed and self.completion_date:
            self.completion_date = None

        super().save(*args, **kwargs)
