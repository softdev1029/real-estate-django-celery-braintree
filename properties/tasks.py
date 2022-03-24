
from celery import shared_task

from services.smarty import SmartyValidateAddresses
from sherpa.models import SiteSettings
from .models import AddressLastValidated, Property


@shared_task
def validate_addresses():
    """
    Validate addresses via Smarty Streets
    """
    # Number of properties to validate
    site_settings = SiteSettings.load()
    limit = site_settings.smarty_streets_nightly_run_count
    subtasks = 10

    last_checked = AddressLastValidated.load()
    last_checked_id = last_checked.property_id

    last_checked_id = last_checked_id if last_checked_id else -1
    properties = Property.objects.filter(pk__gt=last_checked_id).order_by('pk')[:limit]

    # We need to start over if we've checked all properties.
    total_remaining_properties = limit - properties.count()
    if total_remaining_properties:
        remaining_properties = Property.objects.all().order_by('pk')[:total_remaining_properties]
        properties = properties | remaining_properties

    last_prop = None
    execute_validation_data = list()

    for count, prop in enumerate(properties):
        execute_validation_data.append(prop)
        if count % limit / subtasks:
            execute_address_vacancy_validation.delay(execute_validation_data)
            execute_validation_data = list()
        last_prop = prop.pk

    # Handle the case that we set a limit not divisible by the number of subtasks
    if len(execute_validation_data):
        execute_address_vacancy_validation.delay(execute_validation_data)

    last_checked.property_id = last_prop
    last_checked.save()


@shared_task
def execute_address_vacancy_validation(properties):
    """
    Validate a set of properties to update their 'vacancy' status.

    Since we are not saving address info, this only updates vacancy.
    It would make sense to do this here, except 1) We have already validated
    this address and it isn't likely to change and 2) It would take longer to run.
    """
    validator = SmartyValidateAddresses(properties, has_submitted_prefix=False, is_property=True)
    validator.validate_addresses()
