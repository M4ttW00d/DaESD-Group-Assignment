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
        SETTLEMENT_READY   = 'SETTLEMENT_READY',    'Settlement Ready'
        GENERAL            = 'GENERAL',             'General'

    recipient_id      = models.IntegerField(db_index=True)
    notification_type = models.CharField(
        max_length=30,
        choices=NotificationType.choices,
        default=NotificationType.GENERAL,
    )
    title      = models.CharField(max_length=255, blank=True)
    message    = models.TextField()
    is_read    = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notifications'
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.notification_type}] → user {self.recipient_id}"