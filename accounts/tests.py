from datetime import datetime, timedelta
from decimal import Decimal

from djoser import utils
from model_mommy import mommy
import pytz

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.urls import reverse
from django.utils import timezone as django_tz

from accounts.models import UserLogin
from sherpa.models import Company, UserProfile
from sherpa.tests import (
    AllUserRoleMixin,
    CompanyOneMixin,
    CompanyTwoMixin,
    NoDataBaseTestCase,
    SitesMixin,
    StaffUserMixin,
)
from .tasks import modify_freshsuccess_user

User = get_user_model()


class UserProfileAPITestCase(CompanyTwoMixin, CompanyOneMixin, NoDataBaseTestCase):
    list_url = reverse('userprofile-list')
    agreement_url = reverse('userprofile-agreement')

    def setUp(self):
        super(UserProfileAPITestCase, self).setUp()
        self.detail_url = reverse(
            'userprofile-detail', kwargs={'pk': self.master_admin_user.profile.id})

    def test_unauthenticated_cant_get_profiles(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 401)

    def test_can_only_list_company_profiles(self):
        # Make sure there are profiles not in master admin's company.
        company2_profile_count = UserProfile.objects.filter(company=self.company2).count()
        self.assertTrue(company2_profile_count > 0)

        response = self.master_admin_client.get(self.list_url)
        for profile_data in response.json():
            self.assertEqual(profile_data.get('company'), self.company1.id)

    def test_can_update_agreement(self):
        # Verify that auth is required.
        response1 = self.client.post(self.agreement_url)
        self.assertEqual(response1.status_code, 401)

        # Verify that user's data is updated after updating the agreement.
        response2 = self.master_admin_client.post(self.agreement_url)
        self.assertEqual(response2.status_code, 200)
        profile = self.master_admin_user.profile
        self.assertEqual(profile.disclaimer_timestamp.date(), django_tz.now().date())

    def test_can_update_user_profile(self):
        updated_name = 'UPDATED'
        updated_role = 'staff'
        payload = {
            "role": updated_role,
            "user": {
                "first_name": updated_name,
            },
            "phone": "(312) 888-7777",
        }
        response = self.master_admin_client.patch(self.detail_url, payload)
        self.assertEqual(response.json().get('role'), updated_role)
        self.assertEqual(response.json().get('user').get('firstName'), updated_name)
        self.assertEqual(response.json().get('phone'), '3128887777')

    def test_can_update_employee_hours(self):
        payload = {
            "startTime": "10:00:00",
            "endTime": "15:00:00",
        }

        self.master_admin_client.patch(self.detail_url, payload)
        self.master_admin_user.refresh_from_db()
        self.assertEqual(self.master_admin_user.profile.start_time.hour, 10)
        self.assertEqual(self.master_admin_user.profile.end_time.hour, 15)


class InvitationCodeTestCase(CompanyTwoMixin, CompanyOneMixin, NoDataBaseTestCase):

    def setUp(self):
        super(InvitationCodeTestCase, self).setUp()
        self.invitation_code = mommy.make('sherpa.InvitationCode', skip_trace_price=Decimal('0.12'))

    def test_active_user_count_for_invitation_code(self):
        self.company1.invitation_code = self.invitation_code
        self.company1.save()
        self.company2.invitation_code = self.invitation_code
        self.company2.save()
        self.assertEqual(self.invitation_code.active_users.count(), 2)

    def test_active_subscriber_count_for_invitation_code(self):
        for company in [self.company1, self.company2]:
            company.invitation_code = self.invitation_code
            company.subscription_id = 'test1'
            company.subscription_status = Company.SubscriptionStatus.ACTIVE
            company.save()

        self.assertEqual(self.invitation_code.active_subscribers.count(), 2)

        self.company2.subscription_status = Company.SubscriptionStatus.CANCELED
        self.company2.save()
        self.assertEqual(self.invitation_code.active_subscribers.count(), 1)


class UserModelTestCase(CompanyTwoMixin, CompanyOneMixin, NoDataBaseTestCase):

    def test_user_is_created_with_profile(self):
        self.assertTrue(hasattr(self.master_admin_user, 'profile'))

    def test_avg_response_time_stat_against_company_hours(self):
        message = mommy.make(
            'sherpa.SMSMessage',
            response_from_rep=self.master_admin_user,
            response_time_seconds=120,
        )

        # dt is auto_now so gets set to current date/time on create, so we are setting it
        # manually here.
        message.dt = django_tz.now().replace(hour=10, minute=30)
        message.save(update_fields=['dt'])
        stats = self.master_admin_user.profile.send_stats()
        self.assertEqual(stats['avg_response_time'], 2)
        stats = self.master_admin_user.profile.send_stats(
            start_date=datetime.now().date() - timedelta(days=2),
            end_date=datetime.now().date() - timedelta(days=1),
        )
        self.assertEqual(stats['avg_response_time'], 0)

    def test_avg_response_time_stat_against_employee_hours(self):
        tz = pytz.timezone(self.company2_user.profile.company.timezone)
        utc_dt = django_tz.now()
        tz_dt = utc_dt.astimezone(tz)
        #  This message falls outside employees work hours.
        m = mommy.make(
            'sherpa.SMSMessage',
            response_from_rep=self.company2_user,
            response_time_seconds=120,
        )
        m.dt = tz_dt.replace(hour=6, minute=30)
        m.save()
        stats = self.company2_user.profile.send_stats()
        self.assertEqual(stats['avg_response_time'], 0)
        #  This message falls within employees work hours.
        m1 = mommy.make(
            'sherpa.SMSMessage',
            response_from_rep=self.company2_user,
            response_time_seconds=120,
        )
        m1.dt = tz_dt.replace(hour=14, minute=15)  # 2:15 PM
        m1.save()
        stats = self.company2_user.profile.send_stats()
        self.assertEqual(stats['avg_response_time'], 2)


class AuthenticationAPITestCase(SitesMixin, AllUserRoleMixin, CompanyOneMixin, NoDataBaseTestCase):

    def setUp(self):
        super(AuthenticationAPITestCase, self).setUp()
        self.register_payload = {
            'email': 'new_guy@asdf.com',
            'firstName': 'New',
            'lastName': 'Guy',
            'phone': '(312) 888-7777',
            'password': 'jfa912basdfio',
        }
        self.me_url = reverse('user-me')

    def test_user_can_login(self):
        url = reverse('jwt-create-override')
        payload = {'username': self.master_admin_user.username, 'password': 'georgepass'}
        response = self.client.post(url, payload)
        self.assertTrue(response.json().get('refresh') is not None)
        self.assertTrue(response.json().get('access') is not None)

    def test_user_logged_in_signal(self):
        initial_login_count = UserLogin.objects.count()
        url = reverse('jwt-create-override')
        payload = {'username': self.master_admin_user.username, 'password': 'georgepass'}
        self.client.post(url, payload)

        # Verify that the user's login was recorded
        self.assertEqual(UserLogin.objects.count(), initial_login_count + 1)

        # Verify incorrect login does nto record login
        payload['password'] = 'incorrect'
        self.client.post(url, payload)
        self.assertEqual(UserLogin.objects.count(), initial_login_count + 1)

    def test_user_refresh_token(self):
        url = reverse('jwt-create')
        payload = {'username': self.master_admin_user.username, 'password': 'georgepass'}
        response = self.client.post(url, payload)

        refresh_url = reverse('jwt-refresh')
        payload = {'refresh': response.json().get('refresh')}
        refresh_response = self.client.post(refresh_url, payload)
        self.assertTrue(refresh_response.json().get('access') is not None)

    def test_user_can_register(self):
        url = reverse('user-list')
        response = self.client.post(url, self.register_payload)
        self.assertEqual(response.status_code, 201)

        # Verify the created account is not active and awaiting verification.
        user = User.objects.get(email=self.register_payload['email'])
        self.assertFalse(user.is_active)

        # Activate the account with specific uid and token values.
        url = reverse('user-activation')
        payload = {
            'uid': utils.encode_uid(user.pk),
            'token': default_token_generator.make_token(user),
        }
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.json().get('refresh'), None)
        self.assertNotEqual(response.json().get('access'), None)
        user.refresh_from_db()
        self.assertTrue(user.is_active)

    def test_user_can_register_with_invite_code(self):
        url = reverse('user-list')
        body = self.register_payload.copy()
        code = 'test-register'
        mommy.make(
            'sherpa.InvitationCode',
            code=code,
            is_active=True,
        )
        body['invite_code'] = 'test-register'
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201)

        # Verify the created account is not active and awaiting verification.
        user = User.objects.get(email=body['email'])
        self.assertFalse(user.is_active)
        self.assertEqual(user.profile.invite_code, code)

    def test_user_can_get_self(self):
        response = self.master_admin_client.get(self.me_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('id'), self.master_admin_user.id)

    def test_user_can_get_company_data(self):
        response = self.master_admin_client.get(self.me_url)
        self.assertEqual(response.status_code, 200)
        company_data = response.json().get('company')
        self.assertEqual(company_data.get('id'), self.company1.id)

    def test_only_admin_user_can_invite(self):
        url = reverse('user-invite')
        payload = {
            'email': 'test-invite@test.com',
            'role': 'staff',
        }
        response = self.jrstaff_client.post(url, payload)
        self.assertEqual(response.status_code, 403)

        response = self.admin_client.post(url, payload)
        self.assertEqual(response.status_code, 201)

    def test_cant_invite_if_username_exists(self):
        # Need to change the email of a user so that it's not the same as username
        new_username = 'admin+2@asdf.com'
        self.admin_user.username = new_username
        self.admin_user.save()

        # Now try to invite with the username, and it should be handled correctly.
        url = reverse('user-invite')
        payload = {
            'email': new_username,
            'role': 'staff',
        }
        response = self.admin_client.post(url, payload)
        self.assertEqual(response.status_code, 400)

    def test_invited_users_can_register(self):
        url = reverse('user-invite')
        email = 'test-invite@test.com'
        payload = {
            'email': email,
            'role': 'staff',
        }
        response = self.admin_client.post(url, payload)
        user_id = response.json().get('id')
        user = User.objects.get(id=user_id)
        self.assertEqual(user.first_name, '')
        self.assertFalse(user.is_active)
        self.assertEqual(user.profile.company.id, self.admin_user.profile.company.id)

        payload = {
            'first_name': 'Test',
            'last_name': 'User',
            'phone': '3128887777',
            'password': 'ThisISaStr0ng!PswRd',
            'uid': utils.encode_uid(user.pk),
            'token': default_token_generator.make_token(user),
        }
        url = reverse('user-invitation', kwargs={'pk': user_id})
        response = self.client.post(url, payload)
        user.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(user.first_name, payload['first_name'])
        self.assertTrue(user.is_active)
        self.assertEqual(user.profile.phone, payload['phone'])

        # Now we should verify the invitation, get the uid/token from the email.
        email_body = mail.outbox[0].alternatives[0][0]
        uid_index = email_body.index("?uid=")
        token_index = email_body.index("&token=")
        uid = email_body[uid_index + 5: token_index]
        token = email_body[token_index + 7: token_index + 31]

        # Now we can send the request with the uid/token.
        url = reverse('user-verify-invite')
        invalid_query_params = [
            {'uid': uid},
            {'uid': 'invalid'},
            {'uid': uid, 'token': 'invalid'},
        ]
        for invalid_query_param in invalid_query_params:
            url += f'?uid={invalid_query_param.get(uid)}&token={invalid_query_param.get(token, "")}'
            response = self.client.get(url)
            self.assertEqual(response.status_code, 400)

        # Reset the url.
        valid_url = reverse('user-verify-invite') + f'?uid={uid}&token={token}'

        # Check that active users can't validate again.
        user = User.objects.get(email=email)
        user.is_active = True
        user.save()
        response = self.client.get(valid_url)
        self.assertEqual(response.status_code, 400)
        user.is_active = False
        user.save()

        # TODO: for some reason in test the token is not validating.
        # Now finally we can send a valid activation!
        # response = self.client.get(valid_url)
        # print(response.json())
        # self.assertEqual(response.status_code, 200)

    def test_user_can_request_password_reset(self):
        payload = {'email': self.master_admin_user.email}
        url = reverse('user-reset-password')
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 204)

    def test_user_can_verify_email(self):
        pass


class UserAPITestCase(StaffUserMixin, CompanyOneMixin, NoDataBaseTestCase):

    payment_token_url = reverse('user-payment-token')

    def test_unauthenticated_cant_get_payment_token(self):
        response = self.client.get(self.payment_token_url)
        self.assertEqual(response.status_code, 401)

    def test_staff_cant_get_payment_token(self):
        response = self.staff_client.get(self.payment_token_url)
        self.assertEqual(response.status_code, 403)

    def test_registered_can_get_payment_token(self):
        response = self.master_admin_client.get(self.payment_token_url)
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.json().get('token'), None)

    def test_unregistered_can_get_payment_token(self):
        self.company1.braintree_id = ''
        self.company1.save()
        response = self.master_admin_client.get(self.payment_token_url)
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.json().get('token'), None)


class AccountTaskTestCase(CompanyOneMixin, NoDataBaseTestCase):

    def test_modify_freshsuccess_account(self):
        # Since in test mode, does not actually send request to FS, just make sure no error.
        modify_freshsuccess_user(self.master_admin_user.id)


class ValidUserProfileTestCase(NoDataBaseTestCase):

    def create_user(self, **overrides):
        kwargs = dict(
            username='valid',
            email='user@user.com',
            password='testpassword',
            first_name='first',
            last_name='last',
        )
        kwargs.update(**overrides)
        return User.objects.create_user(**kwargs)

    def setUp(self):
        super(ValidUserProfileTestCase, self).setUp()
        self.valid_user = self.create_user()

    def test_valid_profiles(self):
        profiles_before = UserProfile.objects.count()
        edges = [
            {
                'username': 'nofirst',
                'email': 'nofirst@user.com',
                'first_name': '',
            },
            {
                'username': 'nolast',
                'email': 'nolast@user.com',
                'last_name': '',
            },
            {
                'username': 'noname',
                'email': 'noname@user.com',
                'first_name': '',
                'last_name': '',
            },
            {
                'username': 'dupeemailexact1',
                'email': 'noname@user.com',
            },
            {
                'username': 'dupeemailexact2',
                'email': 'noname@user.com',
            },
            {
                'username': 'dupeemailiexact',
                'email': 'NoName@User.com',
            },
            {
                'username': 'staff',
                'email': 'admin@staff.com',
                'is_staff': True,
            },
            {
                'username': 'noprofile',
                'email': 'noprofile@user.com',
            },
        ]
        for kwargs in edges:
            user = self.create_user(**kwargs)
            if kwargs['username'] == 'noprofile':
                user.profile.delete()

        profiles_after = UserProfile.objects.valid().count()

        self.assertEqual(profiles_after, profiles_before)
