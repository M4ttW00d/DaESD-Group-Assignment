from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
from .models import Notification, NotificationPreference, NotificationTypePreference
from .serializers import (
    NotificationSerializer, CreateNotificationSerializer,
    UnreadCountSerializer, NotificationPreferenceSerializer,
    NotificationTypePreferenceSerializer,
)
from .email import send_notification_email


def verify_service_secret(request):
    secret = request.headers.get('X-Service-Secret', '')
    return secret == settings.SERVICE_SECRET_KEY


def _resolve_channel_prefs(user_id, notification_type):
    """
    Returns (email_enabled, in_app_enabled) for a user + notification type.
    Type-specific preference takes precedence over global preference.
    Defaults to (True, True) if no preference record exists.
    """
    type_pref = NotificationTypePreference.objects.filter(
        user_id=user_id, notification_type=notification_type
    ).first()
    if type_pref:
        return type_pref.email_enabled, type_pref.in_app_enabled

    global_pref = NotificationPreference.objects.filter(user_id=user_id).first()
    if global_pref:
        return global_pref.email_enabled, global_pref.in_app_enabled

    return True, True


class NotificationCreateView(APIView):
    def post(self, request):
        if not verify_service_secret(request):
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        serializer = CreateNotificationSerializer(data=request.data)
        if serializer.is_valid():
            data              = serializer.validated_data
            user_id           = data['user']
            recipient_email   = data.get('email', '')
            notification_type = data.get('type', Notification.NotificationType.GENERAL)

            email_enabled, in_app_enabled = _resolve_channel_prefs(user_id, notification_type)

            notification = None
            if in_app_enabled:
                notification = serializer.save()

            if email_enabled and recipient_email:
                try:
                    send_notification_email(
                        recipient_email=recipient_email,
                        title=data.get('title', ''),
                        message=data['message'],
                        notification_type=notification_type,
                    )
                except Exception:
                    pass

            if notification:
                return Response(NotificationSerializer(notification).data, status=status.HTTP_201_CREATED)
            return Response({'detail': 'Notification processed.'}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class NotificationPreferenceView(APIView):
    def get(self, request):
        user_id = request.query_params.get('user_id')
        if not user_id:
            return Response({'error': 'user_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        pref, _ = NotificationPreference.objects.get_or_create(user_id=user_id)
        return Response(NotificationPreferenceSerializer(pref).data)

    def post(self, request):
        user_id = request.data.get('user_id')
        if not user_id:
            return Response({'error': 'user_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        pref, _ = NotificationPreference.objects.get_or_create(user_id=user_id)
        serializer = NotificationPreferenceSerializer(pref, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class NotificationTypePreferenceView(APIView):
    def get(self, request):
        user_id = request.query_params.get('user_id')
        if not user_id:
            return Response({'error': 'user_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        prefs = NotificationTypePreference.objects.filter(user_id=user_id)
        return Response(NotificationTypePreferenceSerializer(prefs, many=True).data)

    def post(self, request):
        user_id           = request.data.get('user_id')
        notification_type = request.data.get('notification_type')
        if not user_id or not notification_type:
            return Response(
                {'error': 'user_id and notification_type are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        pref, _ = NotificationTypePreference.objects.get_or_create(
            user_id=user_id,
            notification_type=notification_type,
        )
        serializer = NotificationTypePreferenceSerializer(pref, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class NotificationListView(APIView):
    def get(self, request):
        recipient_id = request.query_params.get('recipient_id')
        if not recipient_id:
            return Response({'error': 'recipient_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        queryset = Notification.objects.filter(recipient_id=recipient_id)
        if request.query_params.get('unread') == 'true':
            queryset = queryset.filter(is_read=False)
        notification_type = request.query_params.get('type')
        if notification_type:
            queryset = queryset.filter(notification_type=notification_type)
        return Response(NotificationSerializer(queryset, many=True).data)


class NotificationDetailView(APIView):
    def _get_notification(self, pk, recipient_id):
        try:
            return Notification.objects.get(pk=pk, recipient_id=recipient_id)
        except Notification.DoesNotExist:
            return None

    def get(self, request, pk):
        recipient_id = request.query_params.get('recipient_id')
        if not recipient_id:
            return Response({'error': 'recipient_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        notification = self._get_notification(pk, recipient_id)
        if not notification:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        return Response(NotificationSerializer(notification).data)

    def patch(self, request, pk):
        recipient_id = request.data.get('recipient_id') or request.query_params.get('recipient_id')
        if not recipient_id:
            return Response({'error': 'recipient_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        notification = self._get_notification(pk, recipient_id)
        if not notification:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        notification.is_read = True
        notification.save()
        return Response(NotificationSerializer(notification).data)

    def delete(self, request, pk):
        recipient_id = request.query_params.get('recipient_id')
        if not recipient_id:
            return Response({'error': 'recipient_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        notification = self._get_notification(pk, recipient_id)
        if not notification:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        notification.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MarkAllReadView(APIView):
    def patch(self, request):
        recipient_id = request.data.get('recipient_id')
        if not recipient_id:
            return Response({'error': 'recipient_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        updated = Notification.objects.filter(recipient_id=recipient_id, is_read=False).update(is_read=True)
        return Response({'detail': f'{updated} notification(s) marked as read.'})


class UnreadCountView(APIView):
    def get(self, request):
        recipient_id = request.query_params.get('recipient_id')
        if not recipient_id:
            return Response({'error': 'recipient_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        count = Notification.objects.filter(recipient_id=recipient_id, is_read=False).count()
        return Response(UnreadCountSerializer({'recipient_id': recipient_id, 'unread_count': count}).data)
