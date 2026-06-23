from django.test import TestCase

from restaurants.models import Region, Restaurant


class RegionModelTest(TestCase):
    def test_create_region(self):
        r = Region.objects.create(name='Lahore')
        self.assertEqual(str(r), 'Lahore')
        self.assertEqual(r.name, 'Lahore')

    def test_ordering(self):
        Region.objects.create(name='Karachi')
        Region.objects.create(name='Islamabad')
        names = list(Region.objects.values_list('name', flat=True))
        self.assertEqual(names, ['Islamabad', 'Karachi'])


class RestaurantModelTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name='Test')

    def test_create_restaurant(self):
        r = Restaurant.objects.create(
            code='1270001',
            name='McDonald\'s Gulberg',
            city='Lahore',
            address='Main Boulevard, Gulberg',
            region=self.region,
        )
        self.assertEqual(str(r), "McDonald's Gulberg (1270001)")
        self.assertEqual(r.code, '1270001')

    def test_code_is_stripped(self):
        r = Restaurant.objects.create(
            code=' 1270002 ',
            name='Test',
            city='City',
            address='Addr',
        )
        r.refresh_from_db()
        self.assertEqual(r.code, '1270002')

    def test_phone_formatting_local(self):
        r = Restaurant.objects.create(
            code='1270003',
            name='Test',
            city='City',
            address='Addr',
            phone='03001234567',
        )
        r.refresh_from_db()
        self.assertEqual(r.phone, '0300-1234567')

    def test_phone_formatting_international(self):
        r = Restaurant.objects.create(
            code='1270004',
            name='Test',
            city='City',
            address='Addr',
            phone='+923001234567',
        )
        r.refresh_from_db()
        self.assertEqual(r.phone, '+92300-1234567')

    def test_default_status(self):
        r = Restaurant.objects.create(
            code='1270005', name='Test', city='City', address='Addr'
        )
        self.assertEqual(r.status, Restaurant.Status.ACTIVE)

    def test_latest_audit_property(self):
        r = Restaurant.objects.create(
            code='1270006', name='Test', city='City', address='Addr'
        )
        self.assertIsNone(r.latest_audit)
        self.assertEqual(r.submitted_audit_count, 0)
        self.assertIsNone(r.submitted_average_score)
