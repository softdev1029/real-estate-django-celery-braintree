from datetime import datetime, time

from model_mommy import mommy

from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site
from django.core import mail
from django.core.management import call_command
from django.test import override_settings, TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from .models import Company, SupportLink, UserProfile, ZapierWebhook
from .utils import convert_to_company_local, has_link, should_convert_datetime


User = get_user_model()


class CompanyOneMixin:
    """
    Adds the first company with a single user.
    """
    @classmethod
    def setUpTestData(cls):
        """
        Create very basic data for a single user.
        """
        super(CompanyOneMixin, cls).setUpTestData()
        cls.master_admin_user = User.objects.create_user(
            "georgew",
            "george.washington@asdf.com",
            "georgepass",
        )
        cls.invitation_code1 = mommy.make(
            'sherpa.InvitationCode',
            code='code1',
        )
        cls.company1 = mommy.make(
            'sherpa.Company',
            invitation_code=cls.invitation_code1,
            subscription_status=Company.SubscriptionStatus.ACTIVE,
            braintree_id='213639461',
            subscription_id='gh3mcb',
            admin_name=cls.master_admin_user.get_full_name(),
            outgoing_company_names=['GeorgeTestCompany'],
            outgoing_user_names=['GeorgeTestUserName'],
            start_time=time(0, 0, 0),
            end_time=time(23, 59, 59),
        )
        cls.master_admin_user.profile.company = cls.company1
        cls.master_admin_user.profile.role = UserProfile.Role.MASTER_ADMIN
        cls.master_admin_user.profile.is_primary = True
        cls.master_admin_user.profile.save()

        cls.master_admin_client = APIClient()
        cls.master_admin_client.force_authenticate(user=cls.master_admin_user)


class CompanyTwoMixin:
    """
    Adds a second company, useful for when we need to test certain functionality or filtering is
    only available for a single company.
    """
    @classmethod
    def setUpTestData(cls):
        super(CompanyTwoMixin, cls).setUpTestData()
        cls.company2_user = mommy.make(
            User,
            first_name="Thomas",
            last_name="Jefferson",
            username="thomasj",
            email="thomas.jefferson@asdf.com",
        )
        cls.invitation_code2 = mommy.make('sherpa.InvitationCode', code='code2')
        cls.company2 = mommy.make(
            'sherpa.Company',
            invitation_code=cls.invitation_code2,
            subscription_status=Company.SubscriptionStatus.ACTIVE,
            admin_name=cls.company2_user.get_full_name(),
            send_carrier_approved_templates=True,
            outgoing_company_names=['ThomasTestCompany'],
            outgoing_user_names=['ThomasTestUserName'],
            timezone='US/Central',
        )
        cls.company2_user.profile.company = cls.company2
        cls.company2_user.profile.save()

        cls.company2_client = APIClient()
        cls.company2_client.force_authenticate(user=cls.company2_user)
        cls.company2_client.force_authenticate(user=cls.company2_user)


class AdminUserMixin:
    """
    Add an admin user to company1.
    """
    @classmethod
    def setUpTestData(cls):
        super(AdminUserMixin, cls).setUpTestData()
        cls.admin_user = mommy.make(
            User,
            first_name="Admin",
            last_name="User",
            username="admin",
            email="admin@asdf.com",
        )
        cls.admin_user.profile.company = cls.company1
        cls.admin_user.profile.role = UserProfile.Role.ADMIN
        cls.admin_user.profile.save()

        cls.admin_client = APIClient()
        cls.admin_client.force_authenticate(user=cls.admin_user)
        cls.admin_client.force_authenticate(user=cls.admin_user)


class StaffUserMixin:
    """
    Add a staff user to company1.
    """
    @classmethod
    def setUpTestData(cls):
        super(StaffUserMixin, cls).setUpTestData()
        cls.staff_user = mommy.make(
            User,
            first_name="Staff",
            last_name="User",
            username="staff",
            email="staff@asdf.com",
        )
        cls.staff_user.profile.company = cls.company1
        cls.staff_user.profile.role = UserProfile.Role.STAFF
        cls.staff_user.profile.save()

        cls.staff_client = APIClient()
        cls.staff_client.force_authenticate(user=cls.staff_user)
        cls.staff_client.force_authenticate(user=cls.staff_user)


class JrStaffUserMixin:
    """
    Add a junior staff user to company1.
    """
    @classmethod
    def setUpTestData(cls):
        super(JrStaffUserMixin, cls).setUpTestData()
        cls.jrstaff_user = mommy.make(
            User,
            first_name="Junior",
            last_name="Staff",
            username="jrstaff",
            email="jrstaff@asdf.com",
        )
        cls.jrstaff_user.profile.company = cls.company1
        cls.jrstaff_user.profile.role = UserProfile.Role.JUNIOR_STAFF
        cls.jrstaff_user.profile.save()

        cls.jrstaff_client = APIClient()
        cls.jrstaff_client.force_authenticate(user=cls.jrstaff_user)
        cls.jrstaff_client.force_authenticate(user=cls.jrstaff_user)


class AllUserRoleMixin(AdminUserMixin, StaffUserMixin, JrStaffUserMixin):
    """
    Add all the four roles to company 1.
    """


class SitesMixin:
    """
    Apply to test classes that need to have the sites created.
    """
    @classmethod
    def setUpTestData(cls):
        super(SitesMixin, cls).setUpTestData()
        mommy.make(
            Site,
            id=1,
            domain='localhost:8000',
            name='Sherpa Test API',
        )
        mommy.make(
            Site,
            id=2,
            domain='localhost:3000',
            name='Sherpa Test Frontend',
        )


class BaseDataMixin:
    """
    Setup data that can be used in all test cases.
    """
    @classmethod
    def setUpTestData(cls):
        mommy.make(
            'Site',
            domain='localhost:3000',
            name='Sherpa Frontend',
        )
        cls.george_user = User.objects.create_user(
            "georgew",
            "george.washington@asdf.com",
            "georgepass",
        )
        cls.george_user.first_name = "George"
        cls.george_user.last_name = "Washington"
        cls.george_user.save()

        cls.john_user = mommy.make(
            User,
            first_name="John",
            last_name="Adams",
            username="johna",
            email="john.adams@asdf.com",
        )

        cls.staff_user = mommy.make(
            User,
            first_name="Staff",
            last_name="User",
            username="staff",
            email="staff@asdf.com",
        )

        cls.jr_staff_user = mommy.make(
            User,
            first_name="Junior",
            last_name="Staff",
            username="jrstaff",
            email="jrstaff@asdf.com",
        )

        cls.thomas_user = mommy.make(
            User,
            first_name="Thomas",
            last_name="Jefferson",
            username="thomasj",
            email="thomas.jefferson@asdf.com",
        )

        cls.admin_user = mommy.make(
            User,
            first_name="Admin",
            last_name="User",
            username="admin",
            email="admin.user@asdf.com",
            is_superuser=True,
            is_staff=True,
        )

        cls.invitation_code1 = mommy.make(
            'sherpa.InvitationCode',
            code='code1',
        )
        cls.invitation_code2 = mommy.make('sherpa.InvitationCode', code='code2')
        cls.company1 = mommy.make(
            'sherpa.Company',
            name='George Company',
            invitation_code=cls.invitation_code1,
            subscription_status=Company.SubscriptionStatus.ACTIVE,
            braintree_id='213639461',
            subscription_id='gh3mcb',
            admin_name=cls.george_user.get_full_name(),
            outgoing_company_names=['GeorgeTestCompany'],
            outgoing_user_names=['GeorgeTestUserName'],
            start_time=time(0, 0, 0),
            end_time=time(23, 59, 59),
        )
        cls.company2 = mommy.make(
            'sherpa.Company',
            name='Thomas Company',
            invitation_code=cls.invitation_code2,
            subscription_status=Company.SubscriptionStatus.ACTIVE,
            admin_name=cls.thomas_user.get_full_name(),
            send_carrier_approved_templates=True,
            outgoing_company_names=['ThomasTestCompany'],
            outgoing_user_names=['ThomasTestUserName'],
            start_time=time(0, 0, 0),
            end_time=time(23, 59, 59),
            timezone='US/Central',
        )

        cls.company1_users = [cls.george_user, cls.staff_user, cls.jr_staff_user, cls.john_user]
        cls.george_user.profile.is_primary = True
        cls.john_user.profile.role = UserProfile.Role.ADMIN
        cls.jr_staff_user.profile.role = UserProfile.Role.JUNIOR_STAFF
        cls.staff_user.profile.role = UserProfile.Role.STAFF
        for user in cls.company1_users:
            user.profile.company = cls.company1
            user.profile.save()

        cls.thomas_user.profile.company = cls.company2
        cls.thomas_user.profile.phone = '2068883333'
        cls.thomas_user.profile.is_primary = True
        cls.thomas_user.profile.start_time = time(13, 0)  # 1 PM
        cls.thomas_user.profile.end_time = time(15, 0)  # 3 PM
        cls.thomas_user.profile.save()


class TimeTrackingMixin:
    @classmethod
    def setUpClass(cls):
        print(f'\n\n{cls.__name__}')
        cls.__start_time = datetime.now()
        super(TimeTrackingMixin, cls).setUpClass()

    @classmethod
    def tearDownClass(cls):
        super(TimeTrackingMixin, cls).tearDownClass()
        duration = datetime.now() - cls.__start_time
        print(f' ({duration.seconds} seconds)')


@override_settings(task_always_eager=True)
class BaseTestCase(TimeTrackingMixin, BaseDataMixin, TestCase):
    """
    Test class to be inherited by all non-api test cases requiring data.

    In general we'll be testing models or groups of models in a single class.
    """


@override_settings(task_always_eager=True)
class NoDataBaseTestCase(TimeTrackingMixin, TestCase):
    """
    Test class to be inherited by test cases that don't need to load the full data from
    `BaseDataMixin`.
    """
    def verify_email(self, subject, string_list):
        """
        Verify that an email contains the expected results.
        """
        email = mail.outbox[0]
        self.assertEqual(email.subject, subject)

        content = email.alternatives[0][0]
        for string in string_list:
            assert string in content


@override_settings(task_always_eager=True)
class BaseAPITestCase(TimeTrackingMixin, BaseDataMixin, APITestCase):
    """
    Test class to be inherited by all model test cases.

    In general we'll be testing models or groups of models in a single class.
    """
    def setUp(self):
        # George company clients.
        self.george_client = APIClient()
        self.george_client.force_authenticate(user=self.george_user)
        self.john_client = APIClient()
        self.john_client.force_authenticate(user=self.john_user)
        self.staff_client = APIClient()
        self.staff_client.force_authenticate(user=self.staff_user)
        self.jrstaff_client = APIClient()
        self.jrstaff_client.force_authenticate(user=self.jr_staff_user)

        # Other company clients.
        self.thomas_client = APIClient()
        self.thomas_client.force_authenticate(user=self.thomas_user)


class GeneralAPITestCase(CompanyOneMixin, NoDataBaseTestCase):

    campaign_list_url = reverse('campaign-list')
    docs_url = reverse('schema-redoc')

    def test_normal_can_get_docs(self):
        response = self.master_admin_client.get(self.docs_url)
        self.assertEqual(response.status_code, 200)

    @override_settings(REQUIRE_DOCS_ADMIN=True)
    def test_normal_cant_get_docs(self):
        response = self.master_admin_client.get(self.docs_url)
        self.assertEqual(response.status_code, 200)

    def test_can_get_status_page(self):
        url = reverse('status')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)


class SettingsTestCase(APITestCase):

    def test_can_import_all_settings(self):
        # Weird test, but it checks to make sure the environment settings can be loaded correctly.
        # This protects against pushing to an environment when its respected module can't be loaded.
        from core.settings.develop import ALLOWED_HOSTS as develop_hosts  # noqa: F401
        from core.settings.staging import ALLOWED_HOSTS as staging_hosts  # noqa: F401
        from core.settings.prod import ALLOWED_HOSTS as prod_hosts  # noqa: F401


class SupportLinkAPITestCase(CompanyOneMixin, NoDataBaseTestCase):
    support_link_list_url = reverse('supportlink-list')

    def setUp(self):
        super(SupportLinkAPITestCase, self).setUp()
        mommy.make('sherpa.SupportLink', icon='["fas", "blah"]')

    def test_anon_cant_get_support_links(self):
        response = self.client.get(self.support_link_list_url)
        self.assertEqual(response.status_code, 401)

    def test_authenticated_can_get_support_links(self):
        response = self.master_admin_client.get(self.support_link_list_url)
        self.assertEqual(response.json().get('count'), SupportLink.objects.count())

    def test_icon_rendered_as_list(self):
        response = self.master_admin_client.get(self.support_link_list_url)
        result = response.json().get('results')[0].get('icon')
        self.assertEqual(type(result), list)


class ZapierWebhookAPITestCase(
        StaffUserMixin,
        CompanyTwoMixin,
        CompanyOneMixin,
        NoDataBaseTestCase):
    """
    Zapier webhook tests for usage with DRF - not to be confused with current usage.
    """
    list_url = reverse('zapierwebhook-list')

    def setUp(self):
        super().setUp()
        self.webhook = mommy.make(
            'sherpa.ZapierWebhook',
            company=self.company1,
            webhook_url='http://example.com/lead1',
            webhook_type=ZapierWebhook.Type.PROSPECT,
        )
        self.webhook2 = mommy.make(
            'sherpa.ZapierWebhook',
            company=self.company1,
            webhook_url='http://example.com/sms1',
            webhook_type=ZapierWebhook.Type.SMS,
        )
        mommy.make(
            'sherpa.ZapierWebhook',
            company=self.company2,
            webhook_url='http://example.com/lead2',
            webhook_type=ZapierWebhook.Type.PROSPECT,
        )
        self.detail_url = reverse('zapierwebhook-detail', kwargs={'pk': self.webhook.id})
        self.campaign = mommy.make('sherpa.Campaign', company=self.company1)

    def test_anon_cant_get_zapier_webhooks(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 401)

    def test_can_get_zapier_webhooks(self):
        response = self.master_admin_client.get(self.list_url)
        results = response.json().get('results')
        self.assertEqual(len(results), self.company1.webhooks.count())
        for webhook_data in results:
            webhook = ZapierWebhook.objects.get(id=webhook_data.get('id'))
            self.assertEqual(webhook.company, self.company1)

    def test_cant_update_others_zapier_webhook(self):
        new_name = "lead42"
        payload = {"name": new_name}
        response = self.company2_client.patch(self.detail_url, payload)
        self.webhook.refresh_from_db()
        self.assertEqual(response.status_code, 404)
        self.assertNotEqual(self.webhook.name, new_name)

    def test_can_update_zapier_webhook(self):
        new_name = "lead42"
        payload = {"name": new_name}
        response = self.master_admin_client.patch(self.detail_url, payload)
        self.webhook.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.webhook.name, new_name)

    def test_set_webhook_to_inactive_removes_from_campaigns(self):
        # Save the webhook and verify that it's attached to the campaign.
        self.campaign.zapier_webhook = self.webhook
        self.campaign.save()
        self.assertTrue(self.webhook.campaign_set.count() > 0)

        payload = {"status": ZapierWebhook.Status.INACTIVE}
        self.master_admin_client.patch(self.detail_url, payload)
        self.campaign.refresh_from_db()
        self.assertEqual(self.webhook.campaign_set.count(), 0)

    def test_can_create_new_webhook(self):
        payload = {
            "name": "New Webhook Test",
            "webhook_url": "http://www.example.com",
            "type": "prospect",
        }
        response = self.master_admin_client.post(self.list_url, payload)
        self.assertEqual(response.status_code, 201)

    def test_admin_plus_required(self):
        payload = {
            "name": "New Webhook Test 2",
            "webhook_url": "http://www.example.com",
            "type": "prospect",
        }
        response = self.staff_client.post(self.list_url, payload)
        self.assertEqual(response.status_code, 403)

    def test_delete_webhook(self):
        response = self.staff_client.get(self.list_url)
        results = response.json().get('results')
        pk = results[-1]['id']

        url = reverse('zapierwebhook-detail', kwargs={'pk': pk})
        response = self.master_admin_client.delete(url)
        self.assertEqual(response.status_code, 204)

        response = self.master_admin_client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_set_default(self):
        self.assertTrue(self.webhook.is_default)
        url = reverse('company-detail', kwargs={'pk': self.company1.id})
        payload = {
            "default_zapier_webhook": self.webhook2.id,
        }
        self.master_admin_client.patch(url, payload)
        self.company1.refresh_from_db()
        self.assertFalse(self.webhook.is_default)
        self.assertTrue(self.webhook2.is_default)


class GeneralUtilTestCase(NoDataBaseTestCase):

    @classmethod
    def setUpTestData(cls):
        cls.company = mommy.make('Company', timezone='America/New_York')

    def test_can_convert_aware_datetime_to_company(self):
        company_aware = convert_to_company_local(timezone.now(), self.company)
        self.assertEqual(str(company_aware.tzinfo), self.company.timezone)

    def test_can_convert_naive_datetime_to_company(self):
        naive_dt = datetime.now()
        company_aware = convert_to_company_local(naive_dt, self.company)
        self.assertEqual(str(company_aware.tzinfo), self.company.timezone)

    def test_convert_email_datetime(self):
        self.assertFalse(should_convert_datetime('does_not_contain'))
        self.assertTrue(should_convert_datetime('date_billing'))
        self.assertTrue(should_convert_datetime('billing_date'))
        self.assertTrue(should_convert_datetime('datetime_billing'))
        self.assertTrue(should_convert_datetime('billing_datetime'))

    def test_check_if_str_has_link(self):
        positive = [
            'hello http://www.example.com there',
            'click me https://www.example.com',
            'www.example.com',
        ]
        negative = [
            'this is valid',
            'sell me your home, please.',
            'this.has.some.periods.but.is.not.a.link',
        ]

        for positive_string in positive:
            self.assertTrue(has_link(positive_string))

        for negative_string in negative:
            self.assertFalse(has_link(negative_string))


class SherpaCommandTestCase(NoDataBaseTestCase):

    def test_nightly_job_command(self):
        call_command('clear_today_sent_received_count')


class InvitationCodeAPITestCase(CompanyOneMixin, NoDataBaseTestCase):

    def setUp(self):
        super(InvitationCodeAPITestCase, self).setUp()
        self.detail_url = reverse('invitationcode-detail', kwargs={'pk': self.invitation_code1.id})

    def test_unauthenticated_cant_get_invitation_code(self):
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, 401)

    def test_can_get_invitation_code(self):
        response = self.master_admin_client.get(self.detail_url)
        self.assertEqual(response.status_code, 200)
