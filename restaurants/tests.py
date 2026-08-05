from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse

from audits.models import Audit, AuditTemplate
from restaurants.models import Region, Restaurant

User = get_user_model()


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


class RestaurantDetailViewTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name='Test')
        self.restaurant = Restaurant.objects.create(
            code='1270010', name='R1', city='C', address='A', region=self.region)
        self.template = AuditTemplate.objects.create(name='T')
        self.auditor = User.objects.create_user(
            'aud1', 'a1@t.com', 'pass', role=User.Roles.AUDITOR)
        self.auditor.restaurants.add(self.restaurant)
        ct_rest = ContentType.objects.get_for_model(Restaurant)
        self.auditor.user_permissions.add(
            Permission.objects.get(
                content_type=ct_rest, codename='view_restaurant'))
        other = User.objects.create_user('aud2', 'a2@t.com', 'pass')
        Audit.objects.create(
            template=self.template, restaurant=self.restaurant,
            audit_date='2026-07-01', manager_on_duty='M',
            auditor=self.auditor, is_submitted=True,
            total_scored='9', total_possible='10',
        )
        Audit.objects.create(
            template=self.template, restaurant=self.restaurant,
            audit_date='2026-07-05', manager_on_duty='M',
            auditor=other, is_submitted=True,
            total_scored='3', total_possible='10',
        )

    def test_auditor_sees_only_own_audits_on_restaurant_page(self):
        self.client.force_login(self.auditor)
        resp = self.client.get(self.restaurant.get_absolute_url())
        self.assertEqual(resp.status_code, 200)
        ctx = resp.context
        recent = list(ctx['recent_audits'])
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0].auditor_id, self.auditor.pk)
        self.assertEqual(ctx['audit_count'], 1)
        self.assertEqual(ctx['avg_score'], Decimal('90'))
        self.assertEqual(ctx['latest_audit'].auditor_id, self.auditor.pk)


class RestaurantListViewTest(TestCase):
    def setUp(self):
        self.region1 = Region.objects.create(name='North')
        self.region2 = Region.objects.create(name='South')
        self.restaurant = Restaurant.objects.create(
            code='1270020', name='Mine', city='Lahore',
            address='A', region=self.region1)
        Restaurant.objects.create(
            code='1270021', name='Other', city='Karachi',
            address='B', region=self.region2)
        self.auditor = User.objects.create_user(
            'aud_list', 'al@t.com', 'pass', role=User.Roles.AUDITOR)
        self.auditor.restaurants.add(self.restaurant)
        ct_rest = ContentType.objects.get_for_model(Restaurant)
        self.auditor.user_permissions.add(
            Permission.objects.get(
                content_type=ct_rest, codename='view_restaurant'))

    def test_cities_and_region_counts_scoped_to_visible_restaurants(self):
        self.client.force_login(self.auditor)
        resp = self.client.get('/restaurants/')
        self.assertEqual(resp.status_code, 200)
        ctx = resp.context
        self.assertEqual(list(ctx['cities']), ['Lahore'])
        self.assertEqual([r.name for r in ctx['regions']], ['North'])
        self.assertEqual(ctx['regions'][0].restaurant_count, 1)


class RegionDetailViewTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name='Central')
        self.assigned = Restaurant.objects.create(
            code='1270030', name='Mine', city='Lahore',
            address='A', region=self.region)
        self.unassigned = Restaurant.objects.create(
            code='1270031', name='Other', city='Karachi',
            address='B', region=self.region)
        self.auditor = User.objects.create_user(
            'aud_region', 'ar@t.com', 'pass', role=User.Roles.AUDITOR)
        self.auditor.restaurants.add(self.assigned)
        ct_rest = ContentType.objects.get_for_model(Restaurant)
        self.auditor.user_permissions.add(
            Permission.objects.get(
                content_type=ct_rest, codename='view_restaurant'))
        ct_region = ContentType.objects.get_for_model(Region)
        self.auditor.user_permissions.add(
            Permission.objects.get(
                content_type=ct_region, codename='view_region'))

    def test_region_page_shows_only_assigned_restaurants(self):
        self.client.force_login(self.auditor)
        resp = self.client.get(
            reverse('restaurants:region_detail', args=[self.region.pk]))
        self.assertEqual(resp.status_code, 200)
        restaurant_names = [
            r.name for r in resp.context['region'].restaurants.all()]
        self.assertEqual(restaurant_names, ['Mine'])
        self.assertNotIn('Other', restaurant_names)

    def test_region_page_superuser_sees_all_restaurants(self):
        self.auditor.is_superuser = True
        self.auditor.save()
        self.client.force_login(self.auditor)
        resp = self.client.get(
            reverse('restaurants:region_detail', args=[self.region.pk]))
        self.assertEqual(resp.status_code, 200)
        restaurant_names = [
            r.name for r in resp.context['region'].restaurants.all()]
        self.assertEqual(sorted(restaurant_names), ['Mine', 'Other'])
