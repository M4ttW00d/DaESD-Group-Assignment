from rest_framework import serializers
from .models import Notification, NotificationPreference, NotificationTypePreference, EmailLog


class EmailLogSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model  = EmailLog
        fields = ('recipient_email', 'subject', 'html_body', 'status', 'error_message', 'sent_at')


class NotificationSerializer(serializers.ModelSerializer):
    email_log = EmailLogSummarySerializer(read_only=True)

    class Meta:
        model = Notification
        fields = ('id', 'recipient_id', 'notification_type', 'title', 'message', 'is_read', 'show_in_app', 'email_sent', 'email_log', 'created_at')
        read_only_fields = ('id', 'created_at')


class CreateNotificationSerializer(serializers.Serializer):
    user    = serializers.IntegerField()
    message = serializers.CharField()
    type    = serializers.ChoiceField(
        choices=Notification.NotificationType.choices,
        default=Notification.NotificationType.GENERAL,
    )
    title   = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    email   = serializers.EmailField(required=False, allow_blank=True, default='')

    def create(self, validated_data, show_in_app=True):
        return Notification.objects.create(
            recipient_id=validated_data['user'],
            notification_type=validated_data.get('type', Notification.NotificationType.GENERAL),
            title=validated_data.get('title', ''),
            message=validated_data['message'],
            show_in_app=show_in_app,
        )


class UnreadCountSerializer(serializers.Serializer):
    recipient_id = serializers.IntegerField()
    unread_count = serializers.IntegerField()


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model  = NotificationPreference
        fields = ('user_id', 'email_enabled', 'in_app_enabled')


class NotificationTypePreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model  = NotificationTypePreference
        fields = ('user_id', 'notification_type', 'email_enabled', 'in_app_enabled')


class EmailLogSerializer(serializers.ModelSerializer):
    notification_id = serializers.IntegerField(source='notification.id', read_only=True, allow_null=True)

    class Meta:
        model  = EmailLog
        fields = ('id', 'notification_id', 'recipient_email', 'subject', 'html_body', 'status', 'error_message', 'sent_at')