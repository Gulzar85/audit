from decimal import Decimal
from datetime import date, timedelta

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
            completed=True, completion_date=date.today(),
        )
        self.assertFalse(ca.is_overdue)
        self.assertIsNone(ca.days_remaining)


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

    def test_audit_detail_loads(self):
        resp = self.client.get(f'/audits/{self.audit.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Test R')

    def test_audit_score_loads(self):
        resp = self.client.get(f'/audits/{self.audit.pk}/score/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id_section')

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
