from django.test import TestCase
from django.conf import settings
from rest_framework.test import APIClient

from .models import Notification, NotificationPreference, NotificationTypePreference, EmailLog


def _secret():
    return settings.SERVICE_SECRET_KEY


def _make_notification(**kwargs):
    defaults = dict(recipient_id=1, message='Default message', notification_type='GENERAL')
    defaults.update(kwargs)
    return Notification.objects.create(**defaults)


class NotificationCreateTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.url = '/api/notifications/'

    def test_create_with_valid_secret_returns_201(self):
        resp = self.client.post(
            self.url,
            data={'user': 1, 'message': 'Order placed', 'type': 'ORDER_PLACED'},
            format='json',
            HTTP_X_SERVICE_SECRET=_secret(),
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(Notification.objects.count(), 1)

    def test_create_without_secret_returns_401(self):
        resp = self.client.post(
            self.url,
            data={'user': 1, 'message': 'Test'},
            format='json',
        )
        self.assertEqual(resp.status_code, 401)

    def test_create_with_wrong_secret_returns_401(self):
        resp = self.client.post(
            self.url,
            data={'user': 1, 'message': 'Test', 'type': 'GENERAL'},
            format='json',
            HTTP_X_SERVICE_SECRET='totally-wrong-secret',
        )
        self.assertEqual(resp.status_code, 401)

    def test_create_missing_message_returns_400(self):
        resp = self.client.post(
            self.url,
            data={'user': 1, 'type': 'GENERAL'},
            format='json',
            HTTP_X_SERVICE_SECRET=_secret(),
        )
        self.assertEqual(resp.status_code, 400)

    def test_create_missing_user_returns_400(self):
        resp = self.client.post(
            self.url,
            data={'message': 'No user', 'type': 'GENERAL'},
            format='json',
            HTTP_X_SERVICE_SECRET=_secret(),
        )
        self.assertEqual(resp.status_code, 400)

    def test_all_notification_types_accepted(self):
        types = [
            'ORDER_PLACED', 'ORDER_CONFIRMED', 'ORDER_READY', 'ORDER_DELIVERED',
            'ORDER_CANCELLED', 'ORDER_UPDATE', 'LOW_STOCK', 'OUT_OF_STOCK',
            'SURPLUS_DEAL', 'SEASONAL_REMINDER', 'PAYMENT_RECEIVED', 'SETTLEMENT_READY', 'GENERAL',
        ]
        for notif_type in types:
            resp = self.client.post(
                self.url,
                data={'user': 1, 'message': f'Test {notif_type}', 'type': notif_type},
                format='json',
                HTTP_X_SERVICE_SECRET=_secret(),
            )
            self.assertEqual(resp.status_code, 201, f"Expected 201 for type '{notif_type}'")

    def test_notification_saved_with_correct_fields(self):
        self.client.post(
            self.url,
            data={
                'user': 42,
                'message': 'Your order is confirmed.',
                'type': 'ORDER_CONFIRMED',
                'title': 'Order Confirmed',
            },
            format='json',
            HTTP_X_SERVICE_SECRET=_secret(),
        )
        notif = Notification.objects.get()
        self.assertEqual(notif.recipient_id, 42)
        self.assertEqual(notif.message, 'Your order is confirmed.')
        self.assertEqual(notif.notification_type, 'ORDER_CONFIRMED')
        self.assertEqual(notif.title, 'Order Confirmed')
        self.assertFalse(notif.is_read)

    def test_default_type_is_general(self):
        self.client.post(
            self.url,
            data={'user': 1, 'message': 'Hello'},
            format='json',
            HTTP_X_SERVICE_SECRET=_secret(),
        )
        self.assertEqual(Notification.objects.get().notification_type, 'GENERAL')


class NotificationListTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        _make_notification(recipient_id=1, notification_type='ORDER_PLACED', is_read=True)
        _make_notification(recipient_id=1, notification_type='ORDER_CONFIRMED', is_read=False)
        _make_notification(recipient_id=2, notification_type='GENERAL', is_read=False)

    def test_list_returns_only_matching_recipient(self):
        resp = self.client.get('/api/notifications/list/', {'recipient_id': 1})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 2)

    def test_list_filter_unread_only(self):
        resp = self.client.get('/api/notifications/list/', {'recipient_id': 1, 'unread': 'true'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertFalse(data[0]['is_read'])

    def test_list_filter_by_type(self):
        resp = self.client.get(
            '/api/notifications/list/',
            {'recipient_id': 1, 'type': 'ORDER_PLACED'}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 1)

    def test_list_missing_recipient_id_returns_400(self):
        resp = self.client.get('/api/notifications/list/')
        self.assertEqual(resp.status_code, 400)


class UnreadCountTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        _make_notification(recipient_id=1, is_read=False)
        _make_notification(recipient_id=1, is_read=False)
        _make_notification(recipient_id=1, is_read=True)

    def test_unread_count_correct(self):
        resp = self.client.get('/api/notifications/unread-count/', {'recipient_id': 1})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['unread_count'], 2)

    def test_unread_count_zero_for_unknown_recipient(self):
        resp = self.client.get('/api/notifications/unread-count/', {'recipient_id': 999})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['unread_count'], 0)

    def test_unread_count_missing_recipient_returns_400(self):
        resp = self.client.get('/api/notifications/unread-count/')
        self.assertEqual(resp.status_code, 400)


class NotificationDetailTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.notif = _make_notification(recipient_id=1, is_read=False)

    def test_mark_as_read_via_patch(self):
        resp = self.client.patch(
            f'/api/notifications/{self.notif.pk}/',
            data={'recipient_id': 1},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.notif.refresh_from_db()
        self.assertTrue(self.notif.is_read)

    def test_patch_wrong_recipient_returns_404(self):
        resp = self.client.patch(
            f'/api/notifications/{self.notif.pk}/',
            data={'recipient_id': 99},
            format='json',
        )
        self.assertEqual(resp.status_code, 404)

    def test_delete_notification(self):
        resp = self.client.delete(
            f'/api/notifications/{self.notif.pk}/?recipient_id=1'
        )
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(Notification.objects.count(), 0)

    def test_delete_wrong_recipient_returns_404(self):
        resp = self.client.delete(
            f'/api/notifications/{self.notif.pk}/?recipient_id=99'
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(Notification.objects.count(), 1)


class MarkAllReadTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        for i in range(3):
            _make_notification(recipient_id=1, message=f'Notif {i}', is_read=False)
        _make_notification(recipient_id=2, is_read=False)

    def test_mark_all_read_for_user(self):
        resp = self.client.patch(
            '/api/notifications/read-all/',
            data={'recipient_id': 1},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            Notification.objects.filter(recipient_id=1, is_read=False).count(), 0
        )

    def test_mark_all_read_does_not_affect_other_users(self):
        self.client.patch(
            '/api/notifications/read-all/',
            data={'recipient_id': 1},
            format='json',
        )
        self.assertEqual(
            Notification.objects.filter(recipient_id=2, is_read=False).count(), 1
        )

    def test_mark_all_read_missing_recipient_returns_400(self):
        resp = self.client.patch(
            '/api/notifications/read-all/',
            data={},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)


class SeasonalReminderNotificationTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.url = '/api/notifications/'

    def test_seasonal_reminder_type_accepted(self):
        resp = self.client.post(
            self.url,
            data={
                'user': 10,
                'message': "Your product 'Spinach' comes into season in June.",
                'type': 'SEASONAL_REMINDER',
                'title': 'Season Starting: Spinach',
            },
            format='json',
            HTTP_X_SERVICE_SECRET=_secret(),
        )
        self.assertEqual(resp.status_code, 201)
        notif = Notification.objects.get()
        self.assertEqual(notif.notification_type, 'SEASONAL_REMINDER')
        self.assertEqual(notif.recipient_id, 10)

    def test_seasonal_reminder_appears_in_list(self):
        _make_notification(recipient_id=5, notification_type='SEASONAL_REMINDER',
                           title='Season Starting: Leeks')
        _make_notification(recipient_id=5, notification_type='ORDER_PLACED')
        resp = self.client.get('/api/notifications/list/',
                               {'recipient_id': 5, 'type': 'SEASONAL_REMINDER'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['notification_type'], 'SEASONAL_REMINDER')

    def test_seasonal_reminder_counted_as_unread(self):
        _make_notification(recipient_id=7, notification_type='SEASONAL_REMINDER', is_read=False)
        _make_notification(recipient_id=7, notification_type='SEASONAL_REMINDER', is_read=True)
        resp = self.client.get('/api/notifications/unread-count/', {'recipient_id': 7})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['unread_count'], 1)

    def test_seasonal_reminder_can_be_marked_read(self):
        notif = _make_notification(recipient_id=8, notification_type='SEASONAL_REMINDER',
                                   is_read=False)
        resp = self.client.patch(
            f'/api/notifications/{notif.pk}/',
            data={'recipient_id': 8},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        notif.refresh_from_db()
        self.assertTrue(notif.is_read)

    def test_multiple_seasonal_reminders_for_same_producer(self):
        for product_name in ['Spinach', 'Courgettes', 'Leeks']:
            self.client.post(
                self.url,
                data={
                    'user': 28,
                    'type': 'SEASONAL_REMINDER',
                    'title': f'Season Starting: {product_name}',
                    'message': f"Your product '{product_name}' comes into season in June.",
                },
                format='json',
                HTTP_X_SERVICE_SECRET=_secret(),
            )
        self.assertEqual(
            Notification.objects.filter(recipient_id=28, notification_type='SEASONAL_REMINDER').count(),
            3
        )


class ShowInAppPreferenceTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.url = '/api/notifications/'

    def test_notification_created_with_show_in_app_true_by_default(self):
        self.client.post(
            self.url,
            data={'user': 1, 'message': 'Test', 'type': 'GENERAL'},
            format='json',
            HTTP_X_SERVICE_SECRET=_secret(),
        )
        self.assertTrue(Notification.objects.get().show_in_app)

    def test_in_app_disabled_globally_hides_from_list(self):
        NotificationPreference.objects.create(user_id=1, in_app_enabled=False, email_enabled=True)
        self.client.post(
            self.url,
            data={'user': 1, 'message': 'Test', 'type': 'GENERAL'},
            format='json',
            HTTP_X_SERVICE_SECRET=_secret(),
        )
        notif = Notification.objects.get()
        self.assertFalse(notif.show_in_app)
        resp = self.client.get('/api/notifications/list/', {'recipient_id': 1})
        self.assertEqual(len(resp.json()), 0)

    def test_in_app_disabled_globally_excluded_from_unread_count(self):
        NotificationPreference.objects.create(user_id=2, in_app_enabled=False, email_enabled=True)
        self.client.post(
            self.url,
            data={'user': 2, 'message': 'Test', 'type': 'GENERAL'},
            format='json',
            HTTP_X_SERVICE_SECRET=_secret(),
        )
        resp = self.client.get('/api/notifications/unread-count/', {'recipient_id': 2})
        self.assertEqual(resp.json()['unread_count'], 0)

    def test_type_preference_overrides_in_app_for_specific_type(self):
        NotificationPreference.objects.create(user_id=3, in_app_enabled=True, email_enabled=True)
        NotificationTypePreference.objects.create(
            user_id=3, notification_type='ORDER_PLACED', in_app_enabled=False, email_enabled=True
        )
        self.client.post(
            self.url,
            data={'user': 3, 'message': 'New order', 'type': 'ORDER_PLACED'},
            format='json',
            HTTP_X_SERVICE_SECRET=_secret(),
        )
        notif = Notification.objects.get()
        self.assertFalse(notif.show_in_app)

    def test_both_channels_disabled_still_saves_notification(self):
        NotificationPreference.objects.create(user_id=4, in_app_enabled=False, email_enabled=False)
        self.client.post(
            self.url,
            data={'user': 4, 'message': 'Test', 'type': 'GENERAL'},
            format='json',
            HTTP_X_SERVICE_SECRET=_secret(),
        )
        self.assertEqual(Notification.objects.count(), 1)
        self.assertFalse(Notification.objects.get().show_in_app)


class EmailLogTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.url = '/api/notifications/'

    def test_email_log_created_when_email_provided(self):
        with self.settings(
            SECURE_ENV={'BREVO_SECRET_KEY': '', 'BREVO_SENDER_EMAIL': ''}
        ):
            self.client.post(
                self.url,
                data={
                    'user': 1,
                    'message': 'Your order was placed.',
                    'type': 'ORDER_PLACED',
                    'email': 'customer@example.com',
                },
                format='json',
                HTTP_X_SERVICE_SECRET=_secret(),
            )
        self.assertEqual(EmailLog.objects.count(), 1)
        log = EmailLog.objects.get()
        self.assertEqual(log.recipient_email, 'customer@example.com')
        self.assertEqual(log.status, EmailLog.Status.FAILED)

    def test_email_log_not_created_when_no_email(self):
        self.client.post(
            self.url,
            data={'user': 1, 'message': 'In-app only', 'type': 'GENERAL'},
            format='json',
            HTTP_X_SERVICE_SECRET=_secret(),
        )
        self.assertEqual(EmailLog.objects.count(), 0)

    def test_email_sent_flag_false_when_credentials_missing(self):
        with self.settings(
            SECURE_ENV={'BREVO_SECRET_KEY': '', 'BREVO_SENDER_EMAIL': ''}
        ):
            self.client.post(
                self.url,
                data={
                    'user': 1,
                    'message': 'Test',
                    'type': 'GENERAL',
                    'email': 'test@example.com',
                },
                format='json',
                HTTP_X_SERVICE_SECRET=_secret(),
            )
        self.assertFalse(Notification.objects.get().email_sent)

    def test_email_log_linked_to_notification(self):
        with self.settings(
            SECURE_ENV={'BREVO_SECRET_KEY': '', 'BREVO_SENDER_EMAIL': ''}
        ):
            self.client.post(
                self.url,
                data={
                    'user': 1,
                    'message': 'Test',
                    'type': 'GENERAL',
                    'email': 'test@example.com',
                },
                format='json',
                HTTP_X_SERVICE_SECRET=_secret(),
            )
        notif = Notification.objects.get()
        log = EmailLog.objects.get()
        self.assertEqual(log.notification, notif)

    def test_email_log_stores_subject_and_body(self):
        with self.settings(
            SECURE_ENV={'BREVO_SECRET_KEY': '', 'BREVO_SENDER_EMAIL': ''}
        ):
            self.client.post(
                self.url,
                data={
                    'user': 1,
                    'message': 'Order confirmed.',
                    'type': 'ORDER_CONFIRMED',
                    'title': 'Order Confirmed',
                    'email': 'customer@example.com',
                },
                format='json',
                HTTP_X_SERVICE_SECRET=_secret(),
            )
        log = EmailLog.objects.get()
        self.assertIn('BRFN', log.subject)
        self.assertIn('Bristol Regional Food Network', log.html_body)


class NotificationAdminListTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.url = '/api/notifications/admin/list/'
        _make_notification(recipient_id=1, notification_type='ORDER_PLACED', email_sent=True)
        _make_notification(recipient_id=2, notification_type='PAYMENT_RECEIVED', email_sent=False)
        _make_notification(recipient_id=1, notification_type='ORDER_SUMMARY', email_sent=True)

    def test_admin_list_requires_secret(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 401)

    def test_admin_list_returns_all_by_default(self):
        resp = self.client.get(self.url, HTTP_X_SERVICE_SECRET=_secret())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 3)

    def test_admin_list_filter_by_type(self):
        resp = self.client.get(
            self.url, {'type': 'ORDER_PLACED'}, HTTP_X_SERVICE_SECRET=_secret()
        )
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['notification_type'], 'ORDER_PLACED')

    def test_admin_list_filter_by_recipient(self):
        resp = self.client.get(
            self.url, {'recipient_id': 1}, HTTP_X_SERVICE_SECRET=_secret()
        )
        self.assertEqual(len(resp.json()), 2)

    def test_admin_list_filter_email_sent_true(self):
        resp = self.client.get(
            self.url, {'email_sent': 'true'}, HTTP_X_SERVICE_SECRET=_secret()
        )
        data = resp.json()
        self.assertEqual(len(data), 2)
        self.assertTrue(all(n['email_sent'] for n in data))

    def test_admin_list_filter_email_sent_false(self):
        resp = self.client.get(
            self.url, {'email_sent': 'false'}, HTTP_X_SERVICE_SECRET=_secret()
        )
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertFalse(data[0]['email_sent'])


class EmailLogAdminTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.url = '/api/notifications/admin/email-logs/'
        n1 = _make_notification(recipient_id=1, notification_type='ORDER_PLACED')
        n2 = _make_notification(recipient_id=2, notification_type='PAYMENT_RECEIVED')
        EmailLog.objects.create(
            notification=n1,
            recipient_email='producer@farm.com',
            subject='BRFN: New Order',
            html_body='<div>Order details</div>',
            status=EmailLog.Status.SENT,
        )
        EmailLog.objects.create(
            notification=n2,
            recipient_email='customer@example.com',
            subject='BRFN: Payment',
            html_body='<div>Payment confirmed</div>',
            status=EmailLog.Status.FAILED,
            error_message='API timeout',
        )

    def test_email_log_admin_requires_secret(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 401)

    def test_email_log_admin_returns_all(self):
        resp = self.client.get(self.url, HTTP_X_SERVICE_SECRET=_secret())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 2)

    def test_email_log_filter_by_status_sent(self):
        resp = self.client.get(
            self.url, {'status': 'SENT'}, HTTP_X_SERVICE_SECRET=_secret()
        )
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['status'], 'SENT')

    def test_email_log_filter_by_status_failed(self):
        resp = self.client.get(
            self.url, {'status': 'FAILED'}, HTTP_X_SERVICE_SECRET=_secret()
        )
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['status'], 'FAILED')

    def test_email_log_filter_by_recipient_email(self):
        resp = self.client.get(
            self.url, {'recipient_email': 'producer'}, HTTP_X_SERVICE_SECRET=_secret()
        )
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertIn('producer', data[0]['recipient_email'])

    def test_email_log_filter_by_type(self):
        resp = self.client.get(
            self.url, {'type': 'ORDER_PLACED'}, HTTP_X_SERVICE_SECRET=_secret()
        )
        self.assertEqual(len(resp.json()), 1)

    def test_email_log_contains_notification_id(self):
        resp = self.client.get(self.url, HTTP_X_SERVICE_SECRET=_secret())
        for entry in resp.json():
            self.assertIn('notification_id', entry)


class NewNotificationTypesTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.url = '/api/notifications/'

    def _post(self, notif_type, user=1):
        return self.client.post(
            self.url,
            data={'user': user, 'message': f'Test {notif_type}', 'type': notif_type},
            format='json',
            HTTP_X_SERVICE_SECRET=_secret(),
        )

    def test_order_summary_accepted(self):
        self.assertEqual(self._post('ORDER_SUMMARY').status_code, 201)

    def test_recurring_order_placed_accepted(self):
        self.assertEqual(self._post('RECURRING_ORDER_PLACED').status_code, 201)

    def test_recurring_order_paused_accepted(self):
        self.assertEqual(self._post('RECURRING_ORDER_PAUSED').status_code, 201)

    def test_recurring_order_reminder_accepted(self):
        self.assertEqual(self._post('RECURRING_ORDER_REMINDER').status_code, 201)

    def test_settlement_ready_accepted(self):
        self.assertEqual(self._post('SETTLEMENT_READY').status_code, 201)

    def test_order_update_accepted(self):
        self.assertEqual(self._post('ORDER_UPDATE').status_code, 201)

    def test_payment_failed_accepted(self):
        self.assertEqual(self._post('PAYMENT_FAILED').status_code, 201)

    def test_new_types_appear_in_list(self):
        for t in ['ORDER_SUMMARY', 'RECURRING_ORDER_PLACED', 'SETTLEMENT_READY']:
            _make_notification(recipient_id=99, notification_type=t)
        resp = self.client.get('/api/notifications/list/', {'recipient_id': 99})
        self.assertEqual(resp.status_code, 200)
        types_returned = {n['notification_type'] for n in resp.json()}
        self.assertIn('ORDER_SUMMARY', types_returned)
        self.assertIn('RECURRING_ORDER_PLACED', types_returned)
        self.assertIn('SETTLEMENT_READY', types_returned)
