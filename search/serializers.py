from rest_framework import serializers

from sherpa.models import Prospect


class StackerCriteriaSerializer(serializers.Serializer):
    option = serializers.ChoiceField(
        choices=['any', 'all'],
        required=False,
        default='any',
        help_text="Determines how to handle the `included` or `excluded` prospect statuses.",
    )
    criteria = serializers.ChoiceField(
        choices=['tagBefore', 'tagBetween', 'tagAfter'],
        required=False,
        allow_blank=True,
        help_text="Search on prospects lookup name.",
    )
    date_from = serializers.DateField(
        input_formats=["%m/%d/%Y", "iso-8601"],
        required=False,
        allow_null=True,
    )
    date_to = serializers.DateField(
        input_formats=["%m/%d/%Y", "iso-8601"],
        required=False,
        allow_null=True,
    )


class StackerPropertyTagsSerializer(StackerCriteriaSerializer):
    """
    Filter based on the property tags for the Stacker filters.
    """
    include = serializers.ListField(
        child=serializers.IntegerField(min_value=0),
        required=False,
        allow_empty=True,
        min_length=0,
        help_text="Tag IDs to include in filter.",
    )
    exclude = serializers.ListField(
        child=serializers.IntegerField(min_value=0),
        required=False,
        allow_empty=True,
        min_length=0,
        help_text="Tag IDs to exclude in filter.",
    )


class StackerQuerySerializer(serializers.Serializer):
    """
    Query search on the stacker index.  Allows a more granular search as opposed to a general
    search query string.
    """
    name = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Search on prospects name.",
    )
    address = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Search on property street address.",
    )
    city = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Search on property city.",
    )
    phone = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Search on prospects phone.",
    )


class StackerProspectStatusSerilizer(StackerCriteriaSerializer):
    """
    prospect status request filter payload.
    """
    include = serializers.MultipleChoiceField(
        choices=['isBlocked', 'doNotCall', 'isPriority', 'isQualifiedLead', 'wrongNumber'],
        required=False,
        allow_blank=True,
        help_text="Prospect statuses to include in filter.",
    )
    exclude = serializers.MultipleChoiceField(
        choices=['isBlocked', 'doNotCall', 'isPriority', 'isQualifiedLead', 'wrongNumber'],
        required=False,
        allow_blank=True,
        help_text="Prospect statuses to exclude in filter.",
    )


class StackerDateRangeFilterSerializer(serializers.Serializer):
    """
    Used in the filtering of range date in elasticsearch.
    """
    gte = serializers.DateField(
        input_formats=["%m/%d/%Y", "iso-8601"],
        required=False,
        allow_null=True,
    )
    lte = serializers.DateField(
        input_formats=["%m/%d/%Y", "iso-8601"],
        required=False,
        allow_null=True,
    )


class StackerFiltersSerializer(serializers.Serializer):
    """
    Filters to apply to the stacker indexes.
    """
    prospect_id = serializers.ListField(
        child=serializers.IntegerField(min_value=0),
        required=False,
        allow_empty=True,
        help_text="List of prospect IDs to filter on.",
    )
    property_id = serializers.ListField(
        child=serializers.IntegerField(min_value=0),
        required=False,
        allow_empty=True,
        help_text="List of property IDs to filter on.",
    )
    address_id = serializers.ListField(
        child=serializers.IntegerField(min_value=0),
        required=False,
        allow_empty=True,
        help_text="List of address IDs to filter on.",
    )
    state = serializers.ListField(
        child=serializers.CharField(max_length=2),
        required=False,
        allow_empty=True,
        help_text="List of state abbreviations to filter on.",
    )
    zip_code = serializers.CharField(
        max_length=5,
        required=False,
        allow_blank=True,
        help_text="Zip code to filter on.",
    )
    last_sold_date = StackerDateRangeFilterSerializer(required=False)
    skiptrace_date = StackerDateRangeFilterSerializer(required=False)
    distress_indicators = serializers.ListField(
        child=serializers.IntegerField(min_value=0),
        required=False,
        allow_empty=True,
        min_length=1,
        max_length=25,
        help_text="List of included distress indicators counts.",
    )
    lead_stage_id = serializers.ListField(
        child=serializers.IntegerField(required=False),
        required=False,
        min_length=1,
    )
    is_blocked = serializers.BooleanField(required=False)
    do_not_call = serializers.BooleanField(required=False)
    is_priority = serializers.BooleanField(required=False)
    is_qualified_lead = serializers.BooleanField(required=False)
    wrong_number = serializers.BooleanField(required=False)
    opted_out = serializers.BooleanField(required=False)
    owner_verified_status = serializers.MultipleChoiceField(
        choices=['open', 'verified', 'unverified'],
        required=False,
    )
    is_archived = serializers.BooleanField(
        required=False,
        default=False,
    )
    is_reminder = serializers.BooleanField(
        required=False,
    )
    recently_vacant = serializers.BooleanField(
        required=False,
    )
    skip_traced = serializers.NullBooleanField(
        required=False,
        help_text="Filters those who have a phone number.",
    )
    in_campaign = serializers.BooleanField(
        required=False,
        help_text="Filters documents based on if they're in a campaign.",
    )
    in_dm_campaign = serializers.BooleanField(
        required=False,
        help_text="Filters documents based on if they're in a dm campaign.",
    )
    inbound_date = StackerDateRangeFilterSerializer(required=False)
    outbound_date = StackerDateRangeFilterSerializer(required=False)
    prospect_status = StackerProspectStatusSerilizer(required=False)
    property_tags = StackerPropertyTagsSerializer(required=False)
    criteria = serializers.ChoiceField(
        choices=['declared_prior_to', 'declared_between', 'declared_after',
                 'tag_prior_to', 'tag_between', 'tag_after'],
        required=False,
        allow_blank=True,
        help_text="Search on prospects lookup name.",
    )
    date_from = serializers.DateField(
        input_formats=["%m/%d/%Y", "iso-8601"],
        required=False,
        allow_null=True,
    )
    date_to = serializers.DateField(
        input_formats=["%m/%d/%Y", "iso-8601"],
        required=False,
        allow_null=True,
    )
    first_import_date = StackerDateRangeFilterSerializer(required=False)
    last_import_date = StackerDateRangeFilterSerializer(required=False)

    def to_internal_value(self, data):  # noqa: C901
        data = super().to_internal_value(data)

        # Prospect stacker index has property "owner_verified_status" as "owner_status"
        if data.get("owner_verified_status", None) is not None:
            data["owner_status"] = list(data["owner_verified_status"])
            del data["owner_verified_status"]

        return data

    def validate_owner_status(self, value):
        if value:
            return list(value)
        return []


class StackerSearchAfterSerializer(serializers.Serializer):
    """
    Determines the pagination for the stacker search.
    """
    properties = serializers.ListField(
        required=False,
        allow_empty=True,
        help_text="Determines the next list of property documents to pull based on the sorting provided.",  # noqa E501
    )
    prospects = serializers.ListField(
        required=False,
        allow_empty=True,
        help_text="Determines the next list of prospect documents to pull based on the sorting provided.",  # noqa E501
    )


class StackerSearchSortRequestSerializer(serializers.Serializer):
    """
    Serializer to handle stacker sorting.
    """
    field = serializers.ChoiceField(
        choices=["tags", "campaigns", "last_contact", "created_date", "last_modified", "_score"],
        required=True,
    )
    order = serializers.ChoiceField(
        choices=["asc", "desc"],
        required=False,
        default="desc",
    )


class StackerSearchRequestSerializer(serializers.Serializer):
    """
    Serializer combining both the query search parameters and the filter parameters along with
    sorting and paging that will be used on the stacker indexes.
    """
    size = serializers.IntegerField(
        required=False,
        min_value=10,
        max_value=100,
        default=100,
        help_text="Total number of returned documents.",
    )
    query = StackerQuerySerializer(required=False)
    filters = StackerFiltersSerializer(required=False)
    sort = StackerSearchSortRequestSerializer(required=True)
    search_after = StackerSearchAfterSerializer(required=False)


class StackerSearchResultSerializer(serializers.Serializer):
    """
    Stacker results.
    """
    results = serializers.ListField(child=serializers.DictField(read_only=True))
    total = serializers.IntegerField(read_only=True)
    search_after = serializers.ListField(child=serializers.CharField(read_only=True))


class StackerSearchResultProspectSerializer(StackerSearchResultSerializer):
    def to_representation(self, instance):
        data = super().to_representation(instance)

        for result in data["results"]:
            owner_status = result.get("owner_status", None)
            if owner_status is not None:
                del result["owner_status"]
                result["owner_verified_status"] = owner_status

        return data


class StackerSearchCountsSerizlier(serializers.Serializer):
    """
    Contains the total counts per company per index.
    """
    prospects = serializers.IntegerField(read_only=True)
    properties = serializers.IntegerField(read_only=True)


class StackerSearchResponseSerializer(serializers.Serializer):
    """
    Stacker response serializer.
    """
    prospects = StackerSearchResultProspectSerializer(read_only=True)
    properties = StackerSearchResultSerializer(read_only=True)
    counts = StackerSearchCountsSerizlier(read_only=True)


class BaseStackerActionSerializer(serializers.Serializer):
    """
    Base serializer which tells us what type of model should be modified.
    """
    type = serializers.ChoiceField(
        choices=['prospect', 'property'],
        required=True,
        help_text="Determines what IDs to pull from the query/filter found documents or what the list of IDs provided is.",  # noqa E501
    )


class BaseStackerBulkActionSerializer(BaseStackerActionSerializer):
    """
    Base serializer for bulk actions that requires either the search object or a list of IDs.
    """
    search = StackerSearchRequestSerializer(required=False)
    group = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        min_length=2,
        max_length=2,
        help_text="A 2 size array of starting ID and size",
    )
    id_list = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=True,
        help_text="List of IDs to modify via the bulk action.",
    )
    exclude = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=True,
        allow_null=True,
        help_text="List of IDs to exclude from the search results.",
    )


class StackerBulkArchiveSerializer(BaseStackerBulkActionSerializer):
    """
    Archives a group of prospects or properties.
    """
    archive = serializers.BooleanField(required=True)


class StackerSingleArchiveSerializer(BaseStackerActionSerializer):
    """
    Achives a single instance of prospect or property.
    """
    archive = serializers.BooleanField(required=True)


class StackerBulkPropertyTagSerializer(serializers.Serializer):
    """
    Tags found properties.
    """
    search = StackerSearchRequestSerializer(required=False)
    id_list = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=True,
        help_text="List of IDs to modify via the bulk action.",
    )
    tags = serializers.ListField(
        child=serializers.IntegerField(min_value=0),
        required=True,
        allow_empty=False,
        min_length=1,
    )


class StackerSingleProspectTagSerializer(serializers.Serializer):
    """
    Tags a specific prospect.
    """
    is_blocked = serializers.NullBooleanField(required=False)
    do_not_call = serializers.NullBooleanField(required=False)
    is_priority = serializers.NullBooleanField(required=False)
    is_qualified_lead = serializers.NullBooleanField(required=False)
    wrong_number = serializers.NullBooleanField(required=False)
    opted_out = serializers.NullBooleanField(required=False)
    tags = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=True,
        help_text="List of Tag IDs to add via the bulk action.",
    )


class StackerBulkProspectTagSerializer(StackerSingleProspectTagSerializer):
    """
    Tags found prospects.
    """
    search = StackerSearchRequestSerializer(required=False)
    id_list = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=True,
        help_text="List of Prospect IDs to modify via the bulk action.",
    )


class StackerSinglePropertyTagSerializer(serializers.Serializer):
    """
    Tags a specifc property.
    """
    tags = serializers.ListField(
        child=serializers.IntegerField(min_value=0),
        required=True,
        allow_empty=False,
        min_length=1,
    )


class StackerBulkPushToCampaignSerializer(BaseStackerBulkActionSerializer):
    """
    Pushes prospects into a campaign.
    """
    campaign_id = serializers.IntegerField(
        required=False,
        min_value=0,
        help_text="The campaign ID to push to.",
    )
    market_id = serializers.IntegerField(
        required=False,
        min_value=0,
        help_text="The ID of the market to use when creating a campaign.",
    )
    import_type = serializers.ChoiceField(
        choices=['all', 'new'],
        required=True,
    )
    campaign_name = serializers.CharField(
        max_length=64,
        required=False,
        allow_blank=True,
        help_text="The name of the new campaign to create.",
    )
    tags = serializers.ListField(
        child=serializers.IntegerField(min_value=0),
        required=False,
        allow_empty=True,
    )


class StackerBulkPushToDirectMailSerializer(BaseStackerBulkActionSerializer):
    """
    Pushes prospects into a direct mail campaign.
    """
    campaign_name = serializers.CharField(
        max_length=64,
        help_text="The name of the new direct mail campaign to create.",
    )
    budget_per_order = serializers.DecimalField(
        decimal_places=2,
        max_digits=10,
        help_text="Estimated budget per order.",
        required=False,
    )
    drop_date = serializers.DateField(help_text="Drop date for direct mail campaign.")
    note_for_processor = serializers.CharField(
        required=False,
        help_text="Note to send processor.",
    )
    template = serializers.CharField(help_text="Template id to use for direct mail campaign.")
    creative_type = serializers.CharField(default="postcard")
    from_id = serializers.IntegerField(help_text="User ID to use in from")
    return_address = serializers.CharField(
        max_length=100,
        help_text="Return street address for direct mail campaign",
    )
    return_city = serializers.CharField(
        max_length=64,
        help_text="Return address city for direct mail campaign",
    )
    return_state = serializers.CharField(
        max_length=32,
        help_text="Return address state for direct mail campaign",
    )
    return_zip = serializers.CharField(
        max_length=16,
        help_text="Return address zip code for direct mail campaign",
    )
    return_phone = serializers.CharField(help_text="Agent's phone for direct mail campaign")
    owner = serializers.IntegerField(
        help_text="Owner profile ID.",
        required=False,
    )
    access = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        allow_empty=True,
    )
    podio_email = serializers.EmailField(required=False)
    zapier_webhook = serializers.URLField(required=False)
    tags = serializers.ListField(
        child=serializers.IntegerField(min_value=0),
        required=False,
        allow_empty=True,
    )


class StackerAddressDisplaySerializer(serializers.Serializer):
    property_address = serializers.CharField(max_length=256, required=False)
    mailing_address = serializers.CharField(max_length=256, required=False, allow_blank=True)


class StackerTagInfoSerializer(serializers.Serializer):
    total = serializers.IntegerField(required=False)
    distress_indicators = serializers.IntegerField(required=False)


class StackerPropertyRelativesSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=128, required=False, allow_blank=True)
    numbers = serializers.ListField(
        child=serializers.CharField(max_length=12, allow_blank=True),
        required=False,
    )


class StackerPropertyInfoSerializer(serializers.Serializer):
    tags = StackerTagInfoSerializer(required=False)
    relatives = StackerPropertyRelativesSerializer(many=True, required=False)
    legal_description = serializers.CharField(max_length=256, required=False, allow_null=True)
    year_built = serializers.IntegerField(required=False, allow_null=True)
    sale_date = serializers.DateField(required=False, allow_null=True)
    sale_price = serializers.DecimalField(
        max_digits=20,
        decimal_places=4,
        required=False,
        allow_null=True,
    )
    bath_count = serializers.IntegerField(required=False, allow_null=True)
    bath_partial_count = serializers.IntegerField(required=False, allow_null=True)
    bedrooms_count = serializers.IntegerField(required=False, allow_null=True)
    building_sqft = serializers.IntegerField(required=False, allow_null=True)
    lot_sqft = serializers.DecimalField(
        max_digits=20,
        decimal_places=4,
        required=False,
        allow_null=True,
    )
    type = serializers.CharField(max_length=64, required=False, allow_null=True)
    loan = serializers.DictField(required=False)
    is_vacant = serializers.NullBooleanField(required=False)
    street_view_url = serializers.URLField(required=False, allow_blank=True, allow_null=True)
    zillow_link = serializers.URLField(required=False, allow_blank=True, allow_null=True)


class StackerProspectInfoSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False)
    first_name = serializers.CharField(max_length=32, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=64, required=False, allow_blank=True)
    phone_raw = serializers.CharField(max_length=12, required=False)
    do_not_call = serializers.NullBooleanField(required=False)
    is_priority = serializers.NullBooleanField(required=False)
    is_blocked = serializers.NullBooleanField(required=False)
    is_qualified_lead = serializers.NullBooleanField(required=False)
    wrong_number = serializers.NullBooleanField(required=False)
    opted_out = serializers.NullBooleanField(required=False)
    owner_verified_status = serializers.CharField(required=False)
    total_campaigns = serializers.IntegerField(required=False)
    lead_stage = serializers.IntegerField(required=False, allow_null=True)
    campaign_id = serializers.ListField(required=False, allow_null=True)
    last_contact = serializers.DateTimeField(required=False, allow_null=True)


class StackerPropertyResponseSerializer(serializers.Serializer):
    """
    Serializer that is used in the `property/data` endpoint.
    """
    address = StackerAddressDisplaySerializer(required=False)
    property_data = StackerPropertyInfoSerializer(required=False)
    prospects = StackerProspectInfoSerializer(required=False, many=True)


class StackerBulkPushToDirectMailCampaignSerializer(BaseStackerBulkActionSerializer):
    """
    Serializer to create Direct mail campaign as Draft.
    """
    campaign_id = serializers.IntegerField(
        required=False,
        min_value=0,
        help_text="The campaign ID to push to.",
    )
    market_id = serializers.IntegerField(
        required=False,
        min_value=0,
        help_text="The ID of the market to use when creating a campaign.",
    )
    import_type = serializers.ChoiceField(
        choices=['all', 'new'],
        required=True,
    )
    campaign_name = serializers.CharField(
        max_length=64,
        required=False,
        allow_blank=True,
        help_text="The name of the new campaign to create.",
    )
    tags = serializers.ListField(
        child=serializers.IntegerField(min_value=0),
        required=False,
        allow_empty=True,
    )
    budget_per_order = serializers.DecimalField(
        decimal_places=2,
        max_digits=10,
        help_text="Estimated budget per order.",
    )
    drop_date = serializers.DateField(help_text="Drop date for direct mail campaign.")
    note_for_processor = serializers.CharField(help_text="Note to send processor.")
    template = serializers.CharField(help_text="Template id to use for direct mail campaign.")
    creative_type = serializers.CharField(default="postcard")
    from_id = serializers.IntegerField(help_text="User ID to use in from")
    return_address = serializers.CharField(
        max_length=100,
        help_text="Return street address for direct mail campaign",
    )
    return_city = serializers.CharField(
        max_length=64,
        help_text="Return address city for direct mail campaign",
    )
    return_state = serializers.CharField(
        max_length=32,
        help_text="Return address state for direct mail campaign",
    )
    return_zip = serializers.CharField(
        max_length=16,
        help_text="Return address zip code for direct mail campaign",
    )
    return_phone = serializers.CharField(help_text="Agent's phone for direct mail campaign")
    owner = serializers.IntegerField(
        help_text="Owner profile ID.",
        required=False,
    )
    access = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        allow_empty=True,
    )
    podio_email = serializers.EmailField(required=False)
    zapier_webhook = serializers.URLField(required=False)


class ResponseDuplicatedProspectSerializer(serializers.ModelSerializer):
    """
    Serializer used in retrive prospect information while pushing
    from PS to DM as draft.
    """
    sherpa_phone_number = serializers.SerializerMethodField()
    is_duplicated = serializers.SerializerMethodField()

    def get_sherpa_phone_number(self, obj):
        return obj.sherpa_phone_number_obj.phone if obj.sherpa_phone_number_obj else None

    def get_is_duplicated(self, obj):
        dup = self.context.get('deduped_id_list')
        if obj.id in dup:
            return False
        return True

    class Meta:
        model = Prospect
        fields = (
            'id',
            'first_name',
            'last_name',
            'name',
            'phone_display',
            'property_address',
            'property_city',
            'property_state',
            'property_zip',
            'lead_stage',
            'agent',
            'do_not_call',
            'emailed_to_podio',
            'is_priority',
            'is_qualified_lead',
            'owner_verified_status',
            'reminder_date_local',
            'reminder_agent',
            'pushed_to_zapier',
            'sherpa_phone_number',
            'zillow_link',
            'campaigns',
            'token',
            'tags',
            'is_blocked',
            'is_duplicated',
        )
