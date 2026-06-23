from django.core.management.base import BaseCommand
from django.utils import timezone

from decimal import Decimal
from datetime import date, timedelta

from accounts.models import User, Designation, Department
from restaurants.models import Region, Restaurant
from audits.models import AuditTemplate, Section, Question, Audit, AuditSection, AuditQuestionResponse, CorrectiveAction


class Command(BaseCommand):
    help = 'Seed the database with demo data for development and testing'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Delete existing data before seeding',
        )

    def handle(self, *args, **options):
        if options['force']:
            self.stdout.write('Clearing existing data...')
            Question.objects.all().delete()
            Section.objects.all().delete()
            AuditTemplate.objects.all().delete()
            Restaurant.objects.all().delete()
            Region.objects.all().delete()
            User.objects.filter(is_superuser=False).delete()
            Designation.objects.all().delete()
            Department.objects.all().delete()

        self._seed_departments()
        self._seed_designations()
        self._seed_regions()
        self._seed_restaurants()
        self._seed_users()
        self._seed_templates()
        self._seed_audits()

        self.stdout.write(self.style.SUCCESS(
            'Demo data seeded successfully.'))

    # -----------------------------
    # Departments
    # -----------------------------
    def _seed_departments(self):
        departments = ['Operations', 'Quality Assurance',
                       'Training', 'Marketing', 'Human Resources']
        for name in departments:
            Department.objects.get_or_create(name=name)
        self.stdout.write(f'  OK {len(departments)} departments')

    # -----------------------------
    # Designations
    # -----------------------------
    def _seed_designations(self):
        designations = [
            'Regional Manager', 'Restaurant Manager',
            'Shift Manager', 'Quality Auditor',
            'Training Coordinator', 'Area Supervisor',
        ]
        for name in designations:
            Designation.objects.get_or_create(name=name)
        self.stdout.write(f'  OK {len(designations)} designations')

    # -----------------------------
    # Regions
    # -----------------------------
    def _seed_regions(self):
        regions = [
            'Lahore', 'Karachi', 'Islamabad',
            'Rawalpindi', 'Faisalabad', 'Multan',
            'Gujranwala', 'Peshawar', 'Quetta', 'Sialkot',
        ]
        for name in regions:
            Region.objects.get_or_create(name=name)
        self.stdout.write(f'  OK {len(regions)} regions')

    # -----------------------------
    # Restaurants
    # -----------------------------
    def _seed_restaurants(self):
        data = [
            ('1270001', 'McDonald\'s Gulberg', 'Lahore',
             'Main Boulevard, Gulberg', 'Lahore'),
            ('1270002', 'McDonald\'s MM Alam Road', 'Lahore',
             'MM Alam Road, Gulberg II', 'Lahore'),
            ('1270003', 'McDonald\'s Johar Town', 'Lahore',
             'Main Boulevard, Johar Town', 'Lahore'),
            ('1270004', 'McDonald\'s Clifton', 'Karachi',
             'Seaview Road, Clifton', 'Karachi'),
            ('1270005', 'McDonald\'s Saddar', 'Karachi',
             'Abdullah Haroon Road, Saddar', 'Karachi'),
            ('1270006', 'McDonald\'s F-10 Markaz', 'Islamabad',
             'F-10 Markaz, Islamabad', 'Islamabad'),
            ('1270007', 'McDonald\'s Blue Area', 'Islamabad',
             'Blue Area, Jinnah Avenue', 'Islamabad'),
            ('1270008', 'McDonald\'s Faisalabad City', 'Faisalabad',
             'Kutchery Road, Faisalabad', 'Faisalabad'),
            ('1270009', 'McDonald\'s Multan Cantt', 'Multan',
             'Abdali Road, Multan Cantt', 'Multan'),
            ('1270010', 'McDonald\'s Peshawar City', 'Peshawar',
             'Grand Trunk Road, Peshawar', 'Peshawar'),
        ]
        for code, name, city, address, region_name in data:
            region = Region.objects.filter(name=region_name).first()
            Restaurant.objects.get_or_create(
                code=code,
                defaults={
                    'name': name,
                    'city': city,
                    'address': address,
                    'region': region,
                    'phone': f'042-111{code[3:]}',
                }
            )
        self.stdout.write(f'  OK {len(data)} restaurants')

    # -----------------------------
    # Users
    # -----------------------------
    def _seed_users(self):
        # Always create demo users if any are missing
        created = 0

        if not User.objects.filter(username='admin').exists():
            User.objects.create_superuser(
                'admin', 'admin@mcdonalds.pk', 'admin123',
                first_name='Admin', last_name='User',
                role=User.Roles.ADMIN,
            )
            created += 1

        mgr, mgr_created = User.objects.get_or_create(
            username='manager',
            defaults={
                'email': 'manager@mcdonalds.pk',
                'first_name': 'Ali', 'last_name': 'Khan',
                'role': User.Roles.MANAGER,
                'designation': Designation.objects.filter(name='Regional Manager').first(),
                'department': Department.objects.filter(name='Operations').first(),
            },
        )
        if mgr_created:
            mgr.set_password('manager123')
            mgr.save()
            created += 1

        r1 = Restaurant.objects.filter(code='1270001').first()
        r2 = Restaurant.objects.filter(code='1270002').first()

        for uname, fname, lname in [
            ('auditor1', 'Ahmed', 'Hassan'),
            ('auditor2', 'Sara', 'Ahmed'),
        ]:
            aud, aud_created = User.objects.get_or_create(
                username=uname,
                defaults={
                    'email': f'{uname}@mcdonalds.pk',
                    'first_name': fname, 'last_name': lname,
                    'role': User.Roles.AUDITOR,
                    'manager': mgr,
                    'designation': Designation.objects.filter(name='Quality Auditor').first(),
                    'department': Department.objects.filter(name='Quality Assurance').first(),
                },
            )
            if aud_created:
                aud.set_password('auditor123')
                aud.save()
                created += 1
            if r1 and not aud.restaurants.filter(pk=r1.pk).exists():
                aud.restaurants.add(r1)
            if uname == 'auditor2' and r2 and not aud.restaurants.filter(pk=r2.pk).exists():
                aud.restaurants.add(r2)

        ru, ru_created = User.objects.get_or_create(
            username='restuser',
            defaults={
                'email': 'rest@mcdonalds.pk',
                'first_name': 'Usman', 'last_name': 'Tariq',
                'role': User.Roles.RESTAURANT_USER,
                'designation': Designation.objects.filter(name='Restaurant Manager').first(),
                'department': Department.objects.filter(name='Operations').first(),
            },
        )
        if ru_created:
            ru.set_password('rest123')
            ru.save()
            created += 1
            if r1:
                ru.restaurants.add(r1)

        users_count = User.objects.count()
        self.stdout.write(f'  OK {users_count} demo users')

    # -----------------------------
    # Audit Templates
    # -----------------------------
    def _seed_templates(self):
        template, created = AuditTemplate.objects.get_or_create(
            name='2nd Party Audit Check List',
            defaults={
                'description': 'Standard 2nd party audit checklist for McDonald\'s Pakistan restaurants covering food safety, quality, service, and cleanliness.',
                'version': '2.0',
            },
        )
        if not created:
            self.stdout.write('  ~ template already exists')
            return

        sections_data = [
            {
                'name': 'Kitchen & Food Safety',
                'order': 1,
                'description': 'Kitchen hygiene, temperature control, and food safety protocols.',
                'questions': [
                    ('Are all refrigeration units maintaining proper temperature (0-4°C for fridge, -18°C for freezer)?', 10, True, 'Temperature out of range'),
                    ('Are food contact surfaces cleaned and sanitized between uses?', 10, False, ''),
                    ('Are handwashing stations properly stocked and used by staff?', 10, False, ''),
                    ('Are food items properly labeled with date and time?', 5, False, ''),
                    ('Is the FIFO (First In, First Out) system being followed?', 5, False, ''),
                ],
            },
            {
                'name': 'Service & Customer Experience',
                'order': 2,
                'description': 'Order accuracy, speed of service, and customer interaction quality.',
                'questions': [
                    ('Is the order accuracy rate above 95%?', 10, True, 'Order accuracy below 95%'),
                    ('Is the average wait time under 3 minutes?', 5, False, ''),
                    ('Are staff greeting customers with a smile?', 5, False, ''),
                    ('Is the dining area clean and well-maintained?', 5, False, ''),
                    ('Are complaints being logged and resolved?', 5, False, ''),
                ],
            },
            {
                'name': 'Restaurant Cleanliness',
                'order': 3,
                'description': 'Overall restaurant cleanliness including dining area, washrooms, and exterior.',
                'questions': [
                    ('Are washrooms clean and fully stocked?', 10, False, ''),
                    ('Is the dining floor free of debris and spills?', 5, False, ''),
                    ('Are trash bins emptied regularly?', 5, False, ''),
                    ('Is the exterior signage and parking area well-maintained?', 5, False, ''),
                ],
            },
            {
                'name': 'Staff & Training',
                'order': 4,
                'description': 'Staff appearance, uniform compliance, and training records.',
                'questions': [
                    ('Are all staff in proper uniform with name badges?', 5, False, ''),
                    ('Are training records up to date for all staff?', 10, True, 'Training records outdated'),
                    ('Is the shift schedule posted and followed?', 5, False, ''),
                    ('Are food safety certifications current?', 10, True, 'Expired certifications'),
                ],
            },
            {
                'name': 'Equipment & Maintenance',
                'order': 5,
                'description': 'Kitchen equipment functionality, maintenance logs, and safety checks.',
                'questions': [
                    ('Are all kitchen equipment in working condition?', 10, False, ''),
                    ('Is the maintenance log up to date?', 5, False, ''),
                    ('Are fire extinguishers inspected and accessible?', 10, True, 'Missing or expired extinguisher'),
                    ('Is the HVAC system functioning properly?', 5, False, ''),
                ],
            },
        ]

        for sec_data in sections_data:
            section = Section.objects.create(
                template=template,
                name=sec_data['name'],
                description=sec_data['description'],
                order=sec_data['order'],
            )
            for i, (text, points, critical, condition) in enumerate(sec_data['questions'], 1):
                Question.objects.create(
                    section=section,
                    question_text=text,
                    possible_points=points,
                    is_critical=critical,
                    critical_failure_condition=condition,
                    order=i,
                )

        total_questions = sum(len(s['questions']) for s in sections_data)
        self.stdout.write(f'  OK template "{template.name}" with '
                          f'{len(sections_data)} sections, {total_questions} questions')

    def _seed_audits(self):
        if Audit.objects.exists():
            self.stdout.write('  ~ audits already exist')
            return

        template = AuditTemplate.objects.first()
        if not template:
            self.stdout.write('  ! no template found, skipping audits')
            return

        auditor1 = User.objects.filter(username='auditor1').first()
        auditor2 = User.objects.filter(username='auditor2').first()
        if not auditor1 or not auditor2:
            self.stdout.write('  ! auditors not found, skipping audits')
            return

        r1 = Restaurant.objects.filter(code='1270001').first()
        r2 = Restaurant.objects.filter(code='1270002').first()
        r4 = Restaurant.objects.filter(code='1270004').first()
        if not all([r1, r2, r4]):
            self.stdout.write('  ! restaurants not found, skipping audits')
            return

        today = date.today()
        audits_data = [
            {
                'restaurant': r1,
                'auditor': auditor1,
                'audit_date': today - timedelta(days=7),
                'manager': 'Imran Ali',
                'scores': [9, 7, 10, 5, 5, 8, 5, 5, 4, 4, 10, 5, 5, 5, 5, 10, 5, 8, 10, 5, 10, 5],
                'submitted': True,
                'na_indices': [],
                'critical_failures': [],
                'ca_data': [],
            },
            {
                'restaurant': r2,
                'auditor': auditor2,
                'audit_date': today - timedelta(days=3),
                'manager': 'Saeed Ahmed',
                'scores': [6, 4, 8, 2, 3, 10, 5, 3, 5, 2, 8, 5, 5, 3, 5, 0, 5, 6, 0, 5, 10, 5],
                'submitted': True,
                'na_indices': [8],
                'critical_failures': [15, 18],
                'ca_data': [
                    {'desc': 'Fire extinguisher missing in kitchen area - replace immediately',
                     'risk': 'CRITICAL', 'assignee': 'Saeed Ahmed', 'deadline_delta': 3, 'completed': False},
                    {'desc': 'Training records outdated for 4 shift staff - schedule retraining',
                     'risk': 'HIGH', 'assignee': 'Hina Khan', 'deadline_delta': 7, 'completed': True},
                ],
            },
            {
                'restaurant': r4,
                'auditor': auditor1,
                'audit_date': today - timedelta(days=1),
                'manager': 'Farhan Mehmood',
                'scores': [7, 0, 9, 0, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                'submitted': False,
                'na_indices': [],
                'critical_failures': [],
                'ca_data': [],
            },
        ]

        sections = list(template.sections.order_by('order').prefetch_related('questions'))
        questions = [q for s in sections for q in s.questions.all()]
        total_q = len(questions)

        for ad in audits_data:
            scores = ad['scores']
            if len(scores) != total_q:
                self.stdout.write(self.style.WARNING(
                    f'  ! Expected {total_q} scores, got {len(scores)} for {ad["restaurant"].name}. Padding/truncating.'))
                scores = (scores + [0] * total_q)[:total_q]

            audit = Audit.objects.create(
                template=template,
                restaurant=ad['restaurant'],
                audit_date=ad['audit_date'],
                manager_on_duty=ad['manager'],
                auditor=ad['auditor'],
                is_submitted=ad['submitted'],
                submitted_at=timezone.now() if ad['submitted'] else None,
            )

            for sec_idx, section in enumerate(sections):
                sec_questions = list(section.questions.all())
                sec_possible = sum(q.possible_points for q in sec_questions)
                audit_section = AuditSection.objects.create(
                    audit=audit,
                    section=section,
                    possible_points=Decimal(str(sec_possible)),
                )

                for q_idx, question in enumerate(sec_questions):
                    global_idx = sum(len(s.questions.all()) for s in sections[:sec_idx]) + q_idx
                    score = scores[global_idx] if global_idx < len(scores) else 0
                    is_na = global_idx in ad['na_indices']
                    needs_ca = global_idx in ad['critical_failures']
                    AuditQuestionResponse.objects.create(
                        audit_section=audit_section,
                        question=question,
                        scored_points=Decimal(str(score)) if not is_na else Decimal('0'),
                        is_na=is_na,
                        is_answered=True,
                        needs_corrective_action=needs_ca,
                        comments='N/A - item not present at time of audit' if is_na else '',
                    )

                audit_section.calculate_section_score()

            audit.calculate_totals()

            all_responses = list(AuditQuestionResponse.objects.filter(
                audit_section__audit=audit,
            ).exclude(is_na=True).select_related('question'))
            for i, ca in enumerate(ad['ca_data']):
                resp = all_responses[i] if i < len(all_responses) else all_responses[0]
                assignee = User.objects.filter(
                    first_name__iexact=ca['assignee'].split()[0]
                ).first() if ca['assignee'] else None
                CorrectiveAction.objects.create(
                    audit=audit,
                    restaurant=ad['restaurant'],
                    question_response=resp,
                    description=ca['desc'],
                    risk_level=ca['risk'],
                    assigned_to=assignee,
                    deadline=today + timedelta(days=ca['deadline_delta']),
                    completed=ca['completed'],
                    completion_date=today if ca['completed'] else None,
                )

        self.stdout.write(f'  OK {len(audits_data)} sample audits with corrective actions')
