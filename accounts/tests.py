from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import User, Designation, Department
from restaurants.models import Restaurant, Region


class DesignationModelTest(TestCase):
    def test_create_designation(self):
        d = Designation.objects.create(name='Store Manager')
        self.assertEqual(str(d), 'Store Manager')
        self.assertEqual(d.slug, 'store-manager')

    def test_unique_name(self):
        Designation.objects.create(name='Cashier')
        with self.assertRaises(Exception):
            Designation.objects.create(name='Cashier')


class DepartmentModelTest(TestCase):
    def test_create_department(self):
        d = Department.objects.create(name='Operations')
        self.assertEqual(str(d), 'Operations')
        self.assertEqual(d.slug, 'operations')


class UserModelTest(TestCase):
    def test_create_admin(self):
        user = User.objects.create_superuser('admin', 'admin@test.com', 'pass')
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_admin)

    def test_create_auditor(self):
        manager = User.objects.create_user('mgr', 'm@t.com', 'pass')
        manager.role = User.Roles.MANAGER
        manager.save()
        user = User.objects.create_user('auditor1', 'a@t.com', 'pass')
        user.role = User.Roles.AUDITOR
        user.manager = manager
        user.full_clean()
        user.save()
        self.assertEqual(user.role, 'auditor')
        self.assertTrue(user.is_auditor)

    def test_create_manager(self):
        user = User.objects.create_user('mgr1', 'm@t.com', 'pass')
        user.role = User.Roles.MANAGER
        user.full_clean()
        user.save()
        self.assertTrue(user.is_manager)

    def test_create_restaurant_user(self):
        user = User.objects.create_user('ru1', 'r@t.com', 'pass')
        user.role = User.Roles.RESTAURANT_USER
        user.full_clean()
        user.save()
        self.assertTrue(user.is_restaurant_user)

    def test_string_representation(self):
        user = User.objects.create_user('jdoe', 'j@t.com', 'pass')
        user.first_name = 'John'
        user.last_name = 'Doe'
        user.save()
        self.assertEqual(str(user), 'John Doe')

    def test_mobile_formatting(self):
        user = User.objects.create_user('test', 't@t.com', 'pass')
        user.mobile_number = '03001234567'
        user.save()
        self.assertEqual(user.mobile_number, '0300-1234567')

    def test_mobile_formatting_international(self):
        user = User.objects.create_user('test2', 't2@t.com', 'pass')
        user.mobile_number = '+923001234567'
        user.save()
        self.assertEqual(user.mobile_number, '+92300-1234567')

    def test_auditor_must_have_manager(self):
        user = User.objects.create_user('aud', 'a@t.com', 'pass')
        user.role = User.Roles.AUDITOR
        with self.assertRaises(ValidationError):
            user.full_clean()


class UserRestaurantValidationTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name='Test Region')
        self.r1 = Restaurant.objects.create(
            code='1234567', name='R1', city='City', address='Addr'
        )
        self.r2 = Restaurant.objects.create(
            code='7654321', name='R2', city='City', address='Addr'
        )

    def test_auditor_needs_at_least_one_restaurant(self):
        manager = User.objects.create_user('mgr', 'm@t.com', 'pass')
        manager.role = User.Roles.MANAGER
        manager.save()
        user = User.objects.create_user('aud', 'a@t.com', 'pass')
        user.role = User.Roles.AUDITOR
        user.manager = manager
        user.clean()
        user.save()
        with self.assertRaises(ValidationError):
            user.validate_restaurants()

    def test_restaurant_user_needs_exactly_one(self):
        user = User.objects.create_user('ru', 'r@t.com', 'pass')
        user.role = User.Roles.RESTAURANT_USER
        user.clean()
        user.save()
        user.restaurants.add(self.r1)
        with self.assertRaises(ValidationError):
            user.restaurants.add(self.r2)


class RoleGroupSyncSignalTest(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='Auditor')

    def test_role_syncs_to_group(self):
        user = User.objects.create_user('aud', 'a@t.com', 'pass')
        user.role = User.Roles.AUDITOR
        user.save()
        group = Group.objects.get(name='Auditor')
        self.assertIn(group, user.groups.all())

    def test_role_change_updates_group(self):
        user = User.objects.create_user('mgr', 'm@t.com', 'pass')
        user.role = User.Roles.MANAGER
        user.save()
        manager_group = Group.objects.get(name='Manager')
        self.assertIn(manager_group, user.groups.all())

        user.role = User.Roles.AUDITOR
        user.save()
        auditor_group = Group.objects.get(name='Auditor')
        self.assertIn(auditor_group, user.groups.all())
        self.assertNotIn(manager_group, user.groups.all())


class ProfileViewTest(TestCase):
    def test_profile_requires_login(self):
        resp = self.client.get('/accounts/profile/')
        self.assertEqual(resp.status_code, 302)

    def test_profile_renders(self):
        user = User.objects.create_user('test', 't@t.com', 'pass')
        self.client.force_login(user)
        resp = self.client.get('/accounts/profile/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'My Profile')
        self.assertContains(resp, 'test')
