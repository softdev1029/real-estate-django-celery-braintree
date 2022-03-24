import math
import random

from faker import Faker

from django.conf import settings
from django.core.management.base import BaseCommand

from campaigns.models import CampaignAggregatedStats
from properties.models import Address, Property, PropertyTag, PropertyTagAssignment
from sherpa.models import (
    Campaign,
    CampaignProspect,
    Market,
    Prospect,
    SkipTraceProperty,
    UserProfile,
)


class Command(BaseCommand):
    """
    Generates fake addresses, properties, and prospects.
    """
    def add_arguments(self, parser):
        parser.add_argument('--cid', nargs='?', type=int, default=1)
        parser.add_argument('--campaigns', nargs='?', type=int, default=2)
        parser.add_argument('--fill', nargs='?', type=float, default=0.5)
        parser.add_argument('--amount', nargs='?', type=int, default=100)

    def handle(self, *args, **options):
        if not settings.DEBUG:
            print('You cannot use this command while DEBUG mode is off.')
            return
        cid = options['cid']
        amount = options['amount']
        campaign_count = options['campaigns']
        fill = options['fill']
        print(f'Company ID {cid}')

        fake = Faker()

        addresses = create_addresses(fake, amount)
        props = create_properties(cid, addresses)
        skips = create_skiptraceproperties(fake, props)
        prospects = create_prospects(fake, skips)
        campaigns = create_campaigns(fake, cid, campaign_count)
        create_campaignprospects(prospects, campaigns, fill)
        return


def create_addresses(fake, amount):
    """
    Creates fake addresses.
    """
    addresses = []
    print(f'Creating {amount} addresses.')
    for i in range(amount):
        addresses.append(
            Address(
                address=fake.street_address(),
                city=fake.city(),
                state=fake.state(),
                zip_code=fake.zipcode(),
            ),
        )
    Address.objects.bulk_create(addresses)
    return addresses


def create_properties(cid, addresses):
    """
    Creates properties based on fake addresses.
    """
    props = []
    print(f'Creating {len(addresses)} properties.')
    for address in addresses:
        props.append(
            Property(
                company_id=cid,
                address_id=address.id,
                mailing_address_id=address.id,
            ),
        )
    Property.objects.bulk_create(props)
    return props


def create_skiptraceproperties(fake, props):
    """
    Creates fake SkipTraceProperties instances based on prop addresses.
    """
    skips = []
    print(f'Creating {len(props)} skip trace properties.')
    for prop in props:
        first_name = fake.first_name()
        last_name = fake.last_name()
        skips.append(
            SkipTraceProperty(
                company_id=prop.company_id,
                prop=prop,
                returned_fullname=f'{first_name} {last_name}',
                returned_first_name=first_name,
                returned_last_name=last_name,
                returned_phone_1=fake.msisdn()[-10:],
                returned_phone_type_1='mobile',
                returned_phone_carrier_1='FAKE',
                returned_email_1=fake.ascii_company_email(),
                returned_address_1=prop.address.address,
                returned_city_1=prop.address.city,
                returned_state_1=prop.address.state,
                returned_zip_1=prop.address.zip_code,
                returned_ip_address=fake.ipv4(),
                returned_foreclosure_date=fake.date_between(start_date='-5y') if fake.pybool() else None,  # noqa: E501
                returned_lien_date=fake.date_between(start_date='-5y') if fake.pybool() else None,
                returned_judgment_date=fake.date_between(start_date='-5y') if fake.pybool() else None,  # noqa: E501
                validated_returned_address_1=prop.address.address,
                validated_returned_city_1=prop.address.city,
                validated_returned_state_1=prop.address.state,
                validated_returned_zip_1=prop.address.zip_code,
                age=random.randint(45, 82),
                deceased=fake.pybool(),
                bankruptcy=fake.date_between(start_date='-5y') if fake.pybool() else None,
                relative_1_first_name=fake.first_name(),
                relative_1_last_name=fake.last_name(),
                relative_1_phone1=fake.msisdn()[-10:],
                relative_2_first_name=fake.first_name(),
                relative_2_last_name=fake.last_name(),
                relative_2_phone1=fake.msisdn()[-10:],
            ),
        )
    SkipTraceProperty.objects.bulk_create(skips)
    return skips


def create_prospects(fake, skips):
    """
    Creates fake prospects based on fake SkipTraceProperties.  Attaches randomly amount of tags
    to properties.
    """
    tags = list(PropertyTag.objects.filter(
        company_id=skips[0].company_id).values_list('id', flat=True))
    prospects = []
    tag_assignments = []
    print('Assigning 0-3 random property tags to each property created.')
    print(f'Creating {len(skips)} prospects.')
    for skip in skips:
        tag_count = random.randint(0, 3)
        if tag_count:
            tag_list = tags.copy()
            for j in range(tag_count):
                tag_i = random.randint(0, len(tag_list) - 1)
                tag_assignments.append(
                    PropertyTagAssignment(
                        tag_id=tag_list.pop(tag_i),
                        prop_id=skip.prop.id,
                    ),
                )
        prospects.append(
            Prospect(
                company_id=skip.company_id,
                prop_id=skip.prop.id,
                first_name=skip.returned_first_name,
                last_name=skip.returned_last_name,
                phone_raw=skip.returned_phone_1,
                phone_type=skip.returned_phone_type_1,
                phone_carrier=skip.returned_phone_carrier_1,
                wrong_number=fake.pybool(),
                do_not_call=fake.pybool(),
                is_priority=fake.pybool(),
                is_qualified_lead=fake.pybool(),
                is_blocked=fake.pybool(),
            ),
        )
    PropertyTagAssignment.objects.bulk_create(tag_assignments)
    Prospect.objects.bulk_create(prospects)
    return prospects


def create_campaigns(fake, cid, campaign_count):
    """
    Creates fake campaigns.
    """
    print(f'Creating {campaign_count} campaigns.')
    campaigns = []
    market = Market.objects.filter(company_id=cid).first()
    user = UserProfile.objects.filter(company_id=cid).first().user

    for _ in range(campaign_count):
        campaigns.append(
            Campaign(
                company_id=cid,
                name=fake.license_plate(),
                market=market,
                created_by=user,
                campaign_stats=CampaignAggregatedStats.objects.create(),
            ),
        )
    Campaign.objects.bulk_create(campaigns)
    return campaigns


def create_campaignprospects(prospects, campaigns, fill):
    """
    Creates fake campaign prospects
    """
    campaign_prospect_count = math.floor(len(prospects) * fill / len(campaigns))
    print(f'Filling campaigns with {campaign_prospect_count} prospects each.')
    start = 0
    campaign_prospects = []
    for campaign in campaigns:
        for prospect in prospects[start:start + campaign_prospect_count]:
            campaign_prospects.append(
                CampaignProspect(
                    campaign=campaign,
                    prospect=prospect,
                ),
            )
        start += campaign_prospect_count
    CampaignProspect.objects.bulk_create(campaign_prospects)
    return campaign_prospects
