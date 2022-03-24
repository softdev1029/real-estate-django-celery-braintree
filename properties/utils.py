from properties.models import (
    Address,
    AttomPreForeclosure,
    AttomRecorder,
    PropertyTag,
)


def get_or_create_address(data):
    """
    Get or create the address instance based on the smarty streets data.

    :param data: dictionary of data from smarty streets that is used to find/create an address.
    :return: instance of `properties.Address` or None
    """
    required_fields = ['street', 'city', 'state']
    if not all([data.get(required_field) for required_field in required_fields]):
        return None

    property_address_record, _ = Address.objects.get_or_create(
        address=data.get('street')[:100],
        city=data.get('city')[:64],
        state=data.get('state')[:32],
        defaults={
            'zip_code': data.get('zip')[:5] if data.get('zip') else None,
        },
    )

    # If the zip code for the address has changed, it should be updated.
    if data.get('zip') and data.get('zip')[:5] != property_address_record.zip_code:
        property_address_record.zip_code = data.get('zip')[:5]
        property_address_record.save(update_fields=['zip_code'])

    return property_address_record


def get_or_create_attom_tags(address, company):
    """
    Get or create property tags based on `properties.AttomAssessor` records.

    :param address instance: `Address` model instance.
    :param company instance: `Company` model instance.
    :return: ids of `properties.PropertyTag` model or [].
    """
    tag_ids = []
    tag_names = []
    attom_assessor = address.attom
    if attom_assessor:
        attom_log = AttomRecorder.objects.filter(attom_id=attom_assessor). \
            order_by('-transaction_id').first()
        attom_foreclosure = AttomPreForeclosure.objects.filter(attom_id=attom_assessor). \
            order_by('-transaction_id').first()

        if attom_log and attom_log.quitclaim_flag:
            tag_names.append('Quitclaim')
        if attom_foreclosure and attom_foreclosure.foreclosure_recording_date:
            tag_names.append('Pre-foreclosure')

        tag_ids = PropertyTag.objects.filter(company=company, name__in=tag_names). \
            values_list('pk', flat=True)
        if len(tag_names) != len(tag_ids):
            company.create_property_tags()
            tag_ids = PropertyTag.object.filter(company=company, name__in=tag_names). \
                values_list('pk', flat=True)

    return tag_ids
