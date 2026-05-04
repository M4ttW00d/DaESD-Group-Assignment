from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models
from django.utils.translation import gettext_lazy as _

class ActiveUserManager(UserManager):
    """Manager that filters out soft-deleted users."""
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class User(AbstractUser):
    """
    Extends Django's AbstractUser to include role-based access control (RBAC).
    """
    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Admin"
        PRODUCER = "PRODUCER", "Producer"
        CUSTOMER = "CUSTOMER", "Customer"

    groups = models.ManyToManyField(
        "auth.Group",
        verbose_name=_("groups"),
        blank=True,
        help_text=_(
            "The groups this user belongs to. A user will get all permissions "
            "granted to each of their groups."
        ),
        related_name="user_set",
        related_query_name="user",
        db_table="users_groups",
    )
    user_permissions = models.ManyToManyField(
        "auth.Permission",
        verbose_name=_("user permissions"),
        blank=True,
        help_text=_("Specific permissions for this user."),
        related_name="user_set",
        related_query_name="user",
        db_table="users_permissions",
    )

    role = models.CharField(max_length=50, choices=Role.choices, default=Role.CUSTOMER)
    phone_number = models.CharField(max_length=20, blank=True, null=True, help_text="Required for producer/customer contact")
    is_deleted = models.BooleanField(default=False)

    objects = ActiveUserManager()
    all_objects = UserManager()

    class Meta:
        db_table = 'users'

    def delete(self, *args, **kwargs):
        """Soft delete the user and clear PII (GDPR compliance)."""
        self.is_deleted = True
        self.is_active = False
        self.email = ""
        self.first_name = ""
        self.last_name = ""
        self.phone_number = ""
        self.username = f"deleted_user_{self.id}"
        self.save()

        # Cascade soft-delete to profiles
        if hasattr(self, 'producer_profile') and self.producer_profile:
            self.producer_profile.delete()
        if hasattr(self, 'customer_profile') and self.customer_profile:
            self.customer_profile.delete()

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"

class ProducerProfile(models.Model):
    """
    Detailed profile information for users with the 'PRODUCER' role.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='producer_profile')
    business_name = models.CharField(max_length=255, blank=True, default='')
    business_address = models.TextField(blank=True, default='')
    postcode = models.CharField(max_length=20, blank=True, default='', help_text="Used for Food Miles calculation")
    bio = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'producer_profiles'

    def delete(self, *args, **kwargs):
        """Clear PII data from profile on user deletion."""
        self.business_name = "Deleted Business"
        self.business_address = ""
        self.postcode = ""
        self.bio = ""
        self.save()

    def __str__(self):
        return self.business_name

class CustomerProfile(models.Model):
    """
    Detailed profile information for users with the 'CUSTOMER' role.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='customer_profile')
    first_name = models.CharField(max_length=150, blank=True, default='')
    last_name = models.CharField(max_length=150, blank=True, default='')
    delivery_address = models.TextField(blank=True, default='')
    postcode = models.CharField(max_length=20, blank=True, default='', help_text="Used for Food Miles calculation")

    class Meta:
        db_table = 'customer_profiles'

    def delete(self, *args, **kwargs):
        """Clear PII data from profile on user deletion."""
        self.first_name = ""
        self.last_name = ""
        self.delivery_address = ""
        self.postcode = ""
        self.save()

    def __str__(self):
        return f"{self.first_name} {self.last_name}".strip() or self.user.username


class FavouriteProducer(models.Model):
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='favourite_producers',
    )
    producer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='favourited_by',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'favourite_producers'
        unique_together = ('customer', 'producer')

    def __str__(self):
        return f"{self.customer.username} → {self.producer.username}"
