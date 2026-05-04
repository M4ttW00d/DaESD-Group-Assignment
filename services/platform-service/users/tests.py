from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

from .models import FavouriteProducer

User = get_user_model()


def _make_customer(username='customer'):
    return User.objects.create_user(username=username, password='pass', role='CUSTOMER')

def _make_producer(username='producer'):
    return User.objects.create_user(username=username, password='pass', role='PRODUCER')


class FavouriteProducerModelTest(TestCase):

    def setUp(self):
        self.customer = _make_customer()
        self.producer = _make_producer()

    def test_can_create_favourite_relationship(self):
        fav = FavouriteProducer.objects.create(customer=self.customer, producer=self.producer)
        self.assertEqual(fav.customer, self.customer)
        self.assertEqual(fav.producer, self.producer)

    def test_unique_together_prevents_duplicates(self):
        from django.db import IntegrityError
        FavouriteProducer.objects.create(customer=self.customer, producer=self.producer)
        with self.assertRaises(IntegrityError):
            FavouriteProducer.objects.create(customer=self.customer, producer=self.producer)

    def test_str_representation(self):
        fav = FavouriteProducer.objects.create(customer=self.customer, producer=self.producer)
        self.assertIn(self.customer.username, str(fav))
        self.assertIn(self.producer.username, str(fav))

    def test_different_customers_can_favourite_same_producer(self):
        customer2 = _make_customer('customer2')
        FavouriteProducer.objects.create(customer=self.customer, producer=self.producer)
        FavouriteProducer.objects.create(customer=customer2, producer=self.producer)
        self.assertEqual(FavouriteProducer.objects.filter(producer=self.producer).count(), 2)

    def test_same_customer_can_favourite_different_producers(self):
        producer2 = _make_producer('producer2')
        FavouriteProducer.objects.create(customer=self.customer, producer=self.producer)
        FavouriteProducer.objects.create(customer=self.customer, producer=producer2)
        self.assertEqual(FavouriteProducer.objects.filter(customer=self.customer).count(), 2)


class FavouriteProducerListTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.customer = _make_customer()
        self.producer1 = _make_producer('prod1')
        self.producer2 = _make_producer('prod2')

    def test_returns_empty_list_when_no_favourites(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.get('/api/auth/favourites/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['favourited_producer_ids'], [])

    def test_returns_correct_producer_ids(self):
        FavouriteProducer.objects.create(customer=self.customer, producer=self.producer1)
        FavouriteProducer.objects.create(customer=self.customer, producer=self.producer2)
        self.client.force_authenticate(user=self.customer)
        resp = self.client.get('/api/auth/favourites/')
        self.assertEqual(resp.status_code, 200)
        ids = resp.json()['favourited_producer_ids']
        self.assertIn(self.producer1.id, ids)
        self.assertIn(self.producer2.id, ids)
        self.assertEqual(len(ids), 2)

    def test_only_returns_own_favourites(self):
        customer2 = _make_customer('customer2')
        FavouriteProducer.objects.create(customer=customer2, producer=self.producer1)
        self.client.force_authenticate(user=self.customer)
        resp = self.client.get('/api/auth/favourites/')
        self.assertEqual(resp.json()['favourited_producer_ids'], [])

    def test_unauthenticated_request_returns_401(self):
        resp = self.client.get('/api/auth/favourites/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class FavouriteProducerToggleTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.customer = _make_customer()
        self.producer = _make_producer()

    def _toggle(self, producer_id=None):
        pid = producer_id or self.producer.id
        return self.client.post(f'/api/auth/favourites/{pid}/')

    def test_first_toggle_creates_favourite_and_returns_201(self):
        self.client.force_authenticate(user=self.customer)
        resp = self._toggle()
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(resp.json()['favourited'])
        self.assertEqual(FavouriteProducer.objects.count(), 1)

    def test_second_toggle_removes_favourite_and_returns_200(self):
        FavouriteProducer.objects.create(customer=self.customer, producer=self.producer)
        self.client.force_authenticate(user=self.customer)
        resp = self._toggle()
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(resp.json()['favourited'])
        self.assertEqual(FavouriteProducer.objects.count(), 0)

    def test_toggle_twice_results_in_favourite(self):
        self.client.force_authenticate(user=self.customer)
        self._toggle()
        self._toggle()
        resp = self._toggle()
        self.assertTrue(resp.json()['favourited'])
        self.assertEqual(FavouriteProducer.objects.count(), 1)

    def test_cannot_favourite_non_existent_user(self):
        self.client.force_authenticate(user=self.customer)
        resp = self._toggle(producer_id=99999)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_favourite_customer_account(self):
        other_customer = _make_customer('other')
        self.client.force_authenticate(user=self.customer)
        resp = self._toggle(producer_id=other_customer.id)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_favourite_yourself(self):
        self.client.force_authenticate(user=self.producer)
        resp = self._toggle(producer_id=self.producer.id)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('yourself', resp.json()['detail'])

    def test_unauthenticated_toggle_returns_401(self):
        resp = self._toggle()
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(FavouriteProducer.objects.count(), 0)

    def test_multiple_customers_can_independently_favourite_same_producer(self):
        customer2 = _make_customer('customer2')
        self.client.force_authenticate(user=self.customer)
        self._toggle()
        self.client.force_authenticate(user=customer2)
        self._toggle()
        self.assertEqual(FavouriteProducer.objects.filter(producer=self.producer).count(), 2)
