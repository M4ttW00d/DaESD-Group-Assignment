from django.db import models


class Notification(models.Model):
    class NotificationType(models.TextChoices):
        ORDER_PLACED       = 'ORDER_PLACED',       'Order Placed'
        ORDER_CONFIRMED    = 'ORDER_CONFIRMED',     'Order Confirmed'
        ORDER_READY        = 'ORDER_READY',         'Order Ready'
        ORDER_DELIVERED    = 'ORDER_DELIVERED',     'Order Delivered'
        ORDER_CANCELLED    = 'ORDER_CANCELLED',     'Order Cancelled'
        ORDER_UPDATE       = 'ORDER_UPDATE',        'Order Update'
        LOW_STOCK          = 'LOW_STOCK',           'Low Stock'
        OUT_OF_STOCK       = 'OUT_OF_STOCK',        'Out of Stock'
        SURPLUS_DEAL       = 'SURPLUS_DEAL',        'Surplus Deal'
        SEASONAL_REMINDER  = 'SEASONAL_REMINDER',   'Seasonal Reminder'
        PAYMENT_RECEIVED   = 'PAYMENT_RECEIVED',    'Payment Received'
        PAYMENT_FAILED     = 'PAYMENT_FAILED',      'Payment Failed'
        ORDER_SUMMARY      = 'ORDER_SUMMARY',       'Order Summary'
        SETTLEMENT_READY          = 'SETTLEMENT_READY',          'Settlement Ready'
        RECURRING_ORDER_REMINDER  = 'RECURRING_ORDER_REMINDER',  'Recurring Order Reminder'
        RECURRING_ORDER_PLACED    = 'RECURRING_ORDER_PLACED',    'Recurring Order Placed'
        RECURRING_ORDER_PAUSED    = 'RECURRING_ORDER_PAUSED',    'Recurring Order Paused'
        BULK_ORDER_PLACED         = 'BULK_ORDER_PLACED',         'Bulk Order Placed'
        GENERAL                   = 'GENERAL',                   'General'

    recipient_id      = models.IntegerField(db_index=True)
    notification_type = models.CharField(
        max_length=30,
        choices=NotificationType.choices,
        default=NotificationType.GENERAL,
    )
    title        = models.CharField(max_length=255, blank=True)
    message      = models.TextField()
    is_read      = models.BooleanField(default=False)
    show_in_app  = models.BooleanField(default=True)
    email_sent   = models.BooleanField(default=False)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notifications'
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.notification_type}] → user {self.recipient_id}"


class NotificationPreference(models.Model):
    user_id        = models.IntegerField(unique=True, db_index=True)
    email_enabled  = models.BooleanField(default=True)
    in_app_enabled = models.BooleanField(default=True)

    class Meta:
        db_table = 'notification_preferences'

    def __str__(self):
        return f"Prefs for user {self.user_id}"


class EmailLog(models.Model):
    class Status(models.TextChoices):
        SENT   = 'SENT',   'Sent'
        FAILED = 'FAILED', 'Failed'

    notification    = models.OneToOneField(Notification, on_delete=models.CASCADE, related_name='email_log', null=True, blank=True)
    recipient_email = models.EmailField()
    subject         = models.CharField(max_length=255)
    html_body       = models.TextField()
    status          = models.CharField(max_length=10, choices=Status.choices, default=Status.SENT)
    error_message   = models.TextField(blank=True)
    sent_at         = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'email_logs'
        ordering = ['-sent_at']

    def __str__(self):
        return f"[{self.status}] {self.subject} → {self.recipient_email}"


class NotificationTypePreference(models.Model):
    user_id           = models.IntegerField(db_index=True)
    notification_type = models.CharField(max_length=50)
    email_enabled     = models.BooleanField(default=True)
    in_app_enabled    = models.BooleanField(default=True)

    class Meta:
        db_table = 'notification_type_preferences'
        unique_together = ('user_id', 'notification_type')

    def __str__(self):
        return f"TypePref({self.user_id}, {self.notification_type})"