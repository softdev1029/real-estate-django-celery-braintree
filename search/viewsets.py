from itertools import groupby
from operator import itemgetter

from drf_yasg.utils import swagger_auto_schema

from django.conf import settings
from django.contrib.postgres.aggregates import ArrayAgg
from django.db.models import Count
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from companies.models import DownloadHistory
from companies.tasks import generate_download
from properties.models import Property
from sherpa.models import Prospect, SherpaTask
from sherpa.utils import get_upload_additional_cost
from skiptrace.models import UploadSkipTrace
from skiptrace.serializers import UploadSkipTraceResponseSerializer
from .indexes.stacker import StackerIndex
from .serializers import (
    BaseStackerActionSerializer,
    BaseStackerBulkActionSerializer,
    StackerBulkArchiveSerializer,
    StackerBulkPropertyTagSerializer,
    StackerBulkProspectTagSerializer,
    StackerBulkPushToCampaignSerializer,
    StackerBulkPushToDirectMailSerializer,
    StackerPropertyResponseSerializer,
    StackerSearchRequestSerializer,
    StackerSearchResponseSerializer,
    StackerSingleArchiveSerializer,
    StackerSinglePropertyTagSerializer,
    StackerSingleProspectTagSerializer,
)
from .tasks import (
    handle_property_tagging,
    handle_prospect_tag_update,
    handle_skip_trace_task,
    stacker_update_property_data,
    stacker_update_prospect_data,
)
from .utils import build_filters_and_queries


class StackerSearchViewSet(viewsets.ViewSet):
    """
    Viewset that handles the filtering and querying for PropertyStacker.
    """
    permission_classes = [IsAuthenticated]

    def get_model(self, model_name):
        """
        Returns the instance of ID of the model specified.

        :param model_name str: Name of the model to grab.  Choice is either "property" or
        "prospect".
        """
        if model_name not in ["prospect", "property"]:
            raise ValidationError("model_name value must be property or prospect.")
        return Prospect if model_name == "prospect" else Property

    def get_object_or_404(self, company_id, model, pk):
        try:
            return model.objects.get(company_id=company_id, pk=pk)
        except model.DoesNotExist:
            raise ValidationError("Could not locate object")

    def get_id_list(self, company_id, serializer, id_field_name=None, force_skip=False,
                    not_in_campaign=False, forced_type=None, source=None):
        """
        Gets the IDs from the specific stacker index based on the type sent to the serializer.

        :param company_id int: The company ID to filter on.
        :param serializer Serializer: The serializer of BaseStackerBulkActionSerializer.
        :param id_field_name string: Force use this field instead of the one based on model type.
        :param force_skip bool: Forces the filter to set the skip_traced filter to True.
        :param not_in_campaign bool: If true, only pulls those whose documents do not belong to a
        campaign.
        :param source string: Sets the query to only return this field name.
        """
        model_name = serializer.validated_data.get("type", forced_type)
        exclude_list = serializer.validated_data.get("exclude", [])
        id_field_name = id_field_name or f"{model_name}_id"
        query_filter = build_filters_and_queries(
            serializer,
            id_field_name=id_field_name,
            force_skip=force_skip,
            not_in_campaign=not_in_campaign,
            forced_type=forced_type,
        )
        search_body = StackerIndex.build_search_body(
            company_id,
            queries=query_filter["queries"],
            filters=query_filter["filters"],
            id_field_name=id_field_name,
            exclude=exclude_list,
            source=source or id_field_name,
        )
        id_list = StackerIndex.get_id_list(
            StackerIndex.property_index_name
            if model_name == "property"
            else StackerIndex.prospect_index_name,
            search_body,
            source or id_field_name,
        )
        if serializer.validated_data.get("group"):
            try:
                i = id_list.index(serializer.validated_data.get("group")[0])
            except ValueError:
                raise ValidationError({'group': 'Could not locate ID.'})
            id_list = id_list[i:i + serializer.validated_data.get("group")[1]]
        return id_list

    def remove_duplication_for_prospect_ids(self, id_list):
        """
        Method to eradicate the duplicates from DeDuplicationInterFace class.

        :param serializer Serializer: The Serializer object.
        :param id_list list: Duplicated ID requested from front end.
        """
        prospect_qs = list(
            Prospect.objects.filter(id__in=id_list).values("id", "prop_id").order_by("prop_id"),
        )
        id_list = []
        for _, value in groupby(prospect_qs, key=itemgetter("prop_id")):
            id_list.append(list(value)[0]["id"])
        return id_list

    @swagger_auto_schema(
        request_body=StackerSearchRequestSerializer,
        responses={200: StackerSearchResponseSerializer},
    )
    def create(self, request):
        serializer = StackerSearchRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        company_id = request.user.profile.company_id
        search_body = StackerIndex.build_search_body(
            company_id,
            queries=serializer.validated_data.get("query", {}),
            filters=serializer.validated_data.get("filters", {}),
        )
        search_results = StackerIndex.search_indexes(
            search_body,
            size=serializer.validated_data.get("size", 100),
            sort=serializer.validated_data.get("sort"),
            search_after=serializer.validated_data.get("search_after", []),
        )
        search_results["counts"] = StackerIndex.total_counts_by_company(company_id)

        return Response(StackerSearchResponseSerializer(search_results).data, status=201)

    @swagger_auto_schema(
        request_body=StackerBulkArchiveSerializer,
        responses={204: {}},
    )
    @action(methods=["patch"], detail=False, url_path="archive")
    def bulk_archive(self, request):
        """
        Will flip the archive status on the found documents
        """
        serializer = StackerBulkArchiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        id_list = self.get_id_list(request.user.profile.company_id, serializer)

        model = self.get_model(serializer.validated_data.get("type"))
        objects = model.objects.filter(
            company_id=request.user.profile.company_id,
            pk__in=id_list,
        )
        objects.update(is_archived=serializer.validated_data.get("archive"))

        changes = {"is_archived": serializer.validated_data.get("archive")}
        if serializer.validated_data.get("type") == "property":
            stacker_update_property_data.delay(id_list, changes)
        else:
            stacker_update_prospect_data.delay(id_list, changes)

        return Response({}, 204)

    @swagger_auto_schema(
        request_body=StackerSingleArchiveSerializer,
        responses={204: {}},
    )
    @action(methods=["patch"], detail=True, url_path="archive")
    def single_archive(self, request, pk):
        """
        Will flip the archive status on the provided ID.
        """
        serializer = StackerSingleArchiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        obj = self.get_object_or_404(
            request.user.profile.company_id,
            self.get_model(serializer.validated_data.get("type")),
            pk,
        )
        obj.is_archived = serializer.validated_data.get("archive")
        obj.save(update_fields=["is_archived"])

        changes = {"is_archived": serializer.validated_data.get("archive")}
        if serializer.validated_data.get("type") == "property":
            stacker_update_property_data.delay(pk, changes)
        else:
            stacker_update_prospect_data.delay(pk, changes)

        return Response({}, 204)

    @swagger_auto_schema(
        method="post",
        request_body=StackerBulkPropertyTagSerializer,
        responses={204: {}},
    )
    @swagger_auto_schema(
        method="delete",
        request_body=StackerBulkPropertyTagSerializer,
        responses={204: {}},
    )
    @action(methods=["post", "delete"], detail=False, url_path="property/tag")
    def bulk_property_tag(self, request):
        """
        Update the tags on the found property documents.
        """
        self.handle_property_tagging(request)

        return Response({}, 204)

    @swagger_auto_schema(
        method="post",
        request_body=StackerBulkProspectTagSerializer,
        responses={204: {}},
    )
    @action(methods=["post", "delete"], detail=False, url_path="prospect/tag")
    def bulk_prospect_tag(self, request):
        """
        Update the tags on the found property documents.
        """
        self.handle_prospect_tagging(request)

        return Response({}, 204)

    @swagger_auto_schema(
        method="post",
        request_body=StackerSinglePropertyTagSerializer,
        responses={204: {}},
    )
    @swagger_auto_schema(
        method="delete",
        request_body=StackerSinglePropertyTagSerializer,
        responses={204: {}},
    )
    @action(methods=["post", "delete"], detail=True, url_path="property/tag")
    def single_property_tag(self, request, pk):
        """
        Update the tags on the provided property ID.
        """
        self.handle_property_tagging(request, pk)

        return Response({}, 204)

    @swagger_auto_schema(
        method="post",
        request_body=StackerSingleProspectTagSerializer,
        responses={204: {}},
    )
    @action(methods=["post", "delete"], detail=True, url_path="prospect/tag")
    def single_prospect_tag(self, request, pk):
        """
        Update the tags on the provided prospect ID.
        """
        self.handle_prospect_tagging(request, pk)

        return Response({}, 204)

    @swagger_auto_schema(
        request_body=BaseStackerBulkActionSerializer,
        responses={204: {}},
    )
    @action(methods=["post"], detail=False, url_path="export")
    def bulk_export(self, request):
        """
        Exports the found documents
        """
        serializer = BaseStackerBulkActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        id_list = self.get_id_list(request.user.profile.company_id, serializer)
        if not id_list:
            return Response({}, 204)

        uuid = self.handle_export(
            request.user.id,
            request.user.profile.company_id,
            id_list,
            serializer.validated_data.get("type"),
        )

        return Response({"id": uuid}, 201)

    @swagger_auto_schema(
        request_body=BaseStackerActionSerializer,
        responses={204: {}},
    )
    @action(methods=["post"], detail=True, url_path="export")
    def single_export(self, request, pk):
        """
        Exports the provided ID.
        """
        serializer = BaseStackerActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        uuid = self.handle_export(
            request.user.id,
            request.user.profile.company_id,
            [pk],
            serializer.validated_data.get("type"),
        )

        return Response({"id": uuid}, 201)

    @swagger_auto_schema(
        method="post",
        request_body=BaseStackerBulkActionSerializer,
        responses={200: UploadSkipTraceResponseSerializer},
    )
    @action(methods=["post"], detail=False, url_path="skiptrace")
    def bulk_skiptrace(self, request):
        """
        Skiptrace the found property documents
        """
        if not request.user.profile.can_skiptrace:
            return Response({"detail": "User is not valid to skip trace."}, 400)
        serializer = BaseStackerBulkActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        id_list = self.get_id_list(
            request.user.profile.company_id,
            serializer,
            id_field_name="property_id",
        )

        try:
            upload_skip = self.handle_skip_trace(
                request.user.profile.company_id,
                request.user.id,
                id_list,
            )
        except Exception as e:
            return Response({"detail": str(e)}, 400)

        serializer = UploadSkipTraceResponseSerializer(upload_skip)
        return Response(serializer.data, 200)

    @swagger_auto_schema(
        method="get",
        responses={200: UploadSkipTraceResponseSerializer},
    )
    @action(methods=["get"], detail=True, url_path="skiptrace")
    def single_skiptrace(self, request, pk=None):
        """
        Skiptrace the provided property ID.
        """
        if not request.user.profile.can_skiptrace:
            return Response({"detail": "User is not valid to skip trace."}, 400)
        if not Property.objects.filter(company_id=request.user.profile.company_id, id=pk).exists():
            return Response({"detail": "Could not locate property."}, 400)
        try:
            upload_skip = self.handle_skip_trace(
                request.user.profile.company_id,
                request.user.id,
                [pk],
            )
        except Exception as e:
            return Response({"detail": str(e)}, 400)

        serializer = UploadSkipTraceResponseSerializer(upload_skip)
        return Response(serializer.data, 200)

    @swagger_auto_schema(
        method="post",
        request_body=StackerBulkPushToCampaignSerializer,
        responses={204: {}},
    )
    @action(methods=["post"], detail=False, url_path="push")
    def bulk_push_to_campaign(self, request):
        """
        Pushes the found documents prospects into a campaign
        """
        if "import_type" not in request.data:
            serializer = BaseStackerBulkActionSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            # Grab the initial list of IDs.
            id_list = self.get_id_list(
                request.user.profile.company_id,
                serializer,
                force_skip=True,
                source="prospect_id",
            )

            query_filter = build_filters_and_queries(
                serializer,
                id_field_name="prospect_id",
                force_skip=True,
            )
            agg_body = StackerIndex.build_search_body(
                request.user.profile.company_id,
                queries=query_filter["queries"],
                filters=query_filter["filters"],
                id_field_name="prospect_id",
                aggregates={
                    "new_campaign_prospects": {
                        "filter": {
                            "term": {
                                "campaigns": 0,
                            },
                        },
                    },
                },
            )
            aggs = StackerIndex.aggregate(StackerIndex.prospect_index_name, agg_body)
            return Response({
                "new": aggs["new_campaign_prospects"]["doc_count"],
                "existing": len(id_list) - aggs["new_campaign_prospects"]["doc_count"],
            }, 200)

        serializer = StackerBulkPushToCampaignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        id_list = self.get_id_list(
            request.user.profile.company_id,
            serializer,
            id_field_name="prospect_id",
            force_skip=True,
            not_in_campaign=serializer.validated_data.get("import_type") == "new",
        )
        attributes = {
            "campaign_name": serializer.validated_data.get("campaign_name"),
            "campaign_id": serializer.validated_data.get("campaign_id"),
            "market_id": serializer.validated_data.get("market_id"),
            "import_type": serializer.validated_data.get("import_type"),
            "push_count": len(id_list),
            "transaction_id": None,
            "id_list": id_list,
            "user_id": request.user.id,
            "tags": serializer.validated_data.get("tags", []),
            "charge": 0,
        }

        if not request.user.profile.company.is_billing_exempt:
            cost, _ = get_upload_additional_cost(
                request.user.profile.company,
                len(id_list),
            )
            if cost:
                from billing.models import Transaction
                transaction = Transaction.authorize(
                    request.user.profile.company,
                    "Sherpa Upload Fee",
                    cost,
                )
                if not transaction.is_authorized and not settings.TEST_MODE:
                    return Response({"detail": "Could not authorize upload expense."}, status=500)
                attributes["transaction_id"] = transaction.pk

        task = SherpaTask.objects.create(
            company_id=request.user.profile.company_id,
            created_by=request.user,
            task=SherpaTask.Task.PUSH_TO_CAMPAIGN,
            attributes=attributes,
        )
        return Response({"id": task.id}, 201)

    @swagger_auto_schema(
        method="post",
        request_body=StackerBulkPushToDirectMailSerializer,
        responses={204: {}},
    )
    @action(methods=["post"], detail=False, url_path="directmail")
    def bulk_push_to_direct_mail(self, request):
        """
        Pushes the found documents prospects into a direct mail campaign.
        """
        serializer = StackerBulkPushToDirectMailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        id_list = self.get_id_list(
            request.user.profile.company_id,
            serializer,
            force_skip=False,
            source="prospect_id",
        )
        id_list = self.remove_duplication_for_prospect_ids(id_list)
        budget_per_order = 0
        temp_budget_per_order = serializer.validated_data.get('budget_per_order')
        if temp_budget_per_order:
            budget_per_order = temp_budget_per_order

        attributes = {
            "campaign_name": serializer.validated_data.get("campaign_name"),
            "push_count": len(id_list),
            "transaction_id": None,
            "id_list": id_list,
            "user_id": serializer.validated_data.get("from_id", request.user.id),
            "drop_date": serializer.validated_data.get("drop_date"),
            "template": serializer.validated_data.get("template"),
            "creative_type": serializer.validated_data.get("creative_type"),
            "budget_per_order": budget_per_order,
            "note_for_processor": serializer.validated_data.get("note_for_processor"),
            "return_address": serializer.validated_data.get("return_address"),
            "return_city": serializer.validated_data.get("return_city"),
            "return_state": serializer.validated_data.get("return_state"),
            "return_zip": serializer.validated_data.get("return_zip"),
            "return_phone": serializer.validated_data.get("return_phone"),
            "podio_email": serializer.validated_data.get("podio_email"),
            "zapier_webhook": serializer.validated_data.get("zapier_webhook"),
            "access": serializer.validated_data.get("access"),
            "owner": serializer.validated_data.get("owner"),
            "direct_mail": True,
            "tags": serializer.validated_data.get("tags", []),
        }

        task = SherpaTask.objects.create(
            company_id=request.user.profile.company_id,
            created_by=request.user,
            task=SherpaTask.Task.PUSH_TO_CAMPAIGN,
            attributes=attributes,
        )
        return Response({"id": task.id}, 201)

    @swagger_auto_schema(responses={200: StackerPropertyResponseSerializer})
    @action(methods=["get"], detail=True, url_path="property/data")
    def get_property_data(self, request, pk=None):
        """
        Since the property data that is displayed in the UI comes from all sorts of models, this
        single endpoint will collect all or as much as possible so the UI only needs one endpoint.
        """
        prop = Property.objects.get(company_id=request.user.profile.company_id, pk=pk)
        data = {
            "address": {},
            "property_data": {},
            "prospects": [],
        }

        # Get address.
        data["address"]["property_address"] = prop.address.address_display
        data["address"]["mailing_address"] = prop.mailing_address.address_display \
            if prop.mailing_address else ""

        # Get property URLs
        data["property_data"]["zillow_link"] = prop.address.zillow_link
        data["property_data"]["street_view_url"] = prop.address.street_view_url

        # Get property tag info
        tag_counts = prop.tags.order_by("distress_indicator").values(
            "distress_indicator",
        ).annotate(total=Count("id"))
        total_tags = 0
        total_distress = 0
        for c in tag_counts:
            total_tags += c["total"]
            total_distress += c["total"] if c["distress_indicator"] else 0
        data["property_data"]["tags"] = {
            "total": total_tags,
            "distress_indicators": total_distress,
        }

        # Get prospect data.
        data["prospects"] = list(prop.prospect_set.select_related("campaignprospect").annotate(
            total_campaigns=Count("campaignprospect__id"),
            campaign_id=ArrayAgg("campaignprospect__campaign__id"),
        ).values(
            "id",
            "first_name",
            "last_name",
            "phone_raw",
            "do_not_call",
            "is_priority",
            "is_blocked",
            "is_qualified_lead",
            "wrong_number",
            "opted_out",
            "owner_verified_status",
            "total_campaigns",
            "lead_stage",
            "last_sms_sent_utc",
            "campaign_id",
        ))

        for prospect in data["prospects"]:
            prospect["last_contact"] = prospect.pop("last_sms_sent_utc")

        # Get skip trace data.
        skip_trace = prop.skiptraceproperty_set.first()
        data["property_data"]["relatives"] = []
        if skip_trace:
            relatives = []
            if skip_trace.relative_1_first_name:
                relatives.append({
                    "name": f"{skip_trace.relative_1_first_name} {skip_trace.relative_1_last_name}",
                    "numbers": skip_trace.relative_1_numbers.split(", "),
                })
            if skip_trace.relative_2_first_name:
                relatives.append({
                    "name": f"{skip_trace.relative_2_first_name} {skip_trace.relative_2_last_name}",
                    "numbers": skip_trace.relative_2_numbers.split(", "),
                })
            data["property_data"]["relatives"] = relatives
            data["property_data"]["is_vacant"] = skip_trace.validated_property_vacant == "Y"

        # Get attom data.
        attom = prop.address.attom
        attom_data = {}
        if attom:
            attom_data["legal_description"] = attom.legal_description
            attom_data["year_built"] = attom.year_built
            attom_data["sale_date"] = attom.deed_last_sale_date
            attom_data["sale_price"] = attom.deed_last_sale_price
            attom_data["bath_count"] = attom.bath_count
            attom_data["bath_partial_count"] = attom.bath_partial_count
            attom_data["bedrooms_count"] = attom.bedrooms_count
            attom_data["building_sqft"] = attom.area_gross
            attom_data["lot_sqft"] = attom.area_lot_sf
            attom_data["type"] = attom.get_property_use_standardized_display()
            attom_data["loan"] = {}
        data["property_data"].update(attom_data)
        serializer = StackerPropertyResponseSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.validated_data, 200)

    def handle_property_tagging(self, request, pk=None):
        """
        Handles the tagging process, both adding and removing, on properties.

        :param request Request: The request object.
        :param pk int: The ID of the instance that will solely be updated, if not a bulk.
        """
        if pk:
            serializer = StackerSinglePropertyTagSerializer(data=request.data)
        else:
            serializer = StackerBulkPropertyTagSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        id_list = []
        if pk:
            id_list.append(pk)
        else:
            id_list = self.get_id_list(
                request.user.profile.company_id,
                serializer,
                id_field_name="property_id",
                forced_type="property",
            )
        handle_property_tagging.delay(
            id_list,
            serializer.validated_data.get("tags"),
            request.method == "POST",
        )

    def handle_prospect_tagging(self, request, pk=None):
        """
        Handles the tagging process, both adding and removing, on prospects.

        :param request Request: The request object.
        :param pk int: The ID of the instance that will solely be updated, if not a bulk.
        """
        if pk:
            serializer = StackerSingleProspectTagSerializer(data=request.data)
        else:
            serializer = StackerBulkProspectTagSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        id_list = []
        if pk:
            id_list.append(pk)
        else:
            id_list = self.get_id_list(
                request.user.profile.company_id,
                serializer,
                id_field_name="prospect_id",
                forced_type="prospect",
            )
        # Remove all the extra values leaving only the tags/flags behind.
        v_data = serializer.validated_data
        v_data.pop("type", None)
        v_data.pop("search", None)
        v_data.pop("id_list", None)
        toggles = {k: v for k, v in v_data.items() if v is not None}
        handle_prospect_tag_update.delay(
            request.user.id,
            id_list,
            toggles,
            request.method == "POST",
        )

    def handle_export(self, user_id, company_id, id_list, model_type):
        """
        Creates and excutes the export download for the client based on the request.

        :param user_id int: The user who is requesting the export.
        :param company_id int: The company the user belongs to.
        :param id_list list: An array of IDs that should be exported.
        :param model_type string: The type of model the ids belong to.
        """
        if model_type == "property":
            filename = f"leadsherpa-properties_{timezone.now().date()}.csv"
            download_type = DownloadHistory.DownloadTypes.PROPERTY
        else:
            filename = f"leadsherpa-prospects_{timezone.now().date()}.csv"
            download_type = DownloadHistory.DownloadTypes.PROSPECT

        download = DownloadHistory.objects.create(
            created_by_id=user_id,
            company_id=company_id,
            download_type=download_type,
            filters={
                "filename": filename,
                "ids": id_list,
            },
            status=DownloadHistory.Status.SENT_TO_TASK,
        )
        generate_download.delay(download.uuid)

        return download.uuid

    def handle_skip_trace(self, company_id, user_id, id_list):
        """
        Handles skip tracing the provided id_list by first creating a CSV and following the normal
        upload skip trace routine.

        :param company_id int: The ID of the company making the Skip trace request.
        :param user_id int: The ID of the user making the Skip trace request.
        :param id_list list: List of property IDs used to grab the needed data for skip tracing.
        """
        total = Property.objects.select_related("prospect_set").filter(
            company_id=company_id,
            id__in=id_list,
        ).values('id').distinct("id").count()

        filename = f"PS_ST_{total}_{timezone.now().strftime('%Y-%m-%d %I:%M:%S')}.csv"
        upload_skip = UploadSkipTrace.objects.create(
            company_id=company_id,
            created_by_id=user_id,
            total_rows=total,
            has_header_row=True,
            is_single_upload=False,
            first_name_column_number=0,
            last_name_column_number=1,
            mailing_street_column_number=2,
            mailing_city_column_number=3,
            mailing_state_column_number=4,
            mailing_zipcode_column_number=5,
            property_street_column_number=6,
            property_city_column_number=7,
            property_state_column_number=8,
            property_zipcode_column_number=9,
            uploaded_filename=filename,
            is_prop_stack_upload=True,
        )

        handle_skip_trace_task.delay(
            company_id,
            user_id,
            id_list,
            upload_skip.id,
        )

        return upload_skip

    @action(methods=["post"], detail=False, url_path="draft")
    def bulk_push_to_direct_mail_as_draft(self, request):
        """
        Request for pushing from property stacker to DM campaign as draft.
        """
        # Hiding code as we're not using this currently.
        """
        req_serializer = StackerBulkPushToDirectMailCampaignSerializer(data=request.data)
        req_serializer.is_valid(raise_exception=True)
        from_user = get_object_or_404(User, pk=req_serializer.validated_data.get("from_id"))

        id_list = self.get_id_list(
            request.user.profile.company_id,
            req_serializer,
            id_field_name="prospect_id",
            force_skip=True,
            not_in_campaign=req_serializer.validated_data.get("import_type") == "new",
        )
        id_list = self.remove_duplication_for_prospect_ids(id_list)

        attributes = {}
        campaign_obj = None
        if 'campaign' in request.data:
            campaign_obj = Campaign.objects.create(
                company_id=request.user.profile.company_id,
                created_by=request.user,
                market_id=req_serializer.validated_data.get("market_id"),
                name=request.data['campaign']['name'],
                owner=req_serializer.validated_data.get("owner", None),
            )
        elif 'campaign_id' in request.data:
            campaign_obj = Campaign.object.get(id=request.data['campaign_id'])

        drop_date = req_serializer.validated_data.get('drop_date')
        return_address = req_serializer.validated_data.get('return_address')
        return_city = req_serializer.validated_data.get('return_city')
        return_state = req_serializer.validated_data.get('return_state')
        return_zip = req_serializer.validated_data.get('return_zip')
        return_phone = req_serializer.validated_data.get('return_phone')
        template = req_serializer.validated_data.get('template')
        creative_type = req_serializer.validated_data.get('creative_type')
        note_for_processor = req_serializer.validated_data.get('note_for_processor')

        temp_budget_per_order = req_serializer.validated_data.get('budget_per_order')
        if not temp_budget_per_order:
            budget_per_order = 0
        else:
            budget_per_order = temp_budget_per_order

        direct_mail_campaign = DirectMailCampaign.objects.create(
            campaign=campaign_obj,
            provider=DirectMailProvider.YELLOWLETTER,
            budget_per_order=budget_per_order,
            is_draft=True,
        )

        direct_mail_campaign.setup_return_address(
            from_user,
            return_address,
            return_city,
            return_state,
            return_zip,
            return_phone,
        )
        direct_mail_campaign.setup_order(drop_date, template, creative_type, note_for_processor)

        attributes = {
            "push_count": len(req_serializer.validated_data.get("id_list")),
            "transaction_id": None,
            "id_list": req_serializer.validated_data.get("id_list"),
            "user_id": request.user.id,
            "drop_date": req_serializer.validated_data.get("drop_date"),
            "template": req_serializer.validated_data.get("template"),
            "creative_type": req_serializer.validated_data.get("creative_type"),
            "budget_per_order": budget_per_order,
            "note_for_processor": req_serializer.validated_data.get("note_for_processor"),
            "return_address": req_serializer.validated_data.get("return_address"),
            "return_city": req_serializer.validated_data.get("return_city"),
            "return_state": req_serializer.validated_data.get("return_state"),
            "return_zip": req_serializer.validated_data.get("return_zip"),
            "return_phone": req_serializer.validated_data.get("return_phone"),
            "podio_email": req_serializer.validated_data.get("podio_email"),
            "zapier_webhook": req_serializer.validated_data.get("zapier_webhook"),
            "access": req_serializer.validated_data.get("access"),
            "owner": req_serializer.validated_data.get("owner"),
            "direct_mail": True,
            "is_draft": True,
            "tags": req_serializer.validated_data.get("tags"),
            "charge": 0,
            "market_id": req_serializer.validated_data.get("market_id"),
            "import_type": req_serializer.validated_data.get("import_type"),
            "campaign_id": campaign_obj.id,
        }

        SherpaTask.objects.create(
            company_id=request.user.profile.company_id,
            created_by=request.user,
            task=SherpaTask.Task.PUSH_TO_CAMPAIGN,
            attributes=attributes,
        )

        resp_serializer = ResponseDuplicatedProspectSerializer(
            instance=duped_prospect_qs,
            context={'deduped_id_list': req_serializer.validated_data.get('id_list')},
            many=True,
        )

        return Response(resp_serializer.data, 201)
        """
        return Response()
