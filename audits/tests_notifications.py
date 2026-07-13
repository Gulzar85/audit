from unittest.mock import patch, ANY

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from restaurants.models import Restaurant, Region
from core.models import Notification
from audits.models import (
    AuditTemplate, Section, Question,
    Audit, AuditSection, AuditQuestionResponse,
    CorrectiveAction,
)
from audits.utils import (
    _create_notifications,
    notify_restaurant_users,
    notify_auditor_and_manager,
    auto_generate_corrective_actions,
)


class CreateNotificationsUtilTest(TestCase):
    def setUp(self):
        self.u1 = User.objects.create_user('u1', 'u1@t.com', 'pass')
        self.u2 = User.objects.create_user('u2', 'u2@t.com', 'pass')

    def test_creates_notifications_for_each_recipient(self):
        _create_notifications(
            Notification.Type.AUDIT_SUBMITTED, 'Title', 'Msg', '/link/',
            {self.u1, self.u2},
        )
        self.assertEqual(Notification.objects.count(), 2)
        for u in [self.u1, self.u2]:
            n = Notification.objects.get(recipient=u)
            self.assertEqual(n.notification_type, Notification.Type.AUDIT_SUBMITTED)
            self.assertEqual(n.title, 'Title')
            self.assertEqual(n.message, 'Msg')
            self.assertEqual(n.link, '/link/')
            self.assertFalse(n.is_read)

    def test_empty_recipients_creates_nothing(self):
        _create_notifications(Notification.Type.AUDIT_SUBMITTED, 'T', 'M', '/', set())
        self.assertEqual(Notification.objects.count(), 0)

    def test_sends_email_when_email_context_provided(self):
        with patch('audits.utils._send_email_notifications') as mock_send:
            _create_notifications(
                Notification.Type.AUDIT_SUBMITTED, 'T', 'M', '/',
                {self.u1},
                email_context={'subject': 'Test'},
            )
            mock_send.assert_called_once_with(
                {self.u1}, Notification.Type.AUDIT_SUBMITTED, {'subject': 'Test'},
            )

    def test_skips_email_when_no_email_context(self):
        with patch('audits.utils._send_email_notifications') as mock_send:
            _create_notifications(Notification.Type.AUDIT_SUBMITTED, 'T', 'M', '/', {self.u1})
            mock_send.assert_not_called()


class NotifyRestaurantUsersTest(TestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(
            code='1270100', name='R', city='C', address='A')
        self.restaurant_user = User.objects.create_user(
            'ru', 'ru@t.com', 'pass', role=User.Roles.RESTAURANT_USER)
        self.restaurant_user.restaurants.add(self.restaurant)
        self.inactive_user = User.objects.create_user(
            'inact', 'in@t.com', 'pass', role=User.Roles.RESTAURANT_USER,
            is_active=False)
        self.inactive_user.restaurants.add(self.restaurant)
        self.extra = User.objects.create_user('extra', 'ex@t.com', 'pass')

    def test_notifies_all_active_restaurant_users(self):
        notify_restaurant_users(
            Notification.Type.AUDIT_SUBMITTED, 'T', 'M', '/', self.restaurant,
        )
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(Notification.objects.first().recipient, self.restaurant_user)

    def test_includes_extra_recipients(self):
        notify_restaurant_users(
            Notification.Type.AUDIT_SUBMITTED, 'T', 'M', '/', self.restaurant,
            extra_recipients=[self.extra],
        )
        recipients = set(Notification.objects.values_list('recipient_id', flat=True))
        self.assertEqual(recipients, {self.restaurant_user.pk, self.extra.pk})

    def test_deduplicates_when_extra_is_also_restaurant_user(self):
        notify_restaurant_users(
            Notification.Type.AUDIT_SUBMITTED, 'T', 'M', '/', self.restaurant,
            extra_recipients=[self.restaurant_user],
        )
        self.assertEqual(Notification.objects.count(), 1)

    def test_ignores_none_in_extra_recipients(self):
        notify_restaurant_users(
            Notification.Type.AUDIT_SUBMITTED, 'T', 'M', '/', self.restaurant,
            extra_recipients=[None],
        )
        self.assertEqual(Notification.objects.count(), 1)

    def test_skips_inactive_users(self):
        notify_restaurant_users(
            Notification.Type.AUDIT_SUBMITTED, 'T', 'M', '/', self.restaurant,
        )
        self.assertFalse(
            Notification.objects.filter(recipient=self.inactive_user).exists()
        )


class NotifyAuditorAndManagerTest(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(
            'mgr', 'mgr@t.com', 'pass', role=User.Roles.MANAGER)
        self.auditor = User.objects.create_user(
            'aud', 'aud@t.com', 'pass', role=User.Roles.AUDITOR,
            manager=self.manager)

    def test_notifies_auditor_and_manager(self):
        notify_auditor_and_manager(
            Notification.Type.CA_COMPLETED, 'T', 'M', '/', self.auditor,
        )
        recipients = set(Notification.objects.values_list('recipient_id', flat=True))
        self.assertEqual(recipients, {self.auditor.pk, self.manager.pk})

    def test_notifies_auditor_only_when_no_manager(self):
        solo_auditor = User.objects.create_user(
            'solo', 's@t.com', 'pass', role=User.Roles.AUDITOR)
        notify_auditor_and_manager(
            Notification.Type.CA_COMPLETED, 'T', 'M', '/', solo_auditor,
        )
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(Notification.objects.first().recipient, solo_auditor)

    def test_skips_inactive_manager(self):
        self.manager.is_active = False
        self.manager.save()
        notify_auditor_and_manager(
            Notification.Type.CA_COMPLETED, 'T', 'M', '/', self.auditor,
        )
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(Notification.objects.first().recipient, self.auditor)


class SignalCACreatedNotificationTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name='Test')
        self.restaurant = Restaurant.objects.create(
            code='1270200', name='R', city='C', address='A', region=self.region)
        self.manager = User.objects.create_user(
            'mgr2', 'm2@t.com', 'pass', role=User.Roles.MANAGER)
        self.auditor = User.objects.create_user(
            'aud2', 'a2@t.com', 'pass', role=User.Roles.AUDITOR,
            manager=self.manager)
        self.restaurant_user = User.objects.create_user(
            'ru2', 'r2@t.com', 'pass', role=User.Roles.RESTAURANT_USER)
        self.restaurant_user.restaurants.add(self.restaurant)
        self.template = AuditTemplate.objects.create(name='T')
        self.audit = Audit.objects.create(
            template=self.template, restaurant=self.restaurant,
            audit_date='2026-06-15', manager_on_duty='M', auditor=self.auditor,
        )

    def test_ca_creates_notification_for_restaurant_users_and_manager(self):
        ca = CorrectiveAction.objects.create(
            audit=self.audit, restaurant=self.restaurant,
            description='Test CA',
            risk_level=CorrectiveAction.RiskLevel.HIGH,
            deadline=timezone.now().date() + timezone.timedelta(days=7),
        )
        recipients = set(Notification.objects.values_list('recipient_id', flat=True))
        self.assertIn(self.restaurant_user.pk, recipients)
        self.assertIn(self.manager.pk, recipients)
        n = Notification.objects.filter(recipient=self.restaurant_user).first()
        self.assertIsNotNone(n)
        self.assertEqual(n.notification_type, Notification.Type.CA_CREATED)
        self.assertIn('R.', n.message)

    def test_ca_created_notification_has_link(self):
        ca = CorrectiveAction.objects.create(
            audit=self.audit, restaurant=self.restaurant,
            description='Test CA',
            risk_level=CorrectiveAction.RiskLevel.LOW,
            deadline=timezone.now().date() + timezone.timedelta(days=30),
        )
        n = Notification.objects.filter(recipient=self.restaurant_user).first()
        self.assertIn(str(ca.pk), n.link)

    def test_ca_created_notification_not_fired_on_update(self):
        ca = CorrectiveAction.objects.create(
            audit=self.audit, restaurant=self.restaurant,
            description='Initial',
            risk_level=CorrectiveAction.RiskLevel.LOW,
            deadline=timezone.now().date() + timezone.timedelta(days=30),
        )
        count_after_create = Notification.objects.count()
        ca.description = 'Updated'
        ca.save()
        self.assertEqual(Notification.objects.count(), count_after_create)


class AuditSubmittedNotificationTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name='Test')
        self.restaurant = Restaurant.objects.create(
            code='1270300', name='R', city='C', address='A', region=self.region)
        self.manager = User.objects.create_user(
            'mgr3', 'm3@t.com', 'pass', role=User.Roles.MANAGER)
        self.auditor = User.objects.create_user(
            'aud3', 'a3@t.com', 'pass', role=User.Roles.AUDITOR,
            manager=self.manager)
        self.restaurant_user = User.objects.create_user(
            'ru3', 'r3@t.com', 'pass', role=User.Roles.RESTAURANT_USER)
        self.restaurant_user.restaurants.add(self.restaurant)
        self.template = AuditTemplate.objects.create(name='T')
        self.section = Section.objects.create(
            template=self.template, name='S', order=1)
        Question.objects.create(
            section=self.section, question_text='Q', possible_points=10, order=1)
        self.audit = Audit.objects.create(
            template=self.template, restaurant=self.restaurant,
            audit_date='2026-06-15', manager_on_duty='M', auditor=self.auditor,
        )
        audit_section = AuditSection.objects.create(
            audit=self.audit, section=self.section, possible_points=10)
        AuditQuestionResponse.objects.create(
            audit_section=audit_section, question=Question.objects.first(),
            is_answered=True, scored_points=10)

        # Assign permissions
        content_type = ContentType.objects.get_for_model(Audit)
        change_perm = Permission.objects.get(
            content_type=content_type, codename='change_audit')
        view_perm = Permission.objects.get(
            content_type=content_type, codename='view_audit')
        self.auditor.user_permissions.add(change_perm, view_perm)
        self.client.force_login(self.auditor)

    def test_audit_submit_json_creates_notifications(self):
        resp = self.client.post(
            reverse('audits:submit_json', args=[self.audit.pk]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(resp.status_code, 200)
        # Should notify restaurant users + auditor + auditor's manager
        recipients = set(Notification.objects.values_list('recipient_id', flat=True))
        self.assertIn(self.restaurant_user.pk, recipients)
        self.assertIn(self.auditor.pk, recipients)
        self.assertIn(self.manager.pk, recipients)
        n = Notification.objects.filter(recipient=self.restaurant_user).first()
        self.assertEqual(n.notification_type, Notification.Type.AUDIT_SUBMITTED)
        self.assertIn('100.0%', n.message)


class CANotificationFlowTest(TestCase):
    """Tests that CA state transitions produce the right notifications."""

    def setUp(self):
        self.region = Region.objects.create(name='Test')
        self.restaurant = Restaurant.objects.create(
            code='1270400', name='R', city='C', address='A', region=self.region)
        self.manager = User.objects.create_user(
            'mgr4', 'm4@t.com', 'pass', role=User.Roles.MANAGER)
        self.auditor = User.objects.create_user(
            'aud4', 'a4@t.com', 'pass', role=User.Roles.AUDITOR,
            manager=self.manager)
        self.ru = User.objects.create_user(
            'ru4', 'r4@t.com', 'pass', role=User.Roles.RESTAURANT_USER)
        self.ru.restaurants.add(self.restaurant)
        self.template = AuditTemplate.objects.create(name='T')
        self.audit = Audit.objects.create(
            template=self.template, restaurant=self.restaurant,
            audit_date='2026-06-15', manager_on_duty='M', auditor=self.auditor,
        )
        # Auditor needs the restaurant assigned so CA visible_to works (checks restaurant__in)
        self.auditor.restaurants.add(self.restaurant)
        self.ca = CorrectiveAction.objects.create(
            audit=self.audit, restaurant=self.restaurant,
            description='Test CA',
            risk_level=CorrectiveAction.RiskLevel.HIGH,
            assigned_to=self.ru,
            deadline=timezone.now().date() + timezone.timedelta(days=7),
        )
        # Clear notifications created by the CA creation signal
        Notification.objects.all().delete()

        # Assign permissions
        ca_ct = ContentType.objects.get_for_model(CorrectiveAction)
        change_ca = Permission.objects.get(
            content_type=ca_ct, codename='change_correctiveaction')
        view_ca = Permission.objects.get(
            content_type=ca_ct, codename='view_correctiveaction')
        audit_ct = ContentType.objects.get_for_model(Audit)
        view_audit = Permission.objects.get(
            content_type=audit_ct, codename='view_audit')
        self.auditor.user_permissions.add(change_ca, view_ca, view_audit)
        self.ru.user_permissions.add(change_ca, view_ca, view_audit)

    def test_ca_complete_notifies_auditor_and_manager(self):
        self.ca.status = CorrectiveAction.Status.OPEN
        self.ca.save()
        self.client.force_login(self.ru)
        resp = self.client.post(
            reverse('audits:corrective_action_complete', args=[self.ca.pk]))
        self.assertRedirects(resp, reverse('audits:corrective_actions'))
        recipients = set(Notification.objects.values_list('recipient_id', flat=True))
        self.assertIn(self.auditor.pk, recipients)
        self.assertIn(self.manager.pk, recipients)

    def test_ca_verify_notifies_restaurant_users_and_manager(self):
        self.ca.status = CorrectiveAction.Status.COMPLETED
        self.ca.save()
        self.client.force_login(self.auditor)
        resp = self.client.post(
            reverse('audits:corrective_action_verify', args=[self.ca.pk]))
        self.assertRedirects(resp, reverse('audits:corrective_actions'))
        recipients = set(Notification.objects.values_list('recipient_id', flat=True))
        self.assertIn(self.ru.pk, recipients)
        self.assertIn(self.manager.pk, recipients)
        n = Notification.objects.filter(recipient=self.ru).first()
        self.assertEqual(n.notification_type, Notification.Type.CA_VERIFIED)

    def test_ca_close_notifies_restaurant_users_auditor_and_manager(self):
        self.ca.status = CorrectiveAction.Status.VERIFIED
        self.ca.save()
        self.client.force_login(self.auditor)
        resp = self.client.post(
            reverse('audits:corrective_action_close', args=[self.ca.pk]))
        self.assertRedirects(resp, reverse('audits:corrective_actions'))
        recipients = set(Notification.objects.values_list('recipient_id', flat=True))
        self.assertIn(self.ru.pk, recipients)
        self.assertIn(self.auditor.pk, recipients)
        self.assertIn(self.manager.pk, recipients)
        n = Notification.objects.filter(recipient=self.ru).first()
        self.assertEqual(n.notification_type, Notification.Type.CA_CLOSED)


class NotificationViewsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', 'u@t.com', 'pass')
        self.other = User.objects.create_user('other', 'o@t.com', 'pass')
        self.client.force_login(self.user)
        for i in range(3):
            Notification.objects.create(
                recipient=self.user if i < 2 else self.other,
                notification_type=Notification.Type.AUDIT_SUBMITTED,
                title=f'Notif {i}', message=f'Msg {i}', link='/',
            )

    def test_list_shows_only_user_notifications(self):
        resp = self.client.get(reverse('core:notifications'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context['notifications']), 2)

    def test_list_shows_unread_count(self):
        resp = self.client.get(reverse('core:notifications'))
        self.assertEqual(resp.context['unread_count'], 2)

    def test_mark_read_updates_is_read(self):
        n = Notification.objects.filter(recipient=self.user).first()
        resp = self.client.post(
            reverse('core:notification_read', args=[n.pk]))
        n.refresh_from_db()
        self.assertTrue(n.is_read)

    def test_mark_read_redirects_to_link(self):
        n = Notification.objects.filter(recipient=self.user).first()
        n.link = '/'
        n.save()
        resp = self.client.post(
            reverse('core:notification_read', args=[n.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, '/')

    def test_mark_read_ajax_returns_json(self):
        n = Notification.objects.filter(recipient=self.user).first()
        resp = self.client.post(
            reverse('core:notification_read', args=[n.pk]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'ok': True})

    def test_mark_read_other_users_notification_404(self):
        n = Notification.objects.filter(recipient=self.other).first()
        resp = self.client.post(
            reverse('core:notification_read', args=[n.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_mark_all_read(self):
        resp = self.client.post(reverse('core:notification_read_all'))
        self.assertRedirects(resp, reverse('core:notifications'))
        self.assertEqual(
            Notification.objects.filter(recipient=self.user, is_read=False).count(),
            0,
        )

    def test_mark_all_read_ajax_returns_json(self):
        resp = self.client.post(
            reverse('core:notification_read_all'),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'ok': True})

    def test_count_view(self):
        resp = self.client.get(reverse('core:notification_count'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'count': 2})

    def test_count_view_after_read(self):
        n = Notification.objects.filter(recipient=self.user).first()
        self.client.post(reverse('core:notification_read', args=[n.pk]))
        resp = self.client.get(reverse('core:notification_count'))
        self.assertEqual(resp.json(), {'count': 1})
