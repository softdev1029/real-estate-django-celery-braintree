from celery import shared_task

from django.contrib.auth import get_user_model

from services.freshsuccess import FreshsuccessClient
from sherpa.utils import convert_epoch


User = get_user_model()


@shared_task
def modify_freshsuccess_user(user_id):
    """
    Create a new user in freshsuccess.
    """
    user = User.objects.get(id=user_id)
    company = user.profile.company
    client = FreshsuccessClient()
    payload = {
        'account_id': company.id,
        'user_id': user.id,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'role': user.profile.role,
        'is_primary': user.profile.is_primary,
        'product_join_date': convert_epoch(user.date_joined),
        'email': user.email,
        'phone': user.profile.phone,
        'is_active': user.is_active,
    }
    client.create('account_users', payload)
