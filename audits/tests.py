from decimal import Decimal
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from restaurants.models import Restaurant, Region
from audits.models import (
    AuditTemplate, Section, Question,
    Audit, AuditSection, AuditQuestionResponse,
    CorrectiveAction,
)


# -----------------------------
# Template / Section / Question
# -----------------------------

class TemplateModelTest(TestCase):
    def test_create_template(self):
        t = AuditTemplate.objects.create(name='Q4 Audit', version='2.0')
        self.assertEqual(str(t), 'Q4 Audit (v2.0)')
        self.assertTrue(t.is_active)

    def test_template_ordering(self):
        AuditTemplate.objects.create(name='B')
        AuditTemplate.objects.create(name='A')
        names = list(AuditTemplate.objects.values_list('name', flat=True))
        self.assertEqual(names, ['A', 'B'])


class SectionModelTest(TestCase):
    def setUp(self):
        self.template = AuditTemplate.objects.create(name='Test')

    def test_create_section(self):
        s = Section.objects.create(
            template=self.template, name='Kitchen', order=1)
        self.assertEqual(str(s), 'Kitchen (Template: Test)')

    def test_unique_order_per_template(self):
        Section.objects.create(template=self.template, name='S1', order=1)
        with self.assertRaises(Exception):
            Section.objects.create(template=self.template, name='S2', order=1)

    def test_ordering(self):
        Section.objects.create(template=self.template, name='Z', order=2)
        Section.objects.create(template=self.template, name='A', order=1)
        names = [s.name for s in self.template.sections.all()]
        self.assertEqual(names, ['A', 'Z'])


class QuestionModelTest(TestCase):
    def setUp(self):
        self.template = AuditTemplate.objects.create(name='Test')
        self.section = Section.objects.create(
            template=self.template, name='Kitchen', order=1)

    def test_create_question(self):
        q = Question.objects.create(
            section=self.section,
            question_text='Is the grill clean?',
            possible_points=5,
            order=1,
        )
        self.assertIn('Is the grill clean?', str(q))

    def test_critical_requires_condition(self):
        with self.assertRaises(Exception):
            Question.objects.create(
                section=self.section,
                question_text='Critical?',
                possible_points=5,
                is_critical=True,
                critical_failure_condition='',
                order=1,
            )


# -----------------------------
# Audit Execution
# -----------------------------

class AuditModelTest(TestCase):
    def setUp(self):
        self.template = AuditTemplate.objects.create(name='Test Template')
        self.section = Section.objects.create(
            template=self.template, name='Kitchen', order=1)
        self.q1 = Question.objects.create(
            section=self.section, question_text='Clean grill?',
            possible_points=5, order=1)
        self.q2 = Question.objects.create(
            section=self.section, question_text='Proper oil?',
            possible_points=5, order=2, is_critical=True,
            critical_failure_condition='Oil level below min')
        self.region = Region.objects.create(name='Test')
        self.restaurant = Restaurant.objects.create(
            code='1270001', name='Test Restaurant',
            city='City', address='Addr', region=self.region)
        self.user = User.objects.create_user('aud', 'a@t.com', 'pass')

    def _create_audit(self):
        return Audit.objects.create(
            template=self.template,
            restaurant=self.restaurant,
            audit_date='2026-06-15',
            manager_on_duty='Ali',
            auditor=self.user,
        )

    def test_create_audit(self):
        audit = self._create_audit()
        self.assertEqual(str(audit), 'Test Restaurant - 2026-06-15')
        self.assertFalse(audit.is_submitted)
        self.assertEqual(audit.grade, '')

    def test_audit_str(self):
        audit = self._create_audit()
        self.assertIn('Test Restaurant', str(audit))

    def test_submission_sets_submitted_at(self):
        audit = self._create_audit()
        self.assertIsNone(audit.submitted_at)
        audit.is_submitted = True
        audit.save()
        self.assertIsNotNone(audit.submitted_at)


class AuditSectionsAutoGenerationTest(TestCase):
    def setUp(self):
        self.template = AuditTemplate.objects.create(name='T')
        self.s1 = Section.objects.create(
            template=self.template, name='S1', order=1)
        self.s2 = Section.objects.create(
            template=self.template, name='S2', order=2)
        Question.objects.create(
            section=self.s1, question_text='Q1', possible_points=5, order=1)
        Question.objects.create(
            section=self.s1, question_text='Q2', possible_points=10, order=2)
        Question.objects.create(
            section=self.s2, question_text='Q3', possible_points=3, order=1)
        self.restaurant = Restaurant.objects.create(
            code='1270002', name='R', city='C', address='A')
        self.user = User.objects.create_user('u', 'u@t.com', 'pass')
        self.audit = Audit.objects.create(
            template=self.template, restaurant=self.restaurant,
            audit_date='2026-06-15', manager_on_duty='M', auditor=self.user,
        )

        from audits.models import AuditSection, AuditQuestionResponse
        sections = self.audit.template.sections.all().prefetch_related('questions')
        for section in sections:
            audit_section = AuditSection.objects.create(
                audit=self.audit, section=section,
                possible_points=sum(
                    q.possible_points for q in section.questions.all()),
            )
            for question in section.questions.all():
                AuditQuestionResponse.objects.create(
                    audit_section=audit_section, question=question,
                    is_answered=True)

    def test_sections_created(self):
        self.assertEqual(self.audit.audit_sections.count(), 2)

    def test_responses_created(self):
        total = sum(
            s.responses.count() for s in self.audit.audit_sections.all())
        self.assertEqual(total, 3)

    def test_possible_points_set(self):
        s1 = self.audit.audit_sections.get(section=self.s1)
        self.assertEqual(s1.possible_points, 15)


class ScoringAndGradeTest(TestCase):
    def setUp(self):
        self.template = AuditTemplate.objects.create(name='T')
        self.section = Section.objects.create(
            template=self.template, name='S', order=1)
        self.q1 = Question.objects.create(
            section=self.section, question_text='Q1',
            possible_points=10, order=1)
        self.q2 = Question.objects.create(
            section=self.section, question_text='Q2',
            possible_points=10, order=2)
        self.restaurant = Restaurant.objects.create(
            code='1270003', name='R', city='C', address='A')
        self.user = User.objects.create_user('u', 'u@t.com', 'pass')
        self.audit = Audit.objects.create(
            template=self.template, restaurant=self.restaurant,
            audit_date='2026-06-15', manager_on_duty='M', auditor=self.user,
        )
        self.audit_section = AuditSection.objects.create(
            audit=self.audit, section=self.section, possible_points=20)
        self.resp1 = AuditQuestionResponse.objects.create(
            audit_section=self.audit_section, question=self.q1,
            is_answered=True)
        self.resp2 = AuditQuestionResponse.objects.create(
            audit_section=self.audit_section, question=self.q2,
            is_answered=True)

    def test_perfect_score_grade_a(self):
        self.resp1.scored_points = 10
        self.resp1.save()
        self.resp2.scored_points = 10
        self.resp2.save()

        self.audit.refresh_from_db()
        self.assertEqual(self.audit.total_scored, 20)
        self.assertEqual(self.audit.total_possible, 20)
        self.assertEqual(self.audit.grade, 'A')

    def test_partial_score_grade_b(self):
        self.resp1.scored_points = 10
        self.resp1.save()
        self.resp2.scored_points = 8
        self.resp2.save()

        self.audit.refresh_from_db()
        self.assertEqual(self.audit.grade, 'B')

    def test_partial_score_grade_c(self):
        self.resp1.scored_points = 8
        self.resp1.save()
        self.resp2.scored_points = 8
        self.resp2.save()

        self.audit.refresh_from_db()
        self.assertEqual(self.audit.grade, 'C')

    def test_poor_score_grade_f(self):
        self.resp1.scored_points = 5
        self.resp1.save()
        self.resp2.scored_points = 5
        self.resp2.save()

        self.audit.refresh_from_db()
        self.assertEqual(self.audit.grade, 'F')

    def test_critical_failure_forces_f(self):
        self.q2.is_critical = True
        self.q2.critical_failure_condition = 'Test'
        self.q2.save()

        self.resp1.scored_points = 10
        self.resp1.save()
        self.resp2.scored_points = 0
        self.resp2.save()

        self.audit.refresh_from_db()
        self.assertTrue(self.audit.has_critical_failure)
        self.assertEqual(self.audit.grade, 'F')

    def test_na_excluded_from_scoring(self):
        self.resp1.is_na = True
        self.resp1.scored_points = 0
        self.resp1.save()
        self.resp2.scored_points = 10
        self.resp2.save()

        self.audit.refresh_from_db()
        self.assertEqual(self.audit.total_possible, 10)
        self.assertEqual(self.audit.total_scored, 10)
        self.assertEqual(self.audit.grade, 'A')

    def test_scored_points_clamped(self):
        self.resp1.scored_points = 999
        self.resp1.save()
        self.resp1.refresh_from_db()
        self.assertEqual(self.resp1.scored_points, 10)


class CorrectiveActionModelTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name='R')
        self.restaurant = Restaurant.objects.create(
            code='1270004', name='R', city='C', address='A')
        self.user = User.objects.create_user('u', 'u@t.com', 'pass')
        self.template = AuditTemplate.objects.create(name='T')
        self.section = Section.objects.create(
            template=self.template, name='S', order=1)
        self.q = Question.objects.create(
            section=self.section, question_text='Q', possible_points=5, order=1)
        self.audit = Audit.objects.create(
            template=self.template, restaurant=self.restaurant,
            audit_date='2026-06-15', manager_on_duty='M', auditor=self.user,
        )
        self.audit_section = AuditSection.objects.create(
            audit=self.audit, section=self.section, possible_points=5)
        self.resp = AuditQuestionResponse.objects.create(
            audit_section=self.audit_section, question=self.q,
            is_answered=True)

    def test_create_corrective_action(self):
        assignee = User.objects.create_user('john', 'john@t.com', 'pass')
        ca = CorrectiveAction.objects.create(
            audit=self.audit, restaurant=self.restaurant,
            question_response=self.resp,
            description='Fix grill', risk_level=CorrectiveAction.RiskLevel.HIGH,
            assigned_to=assignee, deadline='2026-07-01',
        )
        self.assertIn('Fix grill', str(ca.description))

    def test_is_overdue(self):
        assignee = User.objects.create_user('jane', 'jane@t.com', 'pass')
        ca = CorrectiveAction.objects.create(
            audit=self.audit, restaurant=self.restaurant,
            question_response=self.resp,
            description='Fix', risk_level=CorrectiveAction.RiskLevel.LOW,
            assigned_to=assignee, deadline=date.today() - timedelta(days=1),
        )
        self.assertTrue(ca.is_overdue)
        self.assertEqual(ca.days_remaining, -1)

    def test_not_overdue_when_completed(self):
        assignee = User.objects.create_user('bob', 'bob@t.com', 'pass')
        ca = CorrectiveAction.objects.create(
            audit=self.audit, restaurant=self.restaurant,
            question_response=self.resp,
            description='Fix', risk_level=CorrectiveAction.RiskLevel.LOW,
            assigned_to=assignee, deadline=date.today() - timedelta(days=1),
            status=CorrectiveAction.Status.COMPLETED, completion_date=date.today(),
        )
        self.assertFalse(ca.is_overdue)
        self.assertIsNone(ca.days_remaining)


# -----------------------------------------------------------
# CorrectiveAction.transition_to state machine + clean() rules
# -----------------------------------------------------------

class CorrectiveActionTransitionTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name='R')
        self.restaurant = Restaurant.objects.create(
            code='1270006', name='Trans R', city='C', address='A',
            region=self.region)
        self.template = AuditTemplate.objects.create(name='T')
        self.section = Section.objects.create(
            template=self.template, name='S', order=1)
        self.q = Question.objects.create(
            section=self.section, question_text='Q',
            possible_points=5, order=1)
        self.audit = Audit.objects.create(
            template=self.template, restaurant=self.restaurant,
            audit_date='2026-06-15', manager_on_duty='M')
        self.audit_section = AuditSection.objects.create(
            audit=self.audit, section=self.section, possible_points=5)
        self.resp = AuditQuestionResponse.objects.create(
            audit_section=self.audit_section, question=self.q, is_answered=True)

        ct_ca = ContentType.objects.get_for_model(CorrectiveAction)
        self.approver = User.objects.create_user('appr', 'appr@t.com', 'pass')
        self.approver.role = User.Roles.AUDITOR
        self.approver.save()
        self.approver.restaurants.add(self.restaurant)
        self.approver.user_permissions.add(
            *Permission.objects.filter(content_type=ct_ca))

        self.ru = User.objects.create_user('tru', 'tru@t.com', 'pass')
        self.ru.role = User.Roles.RESTAURANT_USER
        self.ru.save()
        self.ru.restaurants.add(self.restaurant)
        self.ru.user_permissions.add(
            *Permission.objects.filter(
                content_type=ct_ca,
                codename__in=['view_correctiveaction', 'change_correctiveaction']))

        self.ca = CorrectiveAction.objects.create(
            audit=self.audit, restaurant=self.restaurant,
            question_response=self.resp, description='Fix',
            risk_level=CorrectiveAction.RiskLevel.HIGH,
            deadline=date.today() + timedelta(days=30))

    def test_full_forward_flow(self):
        ca = self.ca
        ca.transition_to(ca.Status.IN_PROGRESS, self.approver)
        ca.transition_to(ca.Status.COMPLETED, self.approver)
        ca.transition_to(ca.Status.VERIFIED, self.approver)
        ca.transition_to(ca.Status.CLOSED, self.approver)
        ca.save()
        self.assertEqual(ca.status, ca.Status.CLOSED)

    def test_invalid_forward_transition_raises(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.ca.transition_to(self.ca.Status.CLOSED, self.approver)

    def test_verified_requires_verify_permission(self):
        from django.core.exceptions import ValidationError
        self.ca.status = self.ca.Status.COMPLETED
        self.ca.save()
        with self.assertRaises(ValidationError):
            self.ca.transition_to(self.ca.Status.VERIFIED, self.ru)

    def test_reopen_requires_verify_permission(self):
        from django.core.exceptions import ValidationError
        self.ca.status = self.ca.Status.COMPLETED
        self.ca.save()
        with self.assertRaises(ValidationError):
            self.ca.transition_to(self.ca.Status.OPEN, self.ru)

    def test_reopen_resets_escalation_sent_at(self):
        self.ca.status = self.ca.Status.COMPLETED
        self.ca.escalation_sent_at = timezone.now()
        self.ca.save()
        self.ca.transition_to(self.ca.Status.OPEN, self.approver)
        self.assertIsNone(self.ca.escalation_sent_at)

    def test_same_status_is_noop(self):
        previous = self.ca.transition_to(self.ca.Status.OPEN, self.approver)
        self.assertEqual(previous, self.ca.Status.OPEN)
        self.assertEqual(self.ca.status, self.ca.Status.OPEN)

    def test_clean_rejects_question_response_from_other_audit(self):
        from django.core.exceptions import ValidationError
        other_restaurant = Restaurant.objects.create(
            code='1270007', name='Other', city='C', address='A')
        other_audit = Audit.objects.create(
            template=self.template, restaurant=other_restaurant,
            audit_date='2026-06-20', manager_on_duty='M')
        other_section = AuditSection.objects.create(
            audit=other_audit, section=self.section, possible_points=5)
        other_resp = AuditQuestionResponse.objects.create(
            audit_section=other_section, question=self.q, is_answered=True)
        self.ca.question_response = other_resp
        with self.assertRaises(ValidationError):
            self.ca.full_clean()

    def test_clean_rejects_restaurant_mismatch(self):
        from django.core.exceptions import ValidationError
        other_restaurant = Restaurant.objects.create(
            code='1270008', name='Other R', city='C', address='A')
        self.ca.restaurant = other_restaurant
        with self.assertRaises(ValidationError):
            self.ca.full_clean()

    def test_clean_rejects_assignee_outside_restaurant(self):
        from django.core.exceptions import ValidationError
        self.ca.assigned_to = self.approver
        with self.assertRaises(ValidationError):
            self.ca.full_clean()

    def test_clean_accepts_restaurant_user_assignee(self):
        self.ca.assigned_to = self.ru
        self.ca.full_clean()  # should not raise

    def test_form_assignee_queryset_scoped_to_restaurant_users(self):
        from audits.forms import CorrectiveActionForm
        form = CorrectiveActionForm(
            data={'audit': self.audit.pk}, user=self.approver)
        self.assertEqual(set(form.fields['assigned_to'].queryset), {self.ru})

    def test_form_rejects_assignee_outside_restaurant(self):
        from audits.forms import CorrectiveActionForm
        form = CorrectiveActionForm(
            data={
                'audit': self.audit.pk,
                'question_response': self.resp.pk,
                'description': 'Fix',
                'risk_level': 'HIGH',
                'status': 'OPEN',
                'deadline': date.today() + timedelta(days=5),
                'comments': '',
                'evidence_image': '',
                'assigned_to': self.approver.pk,
            },
            instance=CorrectiveAction(
                audit=self.audit, restaurant=self.restaurant),
            user=self.approver,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('assigned_to', form.errors)


# -----------------------------------------------------------
# Overdue escalation command (throttled by escalation_sent_at)
# -----------------------------------------------------------

class EscalateOverdueCommandTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name='R')
        self.restaurant = Restaurant.objects.create(
            code='1270009', name='Esc R', city='C', address='A',
            region=self.region)
        self.auditor = User.objects.create_user('esca', 'esca@t.com', 'pass')
        self.auditor.role = User.Roles.AUDITOR
        self.auditor.save()
        self.auditor.restaurants.add(self.restaurant)
        self.manager = User.objects.create_user('escm', 'escm@t.com', 'pass')
        self.manager.role = User.Roles.MANAGER
        self.manager.save()
        self.auditor.manager = self.manager
        self.auditor.save()
        self.ru = User.objects.create_user('escu', 'escu@t.com', 'pass')
        self.ru.role = User.Roles.RESTAURANT_USER
        self.ru.save()
        self.ru.restaurants.add(self.restaurant)

        self.template = AuditTemplate.objects.create(name='T')
        self.audit = Audit.objects.create(
            template=self.template, restaurant=self.restaurant,
            audit_date='2026-06-15', manager_on_duty='M', auditor=self.auditor)
        self.ca = CorrectiveAction.objects.create(
            audit=self.audit, restaurant=self.restaurant,
            description='Escalate me', risk_level=CorrectiveAction.RiskLevel.HIGH,
            deadline=date.today() - timedelta(days=10))

    def _run(self):
        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        call_command('escalate_overdue_cas', stdout=out)
        return out.getvalue()

    def test_escalates_and_stamps_marker(self):
        from core.models import Notification
        self._run()
        self.ca.refresh_from_db()
        self.assertIsNotNone(self.ca.escalation_sent_at)
        self.assertTrue(
            Notification.objects.filter(
                notification_type=Notification.Type.CA_ESCALATED).exists())

    def test_does_not_re_escalate_within_window(self):
        from core.models import Notification
        self._run()
        first = Notification.objects.filter(
            notification_type=Notification.Type.CA_ESCALATED).count()
        self.assertGreater(first, 0)
        self._run()
        second = Notification.objects.filter(
            notification_type=Notification.Type.CA_ESCALATED).count()
        self.assertEqual(first, second)

    def test_skips_when_already_escalated_recently(self):
        from core.models import Notification
        self.ca.escalation_sent_at = timezone.now()
        self.ca.save(update_fields=['escalation_sent_at'])
        self._run()
        self.assertEqual(
            Notification.objects.filter(
                notification_type=Notification.Type.CA_ESCALATED).count(), 0)

    def test_reescalates_after_reminder_window(self):
        from core.models import Notification
        self.ca.escalation_sent_at = timezone.now() - timedelta(days=8)
        self.ca.save(update_fields=['escalation_sent_at'])
        self._run()
        self.assertGreater(
            Notification.objects.filter(
                notification_type=Notification.Type.CA_ESCALATED).count(), 0)


class AuditViewTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('auditor1', 'a@t.com', 'pass')
        self.user.role = User.Roles.AUDITOR
        manager = User.objects.create_user('mgr', 'm@t.com', 'pass')
        manager.role = User.Roles.MANAGER
        manager.save()
        self.user.manager = manager
        self.user.save()

        # Assign all audit permissions
        ct = ContentType.objects.get_for_model(Audit)
        perms = Permission.objects.filter(content_type=ct)
        self.user.user_permissions.add(*perms)

        # Assign correctiveaction permissions
        ct_ca = ContentType.objects.get_for_model(CorrectiveAction)
        perms_ca = Permission.objects.filter(content_type=ct_ca)
        self.user.user_permissions.add(*perms_ca)

        # Assign auditquestionresponse permissions
        ct_aqr = ContentType.objects.get_for_model(AuditQuestionResponse)
        perms_aqr = Permission.objects.filter(content_type=ct_aqr)
        self.user.user_permissions.add(*perms_aqr)

        self.restaurant = Restaurant.objects.create(
            code='1270005', name='Test R', city='City', address='Addr')
        self.user.restaurants.add(self.restaurant)

        self.template = AuditTemplate.objects.create(name='T')
        self.section = Section.objects.create(
            template=self.template, name='S', order=1)
        Question.objects.create(
            section=self.section, question_text='Q',
            possible_points=5, order=1)

        self.audit = Audit.objects.create(
            template=self.template, restaurant=self.restaurant,
            audit_date='2026-06-15', manager_on_duty='M',
            auditor=self.user,
        )
        audit_section = AuditSection.objects.create(
            audit=self.audit, section=self.section, possible_points=5)
        self.resp = AuditQuestionResponse.objects.create(
            audit_section=audit_section, question=self.section.questions.first(),
            is_answered=True)

        self.client.force_login(self.user)

    def test_dashboard_loads(self):
        resp = self.client.get('/audits/dashboard/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Dashboard')

    def test_audit_list_loads(self):
        resp = self.client.get('/audits/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'audit')

    def test_audit_create_loads(self):
        resp = self.client.get('/audits/create/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'New Audit')

    def test_duplicate_audit_create_shows_modal(self):
        before = Audit.objects.count()
        resp = self.client.post('/audits/create/', {
            'template': self.template.pk,
            'restaurant': self.restaurant.pk,
            'audit_date': '2026-06-15',
            'manager_on_duty': 'M',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Audit Already Exists')
        self.assertEqual(Audit.objects.count(), before)

    def test_duplicate_archived_audit_allows_recreate(self):
        self.audit.is_archived = True
        self.audit.save()
        before = Audit.objects.count()
        resp = self.client.post('/audits/create/', {
            'template': self.template.pk,
            'restaurant': self.restaurant.pk,
            'audit_date': '2026-06-15',
            'manager_on_duty': 'M',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Audit.objects.count(), before + 1)

    def test_audit_detail_loads(self):
        resp = self.client.get(f'/audits/{self.audit.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Test R')

    def test_audit_score_loads(self):
        resp = self.client.get(f'/audits/{self.audit.pk}/score/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'jump-section')

    def test_audit_submit(self):
        resp = self.client.post(f'/audits/{self.audit.pk}/submit/', {})
        self.assertRedirects(resp, f'/audits/{self.audit.pk}/result/')
        self.audit.refresh_from_db()
        self.assertTrue(self.audit.is_submitted)

    def test_corrective_actions_list_loads(self):
        resp = self.client.get('/audits/corrective-actions/')
        self.assertEqual(resp.status_code, 200)

    def test_csv_export(self):
        resp = self.client.get('/audits/export/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/csv')
        self.assertIn('Restaurant', resp.content.decode())

    def test_scoping_non_superuser(self):
        other_restaurant = Restaurant.objects.create(
            code='9999999', name='Other', city='Other', address='Other')
        other_user = User.objects.create_user('other', 'o@t.com', 'pass')
        other_audit = Audit.objects.create(
            template=self.template, restaurant=other_restaurant,
            audit_date='2026-06-15', manager_on_duty='M',
            auditor=other_user,
        )
        resp = self.client.get('/audits/')
        self.assertContains(resp, 'Test R')
        self.assertNotContains(resp, 'Other')

    def test_admin_role_sees_all_restaurants(self):
        admin = User.objects.create_user('admin1', 'ad@t.com', 'pass')
        admin.role = User.Roles.ADMIN
        admin.save()
        ct = ContentType.objects.get_for_model(Audit)
        admin.user_permissions.add(
            Permission.objects.get(content_type=ct, codename='view_audit')
        )
        other_restaurant = Restaurant.objects.create(
            code='9999998', name='Admin Other', city='Other', address='Other')
        other_user = User.objects.create_user('other_admin', 'oa@t.com', 'pass')
        Audit.objects.create(
            template=self.template, restaurant=other_restaurant,
            audit_date='2026-06-15', manager_on_duty='M',
            auditor=other_user,
        )
        self.client.force_login(admin)
        resp = self.client.get('/audits/')
        self.assertContains(resp, 'Test R')
        self.assertContains(resp, 'Admin Other')

    def test_restaurant_user_cannot_see_draft_audits(self):
        ru = User.objects.create_user('ru_draft', 'rud@t.com', 'pass')
        ru.role = User.Roles.RESTAURANT_USER
        ru.save()
        ru.restaurants.add(self.restaurant)
        ct = ContentType.objects.get_for_model(Audit)
        ru.user_permissions.add(
            Permission.objects.get(content_type=ct, codename='view_audit')
        )
        self.client.force_login(ru)

        resp = self.client.get('/audits/')
        audit_pks = [a.pk for a in resp.context.get('audits', [])]
        self.assertNotIn(self.audit.pk, audit_pks)

        self.audit.is_submitted = True
        self.audit.save()
        resp = self.client.get('/audits/')
        audit_pks = [a.pk for a in resp.context.get('audits', [])]
        self.assertIn(self.audit.pk, audit_pks)

    def test_auditor_only_sees_own_audits(self):
        # An AUDITOR linked to a restaurant must NOT see audits conducted by
        # other auditors at that restaurant.
        auditor = User.objects.create_user('aud_only', 'ao@t.com', 'pass')
        auditor.role = User.Roles.AUDITOR
        auditor.save()
        auditor.restaurants.add(self.restaurant)
        ct = ContentType.objects.get_for_model(Audit)
        auditor.user_permissions.add(
            Permission.objects.get(content_type=ct, codename='view_audit')
        )
        own_audit = Audit.objects.create(
            template=self.template, restaurant=self.restaurant,
            audit_date='2026-06-14', manager_on_duty='M', auditor=auditor,
        )
        other_auditor = User.objects.create_user('other_aud', 'oth@t.com', 'pass')
        other_audit = Audit.objects.create(
            template=self.template, restaurant=self.restaurant,
            audit_date='2026-06-13', manager_on_duty='M', auditor=other_auditor,
        )
        self.client.force_login(auditor)
        resp = self.client.get('/audits/')
        audit_pks = [a.pk for a in resp.context.get('audits', [])]
        self.assertIn(own_audit.pk, audit_pks)
        self.assertNotIn(other_audit.pk, audit_pks)

    def test_manager_of_auditor_sees_draft_and_audit_responses(self):
        manager = self.user.manager
        ct = ContentType.objects.get_for_model(Audit)
        manager.user_permissions.add(
            Permission.objects.get(content_type=ct, codename='view_audit')
        )
        ct_aqr = ContentType.objects.get_for_model(AuditQuestionResponse)
        manager.user_permissions.add(
            *Permission.objects.filter(content_type=ct_aqr)
        )
        self.client.force_login(manager)

        resp = self.client.get('/audits/')
        audit_pks = [a.pk for a in resp.context.get('audits', [])]
        self.assertIn(self.audit.pk, audit_pks)

        resp = self.client.get(
            f'/audits/ajax/audit-responses/{self.audit.pk}/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data['responses']), 1)
        self.assertEqual(data['responses'][0]['id'], self.resp.pk)

    def test_audit_list_pagination_urlencodes_filter_values(self):
        # More than paginate_by (20) submitted audits matching the same filter
        # value containing special characters that must be URL-encoded.
        for i in range(22):
            Audit.objects.create(
                template=self.template, restaurant=self.restaurant,
                audit_date=date(2026, 5, 1) - timedelta(days=i),
                manager_on_duty='A&B M',
                auditor=self.user, is_submitted=True,
            )
        resp = self.client.get('/audits/?q=A%26B&status=submitted')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('A%26B', body)
        self.assertIn('page=2', body)
        # The raw ampersand must never be emitted inside the filter value
        self.assertNotIn('&q=A&B&', body)

    def test_audit_users_json(self):
        # Create a restaurant and a user assigned to it
        from django.contrib.auth import get_user_model
        from django.contrib.contenttypes.models import ContentType
        from django.contrib.auth.models import Permission
        User = get_user_model()

        # AuditUsersJSONView requires view_correctiveaction; grant it to self.user.
        ct_ca = ContentType.objects.get_for_model(CorrectiveAction)
        perm = Permission.objects.get(content_type=ct_ca, codename='view_correctiveaction')
        self.user.user_permissions.add(perm)

        user = User.objects.create_user('test_user', 'u@t.com', 'pass')
        restaurant = Restaurant.objects.create(name='Test Rest', code='1234567')
        user.restaurants.add(restaurant)
        # The view scopes results to restaurants the *requesting* user belongs to,
        # so self.user must also be linked to the new restaurant.
        self.user.restaurants.add(restaurant)
        audit = Audit.objects.create(
            restaurant=restaurant, auditor=self.user, template=self.template,
            audit_date='2026-06-15', manager_on_duty='M',
        )

        # Test endpoint
        resp = self.client.get(f'/audits/ajax/audit-users/{audit.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('users', resp.json())
        self.assertTrue(any(u['id'] == user.pk for u in resp.json()['users']))

    def test_audit_responses_json(self):
        resp = self.client.get(f'/audits/ajax/audit-responses/{self.audit.pk}/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('responses', data)
        self.assertEqual(len(data['responses']), 1)
        self.assertEqual(data['responses'][0]['id'], self.resp.pk)

    def test_audit_responses_json_requires_permission(self):
        other = User.objects.create_user('no_perm2', 'n2@t.com', 'pass')
        self.client.force_login(other)
        resp = self.client.get(f'/audits/ajax/audit-responses/{self.audit.pk}/')
        self.assertEqual(resp.status_code, 403)


class SuperuserViewTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            'admin', 'a@t.com', 'pass')
        self.restaurant = Restaurant.objects.create(
            code='1270006', name='Admin R', city='City', address='Addr')
        self.template = AuditTemplate.objects.create(name='T')
        self.audit = Audit.objects.create(
            template=self.template, restaurant=self.restaurant,
            audit_date='2026-06-15', manager_on_duty='M', auditor=self.admin,
        )
        self.client.force_login(self.admin)

    def test_superuser_sees_all_restaurants(self):
        other = Restaurant.objects.create(
            code='8888888', name='Hidden R', city='C', address='A')
        Audit.objects.create(
            template=self.template, restaurant=other,
            audit_date='2026-06-15', manager_on_duty='M', auditor=self.admin,
        )
        resp = self.client.get('/audits/')
        self.assertContains(resp, 'Admin R')
        self.assertContains(resp, 'Hidden R')


class TemplateViewTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', 'u@t.com', 'pass')
        ct = ContentType.objects.get_for_model(AuditTemplate)
        perms = Permission.objects.filter(content_type=ct)
        self.user.user_permissions.add(*perms)
        self.client.force_login(self.user)
        self.template = AuditTemplate.objects.create(
            name='Food Safety Check', description='A test template', version='1.0')
        self.section = Section.objects.create(
            template=self.template, name='Kitchen', order=1)
        Question.objects.create(section=self.section, question_text='Clean?',
                                possible_points=5, order=1, is_critical=True,
                                critical_failure_condition='Not clean')

    def test_template_list_loads(self):
        resp = self.client.get('/audits/templates/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Food Safety Check')

    def test_template_list_search(self):
        resp = self.client.get('/audits/templates/?q=Food')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Food Safety Check')
        resp = self.client.get('/audits/templates/?q=ZZZ')
        self.assertNotContains(resp, 'Food Safety Check')

    def test_template_detail_loads(self):
        resp = self.client.get(f'/audits/templates/{self.template.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Food Safety Check')
        self.assertContains(resp, 'Kitchen')
        self.assertContains(resp, 'Clean')

    def test_template_detail_404(self):
        resp = self.client.get('/audits/templates/999/')
        self.assertEqual(resp.status_code, 404)

    def test_template_list_requires_login(self):
        self.client.logout()
        resp = self.client.get('/audits/templates/')
        self.assertEqual(resp.status_code, 302)

    def test_template_detail_requires_permission(self):
        other = User.objects.create_user('no_perm', 'n@t.com', 'pass')
        self.client.force_login(other)
        resp = self.client.get(f'/audits/templates/{self.template.pk}/')
        self.assertEqual(resp.status_code, 403)


# -----------------------------------------------------------
# setup_groups management command
# -----------------------------------------------------------

class SetupGroupsCommandTest(TestCase):

    def _run_command(self):
        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        call_command('setup_groups', stdout=out)
        return out.getvalue()

    def test_creates_expected_groups(self):
        from django.contrib.auth.models import Group
        self._run_command()
        group_names = list(Group.objects.values_list('name', flat=True))
        self.assertIn('Manager', group_names)
        self.assertIn('Auditor', group_names)
        self.assertIn('Restaurant User', group_names)
        self.assertIn('Admin', group_names)

    def test_admin_group_has_view_audit_permission(self):
        from django.contrib.auth.models import Group
        from django.contrib.contenttypes.models import ContentType
        from django.contrib.auth.models import Permission
        self._run_command()
        group = Group.objects.get(name='Admin')
        ct = ContentType.objects.get_for_model(Audit)
        perm = Permission.objects.get(content_type=ct, codename='view_audit')
        self.assertIn(perm, group.permissions.all())

    def test_manager_has_view_audit_permission(self):
        from django.contrib.auth.models import Group
        from django.contrib.contenttypes.models import ContentType
        from django.contrib.auth.models import Permission
        self._run_command()
        group = Group.objects.get(name='Manager')
        ct = ContentType.objects.get_for_model(Audit)
        perm = Permission.objects.get(content_type=ct, codename='view_audit')
        self.assertIn(perm, group.permissions.all())

    def test_restaurant_user_cannot_add_audit(self):
        from django.contrib.auth.models import Group
        from django.contrib.contenttypes.models import ContentType
        from django.contrib.auth.models import Permission
        self._run_command()
        group = Group.objects.get(name='Restaurant User')
        ct = ContentType.objects.get_for_model(Audit)
        perm = Permission.objects.get(content_type=ct, codename='add_audit')
        self.assertNotIn(perm, group.permissions.all())

    def test_idempotent_multiple_runs(self):
        """Running the command twice must not duplicate groups or permissions."""
        from django.contrib.auth.models import Group
        self._run_command()
        self._run_command()
        self.assertEqual(Group.objects.filter(name='Manager').count(), 1)
        self.assertEqual(Group.objects.filter(name='Auditor').count(), 1)
        self.assertEqual(Group.objects.filter(name='Restaurant User').count(), 1)

    def test_auditor_has_full_corrective_action_permissions(self):
        from django.contrib.auth.models import Group
        from django.contrib.contenttypes.models import ContentType
        from django.contrib.auth.models import Permission
        self._run_command()
        group = Group.objects.get(name='Auditor')
        ct = ContentType.objects.get_for_model(CorrectiveAction)
        for action in ('view', 'add', 'change', 'verify'):
            perm = Permission.objects.get(
                content_type=ct, codename=f'{action}_correctiveaction')
            self.assertIn(perm, group.permissions.all(),
                          msg=f'Auditor missing {action}_correctiveaction')
        delete_perm = Permission.objects.get(
            content_type=ct, codename='delete_correctiveaction')
        self.assertNotIn(delete_perm, group.permissions.all(),
                         msg='Auditor should not be able to delete corrective actions')

    def test_manager_has_delete_and_verify_corrective_action_permissions(self):
        from django.contrib.auth.models import Group
        from django.contrib.contenttypes.models import ContentType
        from django.contrib.auth.models import Permission
        self._run_command()
        group = Group.objects.get(name='Manager')
        ct = ContentType.objects.get_for_model(CorrectiveAction)
        for action in ('delete', 'verify'):
            perm = Permission.objects.get(
                content_type=ct, codename=f'{action}_correctiveaction')
            self.assertIn(perm, group.permissions.all(),
                          msg=f'Manager missing {action}_correctiveaction')

    def test_restaurant_user_group_lacks_verify_permission(self):
        from django.contrib.auth.models import Group
        from django.contrib.contenttypes.models import ContentType
        from django.contrib.auth.models import Permission
        self._run_command()
        group = Group.objects.get(name='Restaurant User')
        ct = ContentType.objects.get_for_model(CorrectiveAction)
        verify_perm = Permission.objects.get(
            content_type=ct, codename='verify_correctiveaction')
        self.assertNotIn(verify_perm, group.permissions.all())


# -----------------------------------------------------------
# Verified/Closed corrective action workflow protection
# -----------------------------------------------------------

class CorrectiveActionWorkflowProtectionTest(TestCase):

    def setUp(self):
        self.region = Region.objects.create(name='R')
        self.restaurant = Restaurant.objects.create(
            code='9990001', name='WF Restaurant', city='C', address='A',
            region=self.region)

        # Auditor
        self.auditor = User.objects.create_user('wf_auditor', 'wa@t.com', 'pass')
        self.auditor.role = User.Roles.AUDITOR
        self.auditor.save()
        self.auditor.restaurants.add(self.restaurant)

        # Restaurant user
        self.ru = User.objects.create_user('wf_ru', 'wr@t.com', 'pass')
        self.ru.role = User.Roles.RESTAURANT_USER
        self.ru.save()
        self.ru.restaurants.add(self.restaurant)

        ct_ca = ContentType.objects.get_for_model(CorrectiveAction)
        auditor_perms = Permission.objects.filter(
            content_type=ct_ca, codename__in=[
                'view_correctiveaction', 'add_correctiveaction',
                'change_correctiveaction', 'verify_correctiveaction'])
        self.auditor.user_permissions.add(*auditor_perms)
        ru_perms = Permission.objects.filter(
            content_type=ct_ca, codename__in=[
                'view_correctiveaction', 'change_correctiveaction'])
        self.ru.user_permissions.add(*ru_perms)

        self.template = AuditTemplate.objects.create(name='WF T')
        self.section = Section.objects.create(
            template=self.template, name='S', order=1)
        q = Question.objects.create(
            section=self.section, question_text='Q',
            possible_points=5, order=1)

        ct_audit = ContentType.objects.get_for_model(Audit)
        self.auditor.user_permissions.add(
            *Permission.objects.filter(content_type=ct_audit))

        self.audit = Audit.objects.create(
            template=self.template, restaurant=self.restaurant,
            audit_date='2026-06-15', manager_on_duty='M', auditor=self.auditor,
        )
        audit_section = AuditSection.objects.create(
            audit=self.audit, section=self.section, possible_points=5)
        self.response = AuditQuestionResponse.objects.create(
            audit_section=audit_section, question=q, is_answered=True)

        from datetime import date, timedelta
        self.ca = CorrectiveAction.objects.create(
            audit=self.audit,
            restaurant=self.restaurant,
            question_response=self.response,
            description='Fix the issue',
            risk_level=CorrectiveAction.RiskLevel.LOW,
            assigned_to=self.ru,
            deadline=date.today() + timedelta(days=30),
        )

    def test_restaurant_user_cannot_edit_verified_ca(self):
        self.ca.status = CorrectiveAction.Status.VERIFIED
        self.ca.save()
        self.client.force_login(self.ru)
        url = reverse('audits:corrective_action_edit', args=[self.ca.pk])
        resp = self.client.get(url)
        # Should redirect away, not render the form
        self.assertEqual(resp.status_code, 302)

    def test_restaurant_user_cannot_edit_closed_ca(self):
        self.ca.status = CorrectiveAction.Status.CLOSED
        self.ca.save()
        self.client.force_login(self.ru)
        url = reverse('audits:corrective_action_edit', args=[self.ca.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)

    def test_auditor_can_edit_verified_ca(self):
        self.ca.status = CorrectiveAction.Status.VERIFIED
        self.ca.save()
        self.client.force_login(self.auditor)
        url = reverse('audits:corrective_action_edit', args=[self.ca.pk])
        resp = self.client.get(url)
        # Auditor is not blocked — should either render form or redirect to success
        self.assertNotEqual(resp.status_code, 403)

    def test_restaurant_user_cannot_complete_verified_ca(self):
        self.ca.status = CorrectiveAction.Status.VERIFIED
        self.ca.save()
        self.client.force_login(self.ru)
        url = f'/audits/corrective-actions/{self.ca.pk}/complete/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.ca.refresh_from_db()
        # Status must remain VERIFIED — not changed by restaurant user
        self.assertEqual(self.ca.status, CorrectiveAction.Status.VERIFIED)

    def test_restaurant_user_cannot_reopen_completed_ca(self):
        self.ca.status = CorrectiveAction.Status.COMPLETED
        self.ca.save()
        self.client.force_login(self.ru)
        url = f'/audits/corrective-actions/{self.ca.pk}/complete/'
        self.client.post(url)
        self.ca.refresh_from_db()
        self.assertEqual(self.ca.status, CorrectiveAction.Status.COMPLETED)

    def test_restaurant_user_status_field_is_editable_in_form(self):
        self.client.force_login(self.ru)
        url = reverse('audits:corrective_action_edit', args=[self.ca.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        # Status must not be disabled so the restaurant can mark complete.
        self.assertNotContains(resp, 'id="id_status" disabled')

    def test_restaurant_user_can_complete_open_ca_via_form(self):
        self.client.force_login(self.ru)
        url = reverse('audits:corrective_action_edit', args=[self.ca.pk])
        resp = self.client.post(url, {
            'status': CorrectiveAction.Status.COMPLETED,
            'deadline': self.ca.deadline.isoformat(),
        })
        self.assertEqual(resp.status_code, 302)
        self.ca.refresh_from_db()
        self.assertEqual(self.ca.status, CorrectiveAction.Status.COMPLETED)

    def test_restaurant_user_cannot_set_verified_via_form(self):
        self.client.force_login(self.ru)
        url = reverse('audits:corrective_action_edit', args=[self.ca.pk])
        resp = self.client.post(url, {
            'status': CorrectiveAction.Status.VERIFIED,
            'deadline': self.ca.deadline.isoformat(),
        })
        # Form re-rendered with a validation error, status unchanged.
        self.assertEqual(resp.status_code, 200)
        self.ca.refresh_from_db()
        self.assertEqual(self.ca.status, CorrectiveAction.Status.OPEN)

    def test_restaurant_user_cannot_reopen_completed_ca_via_form(self):
        self.ca.status = CorrectiveAction.Status.COMPLETED
        self.ca.save()
        self.client.force_login(self.ru)
        url = reverse('audits:corrective_action_edit', args=[self.ca.pk])
        resp = self.client.post(url, {
            'status': CorrectiveAction.Status.OPEN,
            'deadline': self.ca.deadline.isoformat(),
        })
        self.assertEqual(resp.status_code, 200)
        self.ca.refresh_from_db()
        self.assertEqual(self.ca.status, CorrectiveAction.Status.COMPLETED)

    def test_list_search_filters_by_description(self):
        self.client.force_login(self.auditor)
        resp = self.client.get('/audits/corrective-actions/', {'q': 'Fix the issue'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Fix the issue')
        resp = self.client.get('/audits/corrective-actions/', {'q': 'does-not-exist'})
        self.assertNotContains(resp, 'Fix the issue')

    def test_list_has_active_filters_context(self):
        self.client.force_login(self.auditor)
        resp = self.client.get('/audits/corrective-actions/')
        self.assertFalse(resp.context['has_active_filters'])
        resp = self.client.get('/audits/corrective-actions/', {'status': 'open'})
        self.assertFalse(resp.context['has_active_filters'])
        resp = self.client.get('/audits/corrective-actions/', {'risk': 'LOW'})
        self.assertTrue(resp.context['has_active_filters'])
        self.assertNotIn('page', resp.context['current_filters'])
        resp = self.client.get('/audits/corrective-actions/', {'page': '1', 'status': 'open'})
        self.assertNotIn('page', resp.context['current_filters'])


# -----------------------------------------------------------
# CorrectiveAction delete / verify / close permission rules
# -----------------------------------------------------------

class CorrectiveActionRoleRulesTest(TestCase):

    def setUp(self):
        self.region = Region.objects.create(name='R')
        self.restaurant = Restaurant.objects.create(
            code='9990002', name='Del CA R', city='C', address='A',
            region=self.region)

        self.manager = User.objects.create_user('mgr', 'm@t.com', 'pass')
        self.manager.role = User.Roles.MANAGER
        self.manager.save()

        self.auditor = User.objects.create_user('aud', 'ad@t.com', 'pass')
        self.auditor.role = User.Roles.AUDITOR
        self.auditor.manager = self.manager
        self.auditor.save()
        self.auditor.restaurants.add(self.restaurant)

        self.admin = User.objects.create_user('admin', 'adm@t.com', 'pass')
        self.admin.role = User.Roles.ADMIN
        self.admin.save()

        self.ru = User.objects.create_user('ru', 'ru@t.com', 'pass')
        self.ru.role = User.Roles.RESTAURANT_USER
        self.ru.save()
        self.ru.restaurants.add(self.restaurant)

        ct_ca = ContentType.objects.get_for_model(CorrectiveAction)
        perm_names = {
            'view_correctiveaction',
            'add_correctiveaction',
            'change_correctiveaction',
            'delete_correctiveaction',
            'verify_correctiveaction',
        }
        perms = {
            p.codename: p
            for p in Permission.objects.filter(content_type=ct_ca)
            if p.codename in perm_names
        }
        self.manager.user_permissions.add(
            perms['view_correctiveaction'], perms['add_correctiveaction'],
            perms['change_correctiveaction'], perms['delete_correctiveaction'],
            perms['verify_correctiveaction'])
        self.auditor.user_permissions.add(
            perms['view_correctiveaction'], perms['add_correctiveaction'],
            perms['change_correctiveaction'], perms['verify_correctiveaction'])
        self.admin.user_permissions.add(
            perms['view_correctiveaction'], perms['add_correctiveaction'],
            perms['change_correctiveaction'], perms['delete_correctiveaction'],
            perms['verify_correctiveaction'])
        self.ru.user_permissions.add(
            perms['view_correctiveaction'], perms['change_correctiveaction'])

        self.template = AuditTemplate.objects.create(name='T')
        self.section = Section.objects.create(
            template=self.template, name='S', order=1)
        Question.objects.create(
            section=self.section, question_text='Q',
            possible_points=5, order=1)
        self.audit = Audit.objects.create(
            template=self.template, restaurant=self.restaurant,
            audit_date='2026-06-15', manager_on_duty='M',
            auditor=self.auditor,
        )
        audit_section = AuditSection.objects.create(
            audit=self.audit, section=self.section, possible_points=5)
        self.response = AuditQuestionResponse.objects.create(
            audit_section=audit_section,
            question=self.section.questions.first(), is_answered=True)
        self.ca = CorrectiveAction.objects.create(
            audit=self.audit, restaurant=self.restaurant,
            question_response=self.response, description='Fix the issue',
            risk_level=CorrectiveAction.RiskLevel.LOW,
            assigned_to=self.ru,
            deadline=date.today() + timedelta(days=30),
        )

    def test_auditor_cannot_delete(self):
        self.client.force_login(self.auditor)
        self.client.post(f'/audits/corrective-actions/{self.ca.pk}/delete/')
        self.assertTrue(CorrectiveAction.objects.filter(pk=self.ca.pk).exists())

    def test_restaurant_user_cannot_delete(self):
        self.client.force_login(self.ru)
        self.client.post(f'/audits/corrective-actions/{self.ca.pk}/delete/')
        self.assertTrue(CorrectiveAction.objects.filter(pk=self.ca.pk).exists())

    def test_manager_can_delete(self):
        self.client.force_login(self.manager)
        self.client.post(f'/audits/corrective-actions/{self.ca.pk}/delete/')
        self.assertFalse(CorrectiveAction.objects.filter(pk=self.ca.pk).exists())

    def test_manager_cannot_delete_closed(self):
        self.ca.status = CorrectiveAction.Status.CLOSED
        self.ca.save()
        self.client.force_login(self.manager)
        self.client.post(f'/audits/corrective-actions/{self.ca.pk}/delete/')
        self.assertTrue(CorrectiveAction.objects.filter(pk=self.ca.pk).exists())

    def test_admin_role_can_delete_closed(self):
        self.ca.status = CorrectiveAction.Status.CLOSED
        self.ca.save()
        self.client.force_login(self.admin)
        self.client.post(f'/audits/corrective-actions/{self.ca.pk}/delete/')
        self.assertFalse(CorrectiveAction.objects.filter(pk=self.ca.pk).exists())

    def test_admin_role_can_verify(self):
        self.ca.status = CorrectiveAction.Status.COMPLETED
        self.ca.save()
        self.client.force_login(self.admin)
        self.client.post(f'/audits/corrective-actions/{self.ca.pk}/verify/')
        self.ca.refresh_from_db()
        self.assertEqual(self.ca.status, CorrectiveAction.Status.VERIFIED)

    def test_admin_role_can_close(self):
        self.ca.status = CorrectiveAction.Status.VERIFIED
        self.ca.save()
        self.client.force_login(self.admin)
        self.client.post(f'/audits/corrective-actions/{self.ca.pk}/close/')
        self.ca.refresh_from_db()
        self.assertEqual(self.ca.status, CorrectiveAction.Status.CLOSED)

    def test_auditor_can_reopen_completed_ca(self):
        self.ca.status = CorrectiveAction.Status.COMPLETED
        self.ca.save()
        self.client.force_login(self.auditor)
        self.client.post(f'/audits/corrective-actions/{self.ca.pk}/complete/')
        self.ca.refresh_from_db()
        self.assertEqual(self.ca.status, CorrectiveAction.Status.OPEN)

    def test_user_without_verify_perm_cannot_reopen(self):
        user = User.objects.create_user('noverify', 'nv@t.com', 'pass')
        user.role = User.Roles.AUDITOR
        user.save()
        user.restaurants.add(self.restaurant)
        ct_ca = ContentType.objects.get_for_model(CorrectiveAction)
        user.user_permissions.add(
            *Permission.objects.filter(
                content_type=ct_ca, codename__in=[
                    'view_correctiveaction', 'change_correctiveaction'])
        )

        self.ca.status = CorrectiveAction.Status.COMPLETED
        self.ca.save()
        self.client.force_login(user)
        self.client.post(f'/audits/corrective-actions/{self.ca.pk}/complete/')
        self.ca.refresh_from_db()
        self.assertEqual(self.ca.status, CorrectiveAction.Status.COMPLETED)


# -----------------------------------------------------------
# AuditDeleteView — soft-delete (archive) tests
# -----------------------------------------------------------

class AuditSoftDeleteTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('del_auditor', 'da@t.com', 'pass')
        self.user.role = User.Roles.AUDITOR
        self.user.save()

        self.restaurant = Restaurant.objects.create(
            code='8880001', name='Del R', city='C', address='A')
        self.user.restaurants.add(self.restaurant)

        ct = ContentType.objects.get_for_model(Audit)
        self.user.user_permissions.add(*Permission.objects.filter(content_type=ct))

        self.template = AuditTemplate.objects.create(name='Del T')
        self.audit = Audit.objects.create(
            template=self.template, restaurant=self.restaurant,
            audit_date='2026-06-15', manager_on_duty='M', auditor=self.user,
        )
        self.client.force_login(self.user)

    def test_delete_archives_audit_not_hard_deletes(self):
        pk = self.audit.pk
        self.client.post(f'/audits/{pk}/delete/')
        # Record must still exist in DB
        self.assertTrue(Audit.objects.filter(pk=pk).exists())
        self.audit.refresh_from_db()
        self.assertTrue(self.audit.is_archived)

    def test_submitted_audit_cannot_be_archived(self):
        self.audit.is_submitted = True
        self.audit.save()
        pk = self.audit.pk
        resp = self.client.post(f'/audits/{pk}/delete/')
        # Should redirect to detail, not archive
        self.assertRedirects(resp, f'/audits/{pk}/', fetch_redirect_response=False)
        self.audit.refresh_from_db()
        self.assertFalse(self.audit.is_archived)

    def test_archived_audit_not_visible_in_list(self):
        self.audit.is_archived = True
        self.audit.save()
        resp = self.client.get('/audits/')
        self.assertEqual(resp.status_code, 200)
        # The archived audit's pk should not appear in the queryset context
        audit_pks = [a.pk for a in resp.context.get('audits', [])]
        self.assertNotIn(self.audit.pk, audit_pks)


# -----------------------------------------------------------
# AJAX View Tests (SaveResponseView, FillRemainingView, AuditSubmitJSONView)
# -----------------------------------------------------------

class AJAXSaveResponseViewTest(TestCase):
    """Tests for SaveResponseView — the most frequently called AJAX endpoint."""

    def setUp(self):
        self.user = User.objects.create_user('ajax_user', 'a@t.com', 'pass')
        # Assign change_audit permission (needed by SaveResponseView)
        ct = ContentType.objects.get_for_model(Audit)
        for codename in ('change_audit', 'view_audit'):
            self.user.user_permissions.add(
                Permission.objects.get(content_type=ct, codename=codename)
            )
        ct_aqr = ContentType.objects.get_for_model(AuditQuestionResponse)
        self.user.user_permissions.add(
            *Permission.objects.filter(content_type=ct_aqr)
        )

        self.restaurant = Restaurant.objects.create(
            code='1270100', name='AJAX R', city='C', address='A')
        self.user.restaurants.add(self.restaurant)
        self.template = AuditTemplate.objects.create(name='AJAX T')
        self.section = Section.objects.create(
            template=self.template, name='S', order=1)
        self.question = Question.objects.create(
            section=self.section, question_text='Q', possible_points=10, order=1)
        self.audit = Audit.objects.create(
            template=self.template, restaurant=self.restaurant,
            audit_date='2026-06-15', manager_on_duty='M', auditor=self.user,
        )
        self.audit_section = AuditSection.objects.create(
            audit=self.audit, section=self.section, possible_points=10)
        self.response = AuditQuestionResponse.objects.create(
            audit_section=self.audit_section, question=self.question,
            is_answered=False)
        self.client.force_login(self.user)

    def test_save_response_valid(self):
        resp = self.client.post('/audits/save-response/', {
            'response_id': self.response.pk,
            'scored_points': '8',
            'comments': 'Good',
            'is_na': 'false',
            'needs_ca': 'false',
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.response.refresh_from_db()
        self.assertEqual(self.response.scored_points, Decimal('8'))
        self.assertEqual(self.response.comments, 'Good')
        self.assertTrue(self.response.is_answered)

    def test_save_response_missing_response_id(self):
        resp = self.client.post('/audits/save-response/', {})
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()['success'])

    def test_save_response_invalid_response_id(self):
        resp = self.client.post('/audits/save-response/', {'response_id': 99999})
        self.assertEqual(resp.status_code, 404)

    def test_save_response_is_na_zeroes_score_and_clears_ca_flag(self):
        resp = self.client.post('/audits/save-response/', {
            'response_id': self.response.pk,
            'scored_points': '5',
            'comments': 'Item not present at time of audit',
            'is_na': 'true',
            'needs_ca': 'true',
        })
        self.assertEqual(resp.status_code, 200)
        self.response.refresh_from_db()
        self.assertTrue(self.response.is_na)
        self.assertEqual(self.response.scored_points, Decimal('0.00'))
        # Comments preserved to avoid data loss if N/A is later unchecked
        self.assertEqual(self.response.comments, 'Item not present at time of audit')
        self.assertFalse(self.response.needs_corrective_action)

    def test_save_response_score_exceeds_max(self):
        resp = self.client.post('/audits/save-response/', {
            'response_id': self.response.pk,
            'scored_points': '20',
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn('cannot exceed', resp.json()['message'])

    def test_save_response_invalid_score_value(self):
        resp = self.client.post('/audits/save-response/', {
            'response_id': self.response.pk,
            'scored_points': 'not-a-number',
        })
        self.assertEqual(resp.status_code, 400)

    def test_save_response_submitted_audit_rejected(self):
        self.audit.is_submitted = True
        self.audit.save()
        resp = self.client.post('/audits/save-response/', {
            'response_id': self.response.pk,
            'scored_points': '5',
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn('already submitted', resp.json()['message'])

    def test_save_response_requires_change_audit_permission(self):
        other = User.objects.create_user('no_change', 'nc@t.com', 'pass')
        other.restaurants.add(self.restaurant)
        # Give view_audit but NOT change_audit
        ct = ContentType.objects.get_for_model(Audit)
        other.user_permissions.add(
            Permission.objects.get(content_type=ct, codename='view_audit')
        )
        self.client.force_login(other)
        resp = self.client.post('/audits/save-response/', {
            'response_id': self.response.pk,
            'scored_points': '5',
        })
        self.assertEqual(resp.status_code, 403)

    def test_save_response_scoped_to_user_restaurants(self):
        other_restaurant = Restaurant.objects.create(
            code='9999998', name='Other R', city='C', address='A')
        other_user = User.objects.create_user('other_user', 'ou@t.com', 'pass')
        ct = ContentType.objects.get_for_model(Audit)
        for codename in ('change_audit', 'view_audit'):
            other_user.user_permissions.add(
                Permission.objects.get(content_type=ct, codename=codename)
            )
        ct_aqr = ContentType.objects.get_for_model(AuditQuestionResponse)
        other_user.user_permissions.add(
            *Permission.objects.filter(content_type=ct_aqr)
        )
        other_user.restaurants.add(other_restaurant)
        self.client.force_login(other_user)
        # This user has change_audit perms but not for THIS restaurant
        resp = self.client.post('/audits/save-response/', {
            'response_id': self.response.pk,
            'scored_points': '5',
        })
        self.assertEqual(resp.status_code, 404)


class AJAXFillRemainingViewTest(TestCase):
    """Tests for FillRemainingView — auto-fill unanswered questions to max."""

    def setUp(self):
        self.user = User.objects.create_user('fill_user', 'f@t.com', 'pass')
        ct = ContentType.objects.get_for_model(Audit)
        for codename in ('change_audit', 'view_audit'):
            self.user.user_permissions.add(
                Permission.objects.get(content_type=ct, codename=codename)
            )
        self.restaurant = Restaurant.objects.create(
            code='1270101', name='Fill R', city='C', address='A')
        self.user.restaurants.add(self.restaurant)
        self.template = AuditTemplate.objects.create(name='Fill T')
        self.section = Section.objects.create(
            template=self.template, name='S1', order=1)
        self.q1 = Question.objects.create(
            section=self.section, question_text='Q1', possible_points=5, order=1)
        self.q2 = Question.objects.create(
            section=self.section, question_text='Q2', possible_points=10, order=2)
        self.audit = Audit.objects.create(
            template=self.template, restaurant=self.restaurant,
            audit_date='2026-06-15', manager_on_duty='M', auditor=self.user,
        )
        self.audit_section = AuditSection.objects.create(
            audit=self.audit, section=self.section, possible_points=15)
        self.resp1 = AuditQuestionResponse.objects.create(
            audit_section=self.audit_section, question=self.q1,
            is_answered=False, scored_points=Decimal('0.00'))
        self.resp2 = AuditQuestionResponse.objects.create(
            audit_section=self.audit_section, question=self.q2,
            is_answered=False, scored_points=Decimal('0.00'))
        self.client.force_login(self.user)

    def test_fill_remaining_all(self):
        resp = self.client.post('/audits/fill-remaining/', {
            'audit_id': self.audit.pk,
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['filled_count'], 2)
        self.resp1.refresh_from_db()
        self.resp2.refresh_from_db()
        self.assertEqual(self.resp1.scored_points, Decimal('5'))
        self.assertEqual(self.resp2.scored_points, Decimal('10'))
        self.assertTrue(self.resp1.is_answered)
        self.assertTrue(self.resp2.is_answered)

    def test_fill_remaining_single_section(self):
        resp = self.client.post('/audits/fill-remaining/', {
            'audit_id': self.audit.pk,
            'section_id': str(self.audit_section.pk),
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['filled_count'], 2)

    def test_fill_remaining_skips_answered_and_na(self):
        self.resp1.is_answered = True
        self.resp1.scored_points = Decimal('3')
        self.resp1.save()
        resp = self.client.post('/audits/fill-remaining/', {
            'audit_id': self.audit.pk,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['filled_count'], 1)

    def test_fill_remaining_missing_audit_id(self):
        resp = self.client.post('/audits/fill-remaining/', {})
        self.assertEqual(resp.status_code, 400)

    def test_fill_remaining_submitted_audit_rejected(self):
        self.audit.is_submitted = True
        self.audit.save()
        resp = self.client.post('/audits/fill-remaining/', {
            'audit_id': self.audit.pk,
        })
        self.assertEqual(resp.status_code, 400)

    def test_fill_remaining_scoped(self):
        other = User.objects.create_user('other_fill', 'of@t.com', 'pass')
        ct = ContentType.objects.get_for_model(Audit)
        for codename in ('change_audit', 'view_audit'):
            other.user_permissions.add(
                Permission.objects.get(content_type=ct, codename=codename)
            )
        self.client.force_login(other)
        resp = self.client.post('/audits/fill-remaining/', {
            'audit_id': self.audit.pk,
        })
        self.assertEqual(resp.status_code, 404)


class AJAXAuditSubmitJSONViewTest(TestCase):
    """Tests for AuditSubmitJSONView — JSON-based audit submission."""

    def setUp(self):
        self.user = User.objects.create_user('submit_user', 's@t.com', 'pass')
        ct = ContentType.objects.get_for_model(Audit)
        for codename in ('change_audit', 'view_audit'):
            self.user.user_permissions.add(
                Permission.objects.get(content_type=ct, codename=codename)
            )
        self.restaurant = Restaurant.objects.create(
            code='1270102', name='Submit R', city='C', address='A')
        self.user.restaurants.add(self.restaurant)
        self.template = AuditTemplate.objects.create(name='Submit T')
        self.section = Section.objects.create(
            template=self.template, name='S', order=1)
        Question.objects.create(
            section=self.section, question_text='Q', possible_points=10, order=1)
        self.audit = Audit.objects.create(
            template=self.template, restaurant=self.restaurant,
            audit_date='2026-06-15', manager_on_duty='M', auditor=self.user,
        )
        audit_section = AuditSection.objects.create(
            audit=self.audit, section=self.section, possible_points=10)
        AuditQuestionResponse.objects.create(
            audit_section=audit_section,
            question=self.section.questions.first(),
            is_answered=True, scored_points=Decimal('10'))
        self.client.force_login(self.user)

    @patch('audits.views.notify_restaurant_users')
    @patch('audits.views.auto_generate_corrective_actions')
    def test_submit_json_success(self, mock_auto_ca, mock_notify):
        resp = self.client.post(f'/audits/{self.audit.pk}/submit-json/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertIn('redirect_url', data)
        self.audit.refresh_from_db()
        self.assertTrue(self.audit.is_submitted)
        self.assertIsNotNone(self.audit.submitted_at)

    def test_submit_json_already_submitted(self):
        self.audit.is_submitted = True
        self.audit.save()
        resp = self.client.post(f'/audits/{self.audit.pk}/submit-json/')
        self.assertEqual(resp.status_code, 400)

    def test_submit_json_404(self):
        resp = self.client.post('/audits/99999/submit-json/')
        self.assertEqual(resp.status_code, 404)

    def test_submit_json_scoped(self):
        other = User.objects.create_user('other_sub', 'os@t.com', 'pass')
        ct = ContentType.objects.get_for_model(Audit)
        for codename in ('change_audit', 'view_audit'):
            other.user_permissions.add(
                Permission.objects.get(content_type=ct, codename=codename)
            )
        self.client.force_login(other)
        resp = self.client.post(f'/audits/{self.audit.pk}/submit-json/')
        self.assertEqual(resp.status_code, 404)

    def test_submit_json_requires_change_audit(self):
        other = User.objects.create_user('no_change_sub', 'ncs@t.com', 'pass')
        other.restaurants.add(self.restaurant)
        ct = ContentType.objects.get_for_model(Audit)
        other.user_permissions.add(
            Permission.objects.get(content_type=ct, codename='view_audit')
        )
        self.client.force_login(other)
        resp = self.client.post(f'/audits/{self.audit.pk}/submit-json/')
        self.assertEqual(resp.status_code, 403)

