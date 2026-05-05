from django.urls import path
from .views import (
    NotificationCreateView,
    NotificationListView,
    NotificationDetailView,
    MarkAllReadView,
    UnreadCountView,
    NotificationPreferenceView,
    NotificationTypePreferenceView,
    NotificationAdminListView,
    EmailLogAdminView,
)

urlpatterns = [
    path('', NotificationCreateView.as_view(), name='notification-create'),
    path('list/', NotificationListView.as_view(), name='notification-list'),
    path('unread-count/', UnreadCountView.as_view(), name='notification-unread-count'),
    path('read-all/', MarkAllReadView.as_view(), name='notification-read-all'),
    path('preferences/', NotificationPreferenceView.as_view(), name='notification-preferences'),
    path('preferences/types/', NotificationTypePreferenceView.as_view(), name='notification-type-preferences'),
    path('admin/list/', NotificationAdminListView.as_view(), name='notification-admin-list'),
    path('admin/email-logs/', EmailLogAdminView.as_view(), name='email-log-admin'),
    path('<int:pk>/', NotificationDetailView.as_view(), name='notification-detail'),
]
