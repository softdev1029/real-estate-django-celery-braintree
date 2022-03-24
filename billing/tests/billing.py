from model_mommy import mommy

from django.urls import reverse

from sherpa.tasks import sherpa_send_email
from sherpa.tests import CompanyOneMixin, NoDataBaseTestCase
from ..models import Plan


class BillingAPITestCase(CompanyOneMixin, NoDataBaseTestCase):
    list_url = reverse('plan-list')

    def setUp(self):
        self.plan1 = mommy.make('billing.Plan', is_public=True)

    def test_anon_cant_get_plans(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 401)

    def test_only_public_plans_returned(self):
        response = self.master_admin_client.get(self.list_url)
        mommy.make('billing.Plan', is_public=True)
        self.assertEqual(response.status_code, 200)
        results = response.json()
        for result in results:
            plan = Plan.objects.get(id=result.get('id'))
            self.assertTrue(plan.is_public)


class BillingSubscriptionTestCase(CompanyOneMixin, NoDataBaseTestCase):
    def test_send_past_due_email(self):
        user = self.master_admin_user
        subject = 'Sherpa Subscription Past Due'
        sherpa_send_email(
            subject,
            'email/email_subscription_past_due.html',
            user.email,
            {
                'first_name': user.first_name,
                'user_full_name': user.get_full_name(),
                'company_name': self.company1.name,
            },
        )
        self.verify_email(
            subject,
            [user.first_name, user.get_full_name(), self.company1.name],
        )
