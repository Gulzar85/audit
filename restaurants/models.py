from decimal import Decimal
from typing import Optional

from django.core.validators import RegexValidator, MinValueValidator, MaxValueValidator
from django.db import models
from django.urls import reverse
from simple_history.models import HistoricalRecords

from core.models import BaseModel
from core.utils import normalize_pakistani_phone_number


# -----------------------------
# Validators
# -----------------------------
code_validator = RegexValidator(
    regex=r'^\d{7}$',
    message='Restaurant code must be exactly 7 digits (e.g., 1270001).'
)

mobile_validator = RegexValidator(
    regex=r'^(\+92|0)3\d{2}-?\d{7}$',
    message='Enter valid Pakistani mobile number (0300-1234567 / +92300-1234567)'
)


# -----------------------------
# Region
# -----------------------------
class Region(BaseModel):
    history = HistoricalRecords()
    name = models.CharField(max_length=255, unique=True)

    class Meta:
        verbose_name = "Region"
        verbose_name_plural = "Regions"
        ordering = ['name']
        db_table = 'restaurants_region'

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse('restaurants:region_detail', kwargs={'pk': self.pk})


# -----------------------------
# Restaurant
# -----------------------------
class Restaurant(BaseModel):
    history = HistoricalRecords()

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        INACTIVE = 'inactive', 'Inactive'
        CLOSED = 'closed', 'Closed'
        RENOVATION = 'renovation', 'Under Renovation'

    # -------------------------
    # IDENTIFIERS
    # -------------------------
    code = models.CharField(
        max_length=7,
        unique=True,  # Inherently creates a database index
        validators=[code_validator],
        help_text="7-digit unique restaurant code"
    )

    name = models.CharField(max_length=255)

    # -------------------------
    # LOCATION
    # -------------------------
    region = models.ForeignKey(
        Region,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='restaurants'
    )

    city = models.CharField(max_length=100, db_index=True)
    address = models.TextField()

    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(-90),
            MaxValueValidator(90)
        ]
    )

    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(-180),
            MaxValueValidator(180)
        ]
    )

    # -------------------------
    # CONTACT
    # -------------------------
    phone = models.CharField(
        max_length=14,
        blank=True,
        null=True,
        validators=[mobile_validator]
    )
    manager_email = models.EmailField(blank=True, null=True)

    # -------------------------
    # STATUS
    # -------------------------
    status = models.CharField(
        max_length=20,
        choices=Status,  # Modern Django notation
        default=Status.ACTIVE,
        db_index=True
    )

    opening_date = models.DateField(null=True, blank=True)

    # -------------------------
    # META
    # -------------------------
    class Meta:
        verbose_name = "Restaurant"
        verbose_name_plural = "Restaurants"
        ordering = ['city', 'name']
        db_table = 'restaurants_restaurant'
        indexes = [
            models.Index(fields=['city', 'status']),
            # models.Index(fields=['code']) -> Removed: Redundant due to unique=True
        ]

# -------------------------
    # SAVE (Transformations)
    # -------------------------
    def save(self, *args, **kwargs):
        if self.code:
            self.code = self.code.strip()

        if self.phone:
            self.phone = normalize_pakistani_phone_number(self.phone)
        super().save(*args, **kwargs)

    # -------------------------
    # STRING
    # -------------------------
    def __str__(self) -> str:
        return f"{self.name} ({self.code})"

    # -------------------------
    # URL
    # -------------------------
    def get_absolute_url(self) -> str:
        return reverse(
            'restaurants:restaurant_detail',
            kwargs={'pk': self.pk}
        )

    @property
    def latest_audit(self) -> Optional['Audit']:
        """Return the most recent submitted audit for this restaurant"""
        from audits.models import Audit
        return Audit.objects.filter(restaurant=self, is_submitted=True).order_by('-audit_date').first()

    @property
    def submitted_audit_count(self) -> int:
        """Return count of submitted audits"""
        from audits.models import Audit
        return Audit.objects.filter(restaurant=self, is_submitted=True).count()

    @property
    def submitted_average_score(self) -> Optional[Decimal]:
        """Return average score of submitted audits"""
        from audits.models import Audit
        result = Audit.objects.filter(restaurant=self, is_submitted=True).aggregate(
            avg_score=models.Avg('total_percentage')
        )
        return result['avg_score']
