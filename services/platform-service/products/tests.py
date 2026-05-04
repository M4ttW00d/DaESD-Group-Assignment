from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.management import call_command
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from .models import Product, Category
from orders.models import SurplusDeal

User = get_user_model()


def _make_producer(username='producer'):
    return User.objects.create_user(username=username, password='pass', role='PRODUCER')

def _make_customer(username='customer'):
    return User.objects.create_user(username=username, password='pass', role='CUSTOMER')

def _make_product(producer, category, name='Carrots', price='10.00', stock=100,
                  seasonal_start=None, seasonal_end=None):
    return Product.objects.create(
        producer=producer,
        category=category,
        name=name,
        price=Decimal(price),
        stock_quantity=stock,
        seasonal_start_month=seasonal_start,
        seasonal_end_month=seasonal_end,
    )


class ProductSurplusDealTests(TestCase):
    def setUp(self):
        self.producer = _make_producer()
        self.category = Category.objects.create(name='Vegetables')
        self.product = _make_product(self.producer, self.category)

    def test_no_surplus_deal(self):
        self.assertFalse(self.product.is_surplus)
        self.assertEqual(self.product.current_price, Decimal('10.00'))
        self.assertIsNone(self.product.surplus_deal)

    def test_active_surplus_deal(self):
        deal = SurplusDeal.objects.create(
            product=self.product,
            discount_percentage=Decimal('20.00'),
            expiry_date=timezone.now() + timedelta(days=1)
        )
        self.assertTrue(self.product.is_surplus)
        self.assertEqual(self.product.current_price, Decimal('8.00'))
        self.assertEqual(self.product.surplus_deal, deal)

    def test_expired_surplus_deal(self):
        SurplusDeal.objects.create(
            product=self.product,
            discount_percentage=Decimal('50.00'),
            expiry_date=timezone.now() - timedelta(days=1)
        )
        self.assertFalse(self.product.is_surplus)
        self.assertEqual(self.product.current_price, Decimal('10.00'))
        self.assertIsNone(self.product.surplus_deal)


class ProductSeasonalPropertyTests(TestCase):
    def setUp(self):
        self.producer = _make_producer()
        self.category = Category.objects.create(name='Veg')

    def test_always_in_season_when_no_months_set(self):
        product = _make_product(self.producer, self.category)
        self.assertTrue(product.is_currently_in_season)
        self.assertIsNone(product.seasonal_availability_text)

    def test_in_season_within_range(self):
        current_month = timezone.now().month
        start = max(1, current_month - 1)
        end = min(12, current_month + 1)
        product = _make_product(self.producer, self.category,
                                seasonal_start=start, seasonal_end=end)
        self.assertTrue(product.is_currently_in_season)

    def test_seasonal_availability_text_format(self):
        product = _make_product(self.producer, self.category,
                                seasonal_start=6, seasonal_end=8)
        self.assertEqual(product.seasonal_availability_text, 'Jun - Aug')

    def test_seasonal_reminder_tracking_fields_default_null(self):
        product = _make_product(self.producer, self.category)
        self.assertIsNone(product.seasonal_reminder_sent_month)
        self.assertIsNone(product.seasonal_reminder_sent_year)


class SeasonalReminderPerformUpdateTest(TestCase):
    def setUp(self):
        from rest_framework.test import APIClient
        self.client = APIClient()
        self.producer = _make_producer('farmer_john')
        self.category = Category.objects.create(name='Greens')
        self.next_month = timezone.now().month % 12 + 1
        self.product = _make_product(
            self.producer, self.category,
            name='Spinach',
            seasonal_start=self.next_month,
            seasonal_end=(self.next_month % 12) + 1,
        )
        self.client.force_authenticate(user=self.producer)

    def _patch_product(self, data=None):
        payload = {'name': 'Spinach', 'price': '10.00', 'stock_quantity': 50}
        if data:
            payload.update(data)
        return self.client.patch(
            f'/api/products/{self.product.pk}/',
            data=payload,
            format='json',
        )

    @patch('products.views.http_requests.post')
    def test_seasonal_reminder_sent_when_start_month_matches_next_month(self, mock_post):
        mock_post.return_value = MagicMock(status_code=201)
        resp = self._patch_product()
        self.assertEqual(resp.status_code, 200)
        reminder_calls = [
            c for c in mock_post.call_args_list
            if c[1].get('json', {}).get('type') == 'SEASONAL_REMINDER'
            and c[1].get('json', {}).get('user') == self.producer.id
        ]
        self.assertEqual(len(reminder_calls), 1)

    @patch('products.views.http_requests.post')
    def test_seasonal_reminder_not_sent_when_already_sent_this_month(self, mock_post):
        mock_post.return_value = MagicMock(status_code=201)
        Product.objects.filter(pk=self.product.pk).update(
            seasonal_reminder_sent_month=self.next_month,
            seasonal_reminder_sent_year=timezone.now().year,
        )
        self._patch_product()
        reminder_calls = [
            c for c in mock_post.call_args_list
            if c[1].get('json', {}).get('type') == 'SEASONAL_REMINDER'
        ]
        self.assertEqual(len(reminder_calls), 0)

    @patch('products.views.http_requests.post')
    def test_seasonal_reminder_not_sent_when_start_month_does_not_match(self, mock_post):
        mock_post.return_value = MagicMock(status_code=201)
        wrong_month = (self.next_month % 12) + 1
        self._patch_product({'seasonal_start_month': wrong_month})
        reminder_calls = [
            c for c in mock_post.call_args_list
            if c[1].get('json', {}).get('type') == 'SEASONAL_REMINDER'
        ]
        self.assertEqual(len(reminder_calls), 0)

    @patch('products.views.http_requests.post')
    def test_tracking_fields_updated_after_reminder_sent(self, mock_post):
        mock_post.return_value = MagicMock(status_code=201)
        self._patch_product()
        updated = Product.objects.get(pk=self.product.pk)
        self.assertEqual(updated.seasonal_reminder_sent_month, self.next_month)
        self.assertEqual(updated.seasonal_reminder_sent_year, timezone.now().year)

    @patch('products.views.http_requests.post')
    def test_notification_failure_does_not_break_product_save(self, mock_post):
        mock_post.side_effect = Exception('Network timeout')
        resp = self._patch_product()
        self.assertEqual(resp.status_code, 200)


class SendSeasonalRemindersCommandTest(TestCase):
    def setUp(self):
        self.producer1 = _make_producer('grower_a')
        self.producer2 = _make_producer('grower_b')
        self.category = Category.objects.create(name='Seasonal')
        self.next_month = timezone.now().month % 12 + 1

    @patch('products.management.commands.send_seasonal_reminders.requests.post')
    def test_command_sends_notification_for_each_qualifying_product(self, mock_post):
        mock_post.return_value = MagicMock(status_code=201)
        _make_product(self.producer1, self.category, name='Leeks',
                      seasonal_start=self.next_month)
        _make_product(self.producer1, self.category, name='Kale',
                      seasonal_start=self.next_month)
        out = StringIO()
        call_command('send_seasonal_reminders', stdout=out)
        self.assertIn('Seasonal reminders sent: 2', out.getvalue())
        self.assertEqual(mock_post.call_count, 2)

    @patch('products.management.commands.send_seasonal_reminders.requests.post')
    def test_command_skips_unavailable_products(self, mock_post):
        mock_post.return_value = MagicMock(status_code=201)
        _make_product(self.producer1, self.category, name='Available Leeks',
                      seasonal_start=self.next_month)
        unavailable = _make_product(self.producer1, self.category, name='Unavailable Kale',
                                    seasonal_start=self.next_month)
        unavailable.is_available = False
        unavailable.save()
        out = StringIO()
        call_command('send_seasonal_reminders', stdout=out)
        self.assertIn('Seasonal reminders sent: 1', out.getvalue())

    @patch('products.management.commands.send_seasonal_reminders.requests.post')
    def test_command_skips_products_with_wrong_start_month(self, mock_post):
        mock_post.return_value = MagicMock(status_code=201)
        wrong_month = (self.next_month % 12) + 1
        _make_product(self.producer1, self.category, name='Wrong Month Veg',
                      seasonal_start=wrong_month)
        out = StringIO()
        call_command('send_seasonal_reminders', stdout=out)
        self.assertIn('Seasonal reminders sent: 0', out.getvalue())
        mock_post.assert_not_called()

    @patch('products.management.commands.send_seasonal_reminders.requests.post')
    def test_command_notifies_multiple_producers_independently(self, mock_post):
        mock_post.return_value = MagicMock(status_code=201)
        _make_product(self.producer1, self.category, name='Prod1 Veg',
                      seasonal_start=self.next_month)
        _make_product(self.producer2, self.category, name='Prod2 Veg',
                      seasonal_start=self.next_month)
        out = StringIO()
        call_command('send_seasonal_reminders', stdout=out)
        self.assertIn('Seasonal reminders sent: 2', out.getvalue())
        notified_users = {c[1]['json']['user'] for c in mock_post.call_args_list}
        self.assertIn(self.producer1.id, notified_users)
        self.assertIn(self.producer2.id, notified_users)

    @patch('products.management.commands.send_seasonal_reminders.requests.post')
    def test_command_sends_correct_notification_payload(self, mock_post):
        mock_post.return_value = MagicMock(status_code=201)
        _make_product(self.producer1, self.category, name='Strawberries',
                      seasonal_start=self.next_month)
        call_command('send_seasonal_reminders', stdout=StringIO())
        payload = mock_post.call_args[1]['json']
        self.assertEqual(payload['user'], self.producer1.id)
        self.assertEqual(payload['type'], 'SEASONAL_REMINDER')
        self.assertIn('Strawberries', payload['title'])
        self.assertIn('Strawberries', payload['message'])


class SurplusDealFavouriteNotificationTest(TestCase):
    def setUp(self):
        from rest_framework.test import APIClient
        self.client = APIClient()
        self.producer = _make_producer('surplus_farmer')
        self.customer_with_order = _make_customer('buyer')
        self.customer_favouriter = _make_customer('fan')
        self.customer_both = _make_customer('loyal')
        self.category = Category.objects.create(name='Surplus')
        self.product = _make_product(self.producer, self.category, name='Tomatoes')
        self.client.force_authenticate(user=self.producer)

    def _add_favourite(self, customer):
        from users.models import FavouriteProducer
        FavouriteProducer.objects.get_or_create(customer=customer, producer=self.producer)

    def _add_order(self, customer):
        from orders.models import Order, CustomerOrder
        customer_order = CustomerOrder.objects.create(customer=customer)
        Order.objects.create(
            customer=customer,
            customer_order=customer_order,
            producer=self.producer,
            total_amount=self.product.price,
            status='DELIVERED',
        )

    def _patch_with_surplus(self, discount=20):
        return self.client.patch(
            f'/api/products/{self.product.pk}/',
            data={
                'name': 'Tomatoes', 'price': '10.00', 'stock_quantity': 50,
                'is_surplus': 'true',
                'surplus_deal.discount_percentage': str(discount),
                'surplus_deal.expiry_date': (timezone.now() + timedelta(days=2)).isoformat(),
            },
        )

    @patch('products.views.http_requests.post')
    def test_favouriter_without_order_receives_surplus_notification(self, mock_post):
        mock_post.return_value = MagicMock(status_code=201)
        self._add_favourite(self.customer_favouriter)
        self._patch_with_surplus()
        surplus_calls = [
            c for c in mock_post.call_args_list
            if c[1].get('json', {}).get('type') == 'SURPLUS_DEAL'
            and c[1].get('json', {}).get('user') == self.customer_favouriter.id
        ]
        self.assertEqual(len(surplus_calls), 1)

    @patch('products.views.http_requests.post')
    def test_prior_order_customer_receives_surplus_notification(self, mock_post):
        mock_post.return_value = MagicMock(status_code=201)
        self._add_order(self.customer_with_order)
        self._patch_with_surplus()
        surplus_calls = [
            c for c in mock_post.call_args_list
            if c[1].get('json', {}).get('type') == 'SURPLUS_DEAL'
            and c[1].get('json', {}).get('user') == self.customer_with_order.id
        ]
        self.assertEqual(len(surplus_calls), 1)

    @patch('products.views.http_requests.post')
    def test_customer_in_both_groups_receives_only_one_notification(self, mock_post):
        mock_post.return_value = MagicMock(status_code=201)
        self._add_order(self.customer_both)
        self._add_favourite(self.customer_both)
        self._patch_with_surplus()
        surplus_calls = [
            c for c in mock_post.call_args_list
            if c[1].get('json', {}).get('type') == 'SURPLUS_DEAL'
            and c[1].get('json', {}).get('user') == self.customer_both.id
        ]
        self.assertEqual(len(surplus_calls), 1)

    @patch('products.views.http_requests.post')
    def test_no_surplus_notification_when_deal_already_existed(self, mock_post):
        mock_post.return_value = MagicMock(status_code=201)
        self._add_favourite(self.customer_favouriter)
        SurplusDeal.objects.create(
            product=self.product,
            discount_percentage=Decimal('20.00'),
            expiry_date=timezone.now() + timedelta(days=3),
        )
        mock_post.reset_mock()
        self._patch_with_surplus(discount=25)
        surplus_calls = [
            c for c in mock_post.call_args_list
            if c[1].get('json', {}).get('type') == 'SURPLUS_DEAL'
        ]
        self.assertEqual(len(surplus_calls), 0)
