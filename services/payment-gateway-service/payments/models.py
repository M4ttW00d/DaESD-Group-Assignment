from django.db import models


class Payment(models.Model):
    PAYMENT_STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
        ('CANCELLED', 'Cancelled'),
    ]

    order_id = models.CharField(max_length=64, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='gbp')
    status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default='PENDING',
    )
    stripe_session_id = models.CharField(max_length=255, blank=True, null=True, unique=True)
    stripe_payment_intent = models.CharField(max_length=255, blank=True, null=True)
    request_payload = models.JSONField(default=dict, blank=True)
    settled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'payments'
        ordering = ['-created_at']

    def __str__(self):
        reference = self.order_id or self.stripe_session_id or self.pk
        return f"Payment {reference} - {self.amount} {self.currency} ({self.status})"


class WeeklySettlement(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
    ]
    week_start = models.DateField()
    week_end = models.DateField()
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'weekly_settlements'
        ordering = ['-created_at']

    def __str__(self):
        return f"Settlement {self.week_start} → {self.week_end} ({self.status})"


class ProducerSettlement(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('TRANSFERRED', 'Transferred'),
        ('SKIPPED', 'Skipped'),
        ('FAILED', 'Failed'),
    ]
    settlement = models.ForeignKey(
        WeeklySettlement,
        on_delete=models.CASCADE,
        related_name='producer_settlements',
    )
    producer_id = models.CharField(max_length=64, blank=True, default='')
    producer_name = models.CharField(max_length=255, blank=True, default='')
    stripe_account_id = models.CharField(max_length=255, blank=True, default='')
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    transfer_id = models.CharField(max_length=255, blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    error_message = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'producer_settlements'

    def __str__(self):
        return f"{self.producer_name} - £{self.amount} ({self.status})"
