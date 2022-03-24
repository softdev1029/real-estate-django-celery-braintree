import uuid

from core import models


class ProspectManager(models.Manager):
    def search(self, user, filters=None):
        from prospects.utils import ProspectSearch
        search = ProspectSearch(
            filters['search_input'],
            user,
            params=filters['extra'],
        )
        search.search()
        return search.result

    def create_from_skip_trace_property(self, skip_trace_property):
        """
        Create `Prospect` objects  from `SkipTraceProperty` and `Property`

        :param skip_trace_property: `SkipTraceProperty` to create `Prospect` objects from
        """
        skip_trace_property.create_property()
        data = skip_trace_property.get_data_from_skip_trace_property()
        self.create_from_phones(
            skip_trace_property.phone_list,
            data,
            prop=skip_trace_property.prop,
            skip_trace_prop=skip_trace_property,
        )

    def create_from_phones(
            self,
            phones,
            data,
            upload=None,
            prop=None,
            skip_trace_prop=None,
    ):
        """
        Create `Prospect`s from a list of phones (already cleaned).

        :param phones: List of phones (already cleaned).
        :param data: dict with data to update `Prospect`
        :param prop: `Property` object to add to `Prospect`s created.
        :param upload: Upload object phones came from (ex UploadProspects)
        :param skip_trace_prop: `SkipTraceProperty` object phones came from
        """
        from sherpa.models import LitigatorList

        data['related_record_id'] = str(uuid.uuid4()) if len(phones) > 1 else ''
        has_litigator_list = LitigatorList.objects.filter(phone__in=phones).exists()
        if has_litigator_list:
            data['do_not_call'] = True
            data['phone_type'] = 'mobile'

        sort_order = 1
        company = upload.company if upload else skip_trace_prop.upload_skip_trace.company
        create_prospects = []
        update_prospects = []
        update_fields = set()
        for phone in phones:
            # Get or create `Prospect` for current phone.
            prospect, is_new_prospect, prospect_fields = self.__get_or_create_prospect_from_phone(
                phone,
                data,
                company,
                prop=prop,
            )

            # Update Prop if this is from a Skip Trace
            if skip_trace_prop and prospect.prop:
                prospect.prop.upload_skip_trace = skip_trace_prop.upload_skip_trace
                prospect.prop.save(update_fields=['upload_skip_trace'])

            # Add new Prospect to be created & existing ones to be updated.
            if is_new_prospect:
                create_prospects.append(prospect)
            else:
                update_fields.update(prospect_fields)
                prospect.upload_duplicate = True
                update_fields.add('upload_duplicate')

                update_prospects.append(prospect)

        # Bulk create or bulk update Prospects and run final update tasks.
        if create_prospects:
            self.bulk_create(create_prospects)
            self.__update_new_or_updated_prospects(
                create_prospects,
                upload,
                sort_order,
                has_litigator_list,
                is_new_prospect=True,
            )
        if update_prospects:
            self.bulk_update(update_prospects, list(update_fields))
            self.__update_new_or_updated_prospects(
                update_prospects,
                upload,
                sort_order,
                has_litigator_list,
                is_new_prospect=False,
            )

    def create_from_data(
            self,
            data,
            upload=None,
            prop=None,
            skip_trace_prop=None,
    ):
        has_litigator_list = []
        sort_order = 1
        company = upload.company if upload else skip_trace_prop.upload_skip_trace.company

        data.update(self.__get_address_from_prop(prop))
        prospect_record, is_new_prospect = self.get_or_create(
            phone_raw='',
            company=company,
            prop=prop,
            **data,
        )

        self.__update_new_or_updated_prospects(
            [prospect_record],
            upload,
            sort_order,
            has_litigator_list,
            is_new_prospect=is_new_prospect,
        )

    def __get_or_create_prospect_from_phone(self, phone, data, company, prop=None):
        """
        Get or create `Prospect` for phone passed.

        :param phone: Cleaned phone
        :param prop: `Property` object to add to `Prospect`
        :param data: dict of data to save to `Prospect`
        :param company: `Company` to assign `Prospect` to
        :return: `Prospect` object and Boolean to indicate if new `Prospect`
        """
        from sherpa.models import Prospect

        prospect_record_list = self.filter(phone_raw=phone, company=company).values_list(
            'id', 'do_not_call')
        is_new_prospect = False
        prospect_record = None
        data.update(self.__get_address_from_prop(prop))

        # If there's only one matching `Prospect`, use that one.
        # If there's more than one matching `Prospect`, check to see if there's a do not call.
        if len(prospect_record_list) == 1:
            prospect_record = prospect_record_list[0]
        elif len(prospect_record_list) > 1:
            for p in prospect_record_list:
                prospect_record = p
                if p[1]:
                    # if a prospect is DNC then that is the one to use
                    break
        else:
            # No matching `Prospect` objects found, create a new one.
            is_new_prospect = True
            prospect_record = Prospect(phone_raw=phone, company=company, **data)

        if prospect_record and not is_new_prospect:
            prospect_record = self.get(id=prospect_record[0])
            # Update with data from upload (including tags).
            for field, value in data.items():
                setattr(prospect_record, field, value)

        return prospect_record, is_new_prospect, list(data.keys())

    @staticmethod
    def __update_new_or_updated_prospects(
            prospect_list,
            upload,
            sort_order,
            has_litigator_list,
            is_new_prospect,
    ):
        """
        Run final tasks including adding to campaign, adding tags, and validating address.
        """
        from prospects.tasks import update_prospect_after_create, update_prospect_async
        for prospect in prospect_list:
            # If we aren't yet pushing to campaign, these tasks can run in the background
            # to speed things up. If we are, then need to run synchronously to avoid metrics
            # changing after upload appears to be completed (which could be confusing to the user).
            args = [
                prospect.id,
                upload.id if upload else None,
                sort_order,
                is_new_prospect,
                has_litigator_list,
            ]
            if upload:
                update_prospect_after_create(*args)
            else:
                update_prospect_after_create.delay(*args)

            # The rest of these tasks can always be asynchronous
            update_prospect_async.delay(prospect.id)

        return sort_order

    @staticmethod
    def __get_address_from_prop(prop):
        """
        Get address fields from prop. Will be deprecated- get address from `Property`
        """
        data = dict()
        update_fields = list()
        if prop:
            data['prop_id'] = prop.id
            for field in ['address', 'city', 'state', 'zip_code']:
                val = field if field != 'zip_code' else 'zip'
                data[f'property_{val}'] = getattr(prop.address, field)
                update_fields.append(f'property_{val}')
                if prop.mailing_address:
                    update_fields.append(f'mailing_{val}')
                    data[f'mailing_{val}'] = getattr(prop.mailing_address, field)
        return data
