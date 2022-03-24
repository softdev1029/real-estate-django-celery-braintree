import datetime
import json
import unittest

from model_mommy import mommy

from search.indexes import StackerIndex
from search.serializers import BaseStackerBulkActionSerializer
from search.tasks import populate_by_company_id
from search.utils import build_filters_and_queries, get_tag_filter
from sherpa.tests import BaseAPITestCase


class ElasticSearchTestCase(BaseAPITestCase):
    def setUp(self):
        StackerIndex.delete()
        StackerIndex.create()

        super().setUp()

        address = mommy.make("properties.Address")
        self.property = mommy.make('Property', address=address, company=self.company1)
        self.prospect1 = mommy.make('Prospect', prop=self.property, company=self.company1)
        self.prospect2 = mommy.make('Prospect', prop=self.property, company=self.company1)

        populate_by_company_id([self.company1.pk, self.company2.pk])

        StackerIndex.es.indices.refresh()  # Wait until data is ready on ES


class StackerSearchAPITestCase(ElasticSearchTestCase):
    def test_retrive_company_prospects_and_properties_from_ES(self):
        search_body = StackerIndex.build_search_body(self.company1.pk)
        search_results = StackerIndex.search_indexes(search_body)

        prospect_results = search_results["prospects"]["results"]
        property_results = search_results["properties"]["results"]

        # Checking that we are getting the correct amount of prospects and properties
        self.assertEqual(len(prospect_results), 2)
        self.assertEqual(len(property_results), 1)

        # Checking that the prospects and properties that we are getting are the correct ones
        prospect_ids = [self.prospect1.pk, self.prospect2.pk]
        self.assertTrue(prospect_results[0]["prospect_id"] in prospect_ids)
        self.assertTrue(prospect_results[1]["prospect_id"] in prospect_ids)

        es_property_data = property_results[0]
        self.assertEqual(es_property_data["property_id"], self.property.pk)

        # Checking relationship data between prospects and properties is correct
        self.assertEqual(prospect_results[0]["property_id"], self.property.pk)
        self.assertEqual(prospect_results[1]["property_id"], self.property.pk)
        self.assertEqual(es_property_data["prospect_id"], prospect_ids)

    def test_ES_querybuilding_no_sideeffects(self):
        # Make sure building ES queries is not modifying it's input data, because
        # that data its used in building further filtering queries in some cases
        request_data = json.loads("""
        {"type":"property","search":{"query":{},"filters":{"lead_stage_id":[11608893],"is_archived":false},"sort":{"field":"last_contact","order":"desc"}}}
        """)

        serializer = BaseStackerBulkActionSerializer(data=request_data)
        serializer.is_valid(raise_exception=True)

        # Saving the original validated_data to confirm later that its not modified
        original_validated_data = json.dumps(serializer.validated_data, sort_keys=True)

        # We attempt to create the same ES query search body two times
        search_bodies = []
        for _ in range(2):
            query_filter = build_filters_and_queries(
                serializer,
                id_field_name="prospect_id",
                force_skip=True,
            )
            # Using a json dump with sorted keys provides an easy way of comparing nested dicts
            # by comparing the resulting strings
            search_bodies.append(
                json.dumps(
                    StackerIndex.build_search_body(
                        self.company1.pk,
                        queries=query_filter["queries"],
                        filters=query_filter["filters"],
                        id_field_name="prospect_id",
                    ),
                    sort_keys=True,
                ),
            )

        # Direct test that the validated_data has not been modified
        self.assertEqual(
            original_validated_data,
            json.dumps(serializer.validated_data, sort_keys=True),
        )
        # The built search bodies should be equal as they got the same input parameters
        self.assertEqual(search_bodies[0], search_bodies[1])


class SearchUtilUnitTest(unittest.TestCase):
    def test_tag_filter(self):
        self.assertDictEqual(
            {
                'must': [
                    {'range': {'prospect_status.date_utc': {'gte': datetime.date(2021, 1, 1)}}},
                ],
                'must_not': [],
                'should': [{'match': {'test_tag': 'This is FAKE'}}],
            },
            get_tag_filter(
                {
                    'option': 'any',
                    'criteria': 'tagAfter',
                    'date_from': datetime.date(2021, 1, 1),
                    'include': ['testTag'],
                    'exclude': [],
                },
                "match",
                {
                    "testTag": {"test_tag": "This is FAKE"},
                },
            ),
        )

    def test_prospect_status_filter(self):
        self.assertDictEqual(
            {
                'must': [
                    {'range': {'prospect_status.date_utc': {'lte': datetime.date(2021, 8, 4)}}},
                ],
                'must_not': [],
                'should': [{'match': {'prospect_status.title': 'Added to DNC'}}],
            },
            get_tag_filter(
                {
                    'option': 'any',
                    'criteria': 'tagBefore',
                    'date_to': datetime.date(2021, 8, 4),
                    'include': ['doNotCall'],
                    'exclude': [],
                },
                "match",
                StackerIndex.prospect_status_query_map,
            ),
        )

    def test_property_tag_filter(self):
        # property tag check
        self.assertDictEqual(
            {
                'must': [
                    {'term': {'tags': 1}},
                    {'range': {'property_status.date_utc': {'lte': datetime.date(2021, 8, 4)}}},
                ],
                'must_not': [],
                'should': [],
            },
            get_tag_filter(
                {
                    'option': 'all',
                    'criteria': 'tagBefore',
                    'date_to': datetime.date(2021, 8, 4),
                    'include': [1],
                    'exclude': [],
                },
            ),
        )
