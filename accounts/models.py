from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.urls import reverse
from django.utils.text import slugify

from simple_history.models import HistoricalRecords

from core.models import BaseModel
from core.utils import normalize_pakistani_phone_number
from restaurants.models import Restaurant


# -----------------------------
# Validator
# -----------------------------
mobile_validator = RegexValidator(
    regex=r'^(\+92|0)3\d{2}-?\d{7}$',
    message='Enter valid Pakistani mobile number (0300-1234567 / +92300-1234567)'
)


# -----------------------------
# Designation
# -----------------------------
class Designation(BaseModel):
    history = HistoricalRecords()
    name = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    description = models.TextField(blank=True)

    class Meta:
        db_table = "accounts_designation"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


# -----------------------------
# Department
# -----------------------------
class Department(BaseModel):
    history = HistoricalRecords()
    name = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    description = models.TextField(blank=True)

    class Meta:
        db_table = "accounts_department"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


# -----------------------------
# USER MODEL
# -----------------------------
class User(AbstractUser):
    history = HistoricalRecords()

    class Roles(models.TextChoices):
        ADMIN = "admin", "Admin"
        AUDITOR = "auditor", "Auditor"
        MANAGER = "manager", "Manager"
        RESTAURANT_USER = "restaurant_user", "Restaurant User"

    email = models.EmailField(unique=True)

    role = models.CharField(
        max_length=20,
        choices=Roles.choices,
        null=True,
        blank=True,
        db_index=True
    )

    designation = models.ForeignKey(
        Designation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users"
    )

    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users"
    )

    restaurants = models.ManyToManyField(
        Restaurant,
        blank=True,
        related_name="users"
    )

    manager = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="auditors"
    )

    assigned_by = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_users"
    )

    mobile_number = models.CharField(
        max_length=14,
        blank=True,
        null=True,
        validators=[mobile_validator]
    )

    class Meta:
        db_table = "accounts_user"
        ordering = ["username"]

    # -----------------------------
    # VALIDATION (FIELDS + RELATIONS)
    # -----------------------------
    def clean(self):
        super().clean()

        if self.is_superuser or self.role == self.Roles.ADMIN:
            return

        if not self.role:
            raise ValidationError({"role": "Role is required."})

        # safe role check
        role = self.role

        # -------------------------
        # MANAGER RULES
        # -------------------------
        if role == self.Roles.MANAGER:
            if self.manager:
                raise ValidationError(
                    {"manager": "Manager cannot have a manager."})

            if self.pk and self.restaurants.exists():
                raise ValidationError(
                    {"restaurants": "Manager cannot have restaurants."})

        # -------------------------
        # RESTAURANT USER RULES
        # -------------------------
        elif role == self.Roles.RESTAURANT_USER:
            if self.manager:
                raise ValidationError(
                    {"manager": "Restaurant user cannot have manager."})

        # -------------------------
        # AUDITOR RULES
        # -------------------------
        elif role == self.Roles.AUDITOR:
            if self.manager and self.manager.role != self.Roles.MANAGER:
                raise ValidationError(
                    {"manager": "Auditor must be assigned to a manager."})

            if self.manager is None:
                raise ValidationError(
                    {"manager": "Auditor must have a manager."})

    # -----------------------------
    # M2M VALIDATION (SAFE POST-SAVE)
    # -----------------------------
    def validate_restaurants(self):
        if not self.pk:
            return

        if not self.role or self.role == self.Roles.ADMIN:
            return

        count = self.restaurants.count()

        if self.role == self.Roles.RESTAURANT_USER:
            if count != 1:
                raise ValidationError(
                    "Restaurant user must have exactly one restaurant.")

        elif self.role == self.Roles.AUDITOR:
            if count < 1:
                raise ValidationError(
                    "Auditor must have at least one restaurant.")

        elif self.role == self.Roles.MANAGER:
            if count > 0:
                raise ValidationError("Manager cannot have restaurants.")

    # -----------------------------
    # SAVE
    # -----------------------------
    def save(self, *args, **kwargs):
        if self.mobile_number:
            self.mobile_number = normalize_pakistani_phone_number(self.mobile_number)
        super().save(*args, **kwargs)

    # -----------------------------
    # STRING / URL
    # -----------------------------
    def __str__(self):
        return self.get_full_name().strip() or self.username

    def get_absolute_url(self):
        return reverse("accounts:user_detail", kwargs={"pk": self.pk})

    # -----------------------------
    # HELPERS
    # -----------------------------
    @property
    def is_auditor(self):
        return self.role == self.Roles.AUDITOR

    @property
    def is_manager(self):
        return self.role == self.Roles.MANAGER

    @property
    def is_restaurant_user(self):
        return self.role == self.Roles.RESTAURANT_USER

    @property
    def is_admin(self):
        return self.is_superuser or self.role == self.Roles.ADMIN
