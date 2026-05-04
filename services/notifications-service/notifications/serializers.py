from rest_framework import serializers
from .models import Notification, NotificationPreference, NotificationTypePreference


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ('id', 'recipient_id', 'notification_type', 'title', 'message', 'is_read', 'created_at')
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

    def create(self, validated_data):
        return Notification.objects.create(
            recipient_id=validated_data['user'],
            notification_type=validated_data.get('type', Notification.NotificationType.GENERAL),
            title=validated_data.get('title', ''),
            message=validated_data['message'],
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