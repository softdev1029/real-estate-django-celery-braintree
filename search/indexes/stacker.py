from typing import Any, Dict, List, Optional

from elasticsearch import Elasticsearch
from elasticsearch.helpers import scan

from django.conf import settings
from django.core.cache import cache

from sherpa.models import Activity
from .sql import property_create_sql, property_update_sql, prospect_create_sql, prospect_update_sql
from ..utils import (
    build_search_filters,
    build_search_query,
    execute_sql_and_index,
    generate_sort_object,
    get_tag_filter,
)


class StackerIndex:
    """
    The Property Stacker search requires two indexes based on the same mapping due to how
    the filter was designed to work.  Each index is based on the prospects and properties.

    We track the prospect, property and address IDs as a way to handle updates.  All updates
    are done via an `update_by_query` approach which will take a query to determine which records
    will be updated.  All updates should try to utilize the `FieldTracker` on the model to limit
    any calls to the database.

    Note: The property index groups the prospect data into arrays. This does not affect search.
    """
    property_index_name = f"{'test_' if settings.TEST_MODE else ''}stacker-property"
    prospect_index_name = f"{'test_' if settings.TEST_MODE else ''}stacker-prospect"
    index = {
        "settings": {
            "index": {
                "number_of_shards": 2,
                "number_of_replicas": 0,
                "search": {
                    "idle": {
                        "after": f"{10 * 60}s",  # 10 minutes
                    },
                },
                "max_ngram_diff": 3,
            },
            "analysis": {
                "char_filter": {
                    "digits_only": {
                        "type": "pattern_replace",
                        "pattern": "[^\\d]",
                    },
                },
                "filter": {
                    "street_synonyms": {
                        "type": "synonym",
                        "lenient": True,
                        "synonyms_path": "synonyms/street_synonyms.txt",
                    },
                    "4_7_egram": {
                        "type": "edge_ngram",
                        "min_gram": 4,
                        "max_gram": 7,
                        "preserve_original": True,
                    },
                    "street_search_filter": {
                        "type": "stop",
                        "ignore_case": True,
                        "stopwords_path": "stop/stop_words.txt",
                    },
                },
                "normalizer": {
                    "city_normalizer": {
                        "type": "custom",
                        "char_filter": [],
                        "filter": ["lowercase"],
                    },
                },
                "tokenizer": {
                    "phone_number_tokenizer": {
                        "type": "ngram",
                        "min_gram": "4",
                        "max_gram": "7",
                        "token_chars": ["digit"],
                    },
                },
                "analyzer": {
                    "index_phone_analyzer": {
                        "type": "custom",
                        "char_filter": ["digits_only"],
                        "tokenizer": "phone_number_tokenizer",
                        "filter": ["trim"],
                    },
                    "search_phone_analyzer": {
                        "type": "custom",
                        "char_filter": ["digits_only"],
                        "tokenizer": "keyword",
                        "filter": ["trim"],
                    },
                    "name_analyzer": {
                        "type": "custom",
                        "tokenizer": "standard",
                        "filter": ["trim", "lowercase", "4_7_egram"],
                    },
                    "index_address_analyzer": {
                        "type": "custom",
                        "tokenizer": "standard",
                        "filter": ["trim", "lowercase", "street_synonyms", "4_7_egram"],
                    },
                    "search_address_analyzer": {
                        "type": "custom",
                        "tokenizer": "standard",
                        "filter": ["trim", "lowercase", "street_search_filter", "4_7_egram"],
                    },
                },
            },
        },
        "mappings": {
            "properties": {
                "company_id": {
                    "type": "integer",
                },
                "prospect_id": {
                    "type": "integer",
                },
                "property_id": {
                    "type": "integer",
                },
                "address_id": {
                    "type": "integer",
                },
                "name": {  # partial match
                    "type": "text",
                    "analyzer": "name_analyzer",
                    "fields": {
                        "raw": {
                            "type": "keyword",
                        },
                    },
                },
                "address": {  # partial match
                    "type": "text",
                    "analyzer": "index_address_analyzer",
                    "search_analyzer": "search_address_analyzer",
                    "fields": {
                        "raw": {
                            "type": "keyword",
                        },
                    },
                },
                "city": {  # full match
                    "type": "keyword",
                    "normalizer": "city_normalizer",
                },
                "state": {
                    "type": "keyword",
                    "ignore_above": 2,
                },
                "zip_code": {
                    "type": "keyword",
                    "ignore_above": 5,
                },
                "last_sold_date": {
                    "type": "date",
                },
                "tags": {
                    "type": "integer",
                },
                "tags_length": {
                    "type": "integer",
                },
                "distress_indicators": {
                    "type": "integer",
                },
                "phone_raw": {  # partial match
                    "type": "text",
                    "analyzer": "index_phone_analyzer",
                    "search_analyzer": "search_phone_analyzer",
                    "fields": {
                        "raw": {
                            "type": "keyword",
                        },
                    },
                },
                "lead_stage_id": {
                    "type": "integer",
                },
                "is_blocked": {
                    "type": "boolean",
                },
                "do_not_call": {
                    "type": "boolean",
                },
                "is_priority": {
                    "type": "boolean",
                },
                "is_qualified_lead": {
                    "type": "boolean",
                },
                "wrong_number": {
                    "type": "boolean",
                },
                "opted_out": {
                    "type": "boolean",
                },
                "owner_status": {
                    "type": "keyword",
                },
                "is_archived": {
                    "type": "boolean",
                },
                "last_contact": {
                    "type": "date",
                },
                "last_contact_inbound": {
                    "type": "date",
                },
                "created_date": {
                    "type": "date",
                    "index": False,
                },
                "last_modified": {
                    "type": "date",
                    "index": False,
                },
                "campaigns": {
                    "type": "integer",
                },
                "dm_campaigns": {
                    "type": "integer",
                },
                "has_reminder": {
                    "type": "boolean",
                },
                "recently_vacant": {
                    "type": "boolean",
                },
                "bankruptcy_date": {
                    "type": "date",
                },
                "judgment_date": {
                    "type": "date",
                },
                "foreclosure_date": {
                    "type": "date",
                },
                "lien_date": {
                    "type": "date",
                },
                "skiptrace_date": {
                    "type": "date",
                },
                "campaign_id": {
                    "type": "integer",
                },
                "prospect_status": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "text",
                        },
                        "date_utc": {
                            "type": "date",
                        },
                    },
                },
                "property_status": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "text",
                        },
                        "date_utc": {
                            "type": "date",
                        },
                    },
                },
                "first_import_date": {
                    "type": "date",
                },
                "last_import_date": {
                    "type": "date",
                },
            },
        },
    }
    es = Elasticsearch(
        hosts=settings.ELASTICSEARCH_HOSTS,
        timeout=30,
        max_retries=5,
        retry_on_timeout=True,
    )
    query_map = {
        "name": {
            "type": "multi_match",
            "fields": ["name", "name.raw^6"],
        },
        "address": {
            "type": "multi_match",
            "fields": ["address", "address.raw^6"],
        },
        "city": {
            "type": "term",
            "fields": ["city"],
        },
        "phone": {
            "type": "multi_match",
            "fields": ["phone_raw", "phone_raw.raw^6"],
        },
    }
    prospect_status_query_map = {
        "isBlocked": {"prospect_status.title": "is_blocked"},
        "doNotCall": {"prospect_status.title": Activity.Title.ADDED_DNC},
        "isPriority": {"prospect_status.title": Activity.Title.ADDED_PRIORITY},
        "isQualifiedLead": {"prospect_status.title": Activity.Title.ADDED_QUALIFIED},
        "wrongNumber": {"prospect_status.title": Activity.Title.ADDED_WRONG},
    }

    @classmethod
    def fields(cls):
        """
        Returns the fields in the mapping.
        """
        return list(cls.index["mappings"]["properties"].keys())

    @classmethod
    def create(cls):
        """
        Creates the indexes.
        """
        for index in [cls.property_index_name, cls.prospect_index_name]:
            cls.es.indices.create(index=index, body=cls.index, timeout="30s")

    @classmethod
    def delete(cls):
        """
        Deletes the index.
        """
        cls.es.indices.delete(index=cls.property_index_name, ignore=404)
        cls.es.indices.delete(index=cls.prospect_index_name, ignore=404)

    @classmethod
    def total_counts_by_company(cls, company_id):
        """
        Returns the total index counts and stores them into Redis cache.
        """
        cache_key = f"stacker-counts-{company_id}"
        counts = cache.get(cache_key)
        if counts:
            return counts

        body = cls.build_search_body(company_id)
        counts = {
            "prospects": cls.es.count(body=body, index=cls.prospect_index_name)["count"],
            "properties": cls.es.count(body=body, index=cls.property_index_name)["count"],
        }

        cache.set(cache_key, counts, timeout=60 * 3)  # Store counts for 3 minutes.
        return counts

    @classmethod
    def populate_property_by_company(cls, company_id):
        """
        Populates the stacker property index with documents by company.

        :param company_id int: The company whose data will be inserted into the index.
        """
        execute_sql_and_index(
            cls.es,
            "property_id",
            cls.property_index_name,
            property_create_sql,
            [tuple(company_id)],
            cls.fields(),
        )

    @classmethod
    def populate_prospect_by_company(cls, company_id):
        """
        Populates the stacker prospect index with documents by company.

        :param company_id int: The company whose data will be inserted into the index.
        """
        execute_sql_and_index(
            cls.es,
            "prospect_id",
            cls.prospect_index_name,
            prospect_create_sql,
            [tuple(company_id)],
            cls.fields(),
        )

    @classmethod
    def full_update(cls, prop_id_list, pros_id_list):
        """
        Updates all documents found via id

        :param prop_id_list tuple: Tuple of property id to query and update.
        :param pros_id_list tuple: Tuple of prospect id to query and update.
        """

        if prop_id_list:
            execute_sql_and_index(
                cls.es,
                "property_id",
                cls.property_index_name,
                property_update_sql,
                [prop_id_list],
                cls.fields(),
            )
        if pros_id_list:
            execute_sql_and_index(
                cls.es,
                "prospect_id",
                cls.prospect_index_name,
                prospect_update_sql,
                [pros_id_list],
                cls.fields(),
            )

    @classmethod
    def update_by_query(cls, index, body):
        """
        Updates the found documents in the search query with the changes provided.

        :param index string: Name of the index to update.
        :param body dictionary: A dictionary containing both the query and updates for update.
        """
        cls.es.update_by_query(index, body=body, refresh=True, conflicts="proceed")

    @classmethod
    def search(cls, index_name, body, size=None, sort=None, search_after=None):
        """
        Search index based on body.

        :param index_name str: Name of the index.  Must be one of the above specified.
        :param body dictionary: An object containing the query and sort.
        :param size int: The number of documents to return.
        :param sort list: A list of (<Field>:<Direction>).
        :param search_after list: A list of values that are returned during a sort to determine
        the next page.
        """
        if index_name not in [cls.property_index_name, cls.prospect_index_name]:
            raise Exception("Index name does not exist.")

        if search_after:
            body.update({"search_after": search_after})
        if sort:
            sort_id_field = "property_id"
            if index_name == cls.prospect_index_name:
                sort_id_field = "prospect_id"
            body.update(
                {
                    "sort": generate_sort_object(
                        sort.get("field"),
                        sort.get("order"),
                        0,
                        sort_id_field,
                    ),
                },
            )
        search_response = cls.es.search(
            index=index_name,
            body=body,
            size=size,
            track_total_hits=True,
        )
        results = {
            "results": [result["_source"] for result in search_response["hits"]["hits"]],
            "total": search_response["hits"]["total"]["value"],
            "search_after": None,
        }

        if sort and search_response["hits"]["hits"]:
            results["search_after"] = search_response["hits"]["hits"][-1]["sort"]

        if "aggs" in body:
            results["aggs"] = search_response["aggregations"]

        return results

    @classmethod
    def search_indexes(cls, body, size=None, sort=None, search_after=None):
        prospect_sa = None
        property_sa = None
        if search_after:
            prospect_sa = search_after["prospects"] if "prospects" in search_after else None
            property_sa = search_after["properties"] if "properties" in search_after else None
        return {
            "prospects": cls.search(cls.prospect_index_name, body, size, sort, prospect_sa),
            "properties": cls.search(cls.property_index_name, body, size, sort, property_sa),
        }

    @classmethod
    def get_id_list(cls, index, body, id_field):
        """
        Returns the list of IDs of the model type found in that models index.

        :param index string: The index to use.
        :param body dictionary: An object containing the query to send to elasticsearch.
        :param id_field string: The ID field name to pull from each doc.
        """
        gen = scan(cls.es, query=body, index=index, size=10000)
        ids = [doc["_source"][id_field] for doc in gen]
        if isinstance(ids[0], list):
            ids = [id for inner in ids for id in inner]
        return ids

    @classmethod
    def aggregate(cls, index, body):
        aggregate_result = cls.search(index, body, size=0)
        return aggregate_result["aggs"]

    @classmethod  # noqa C901
    def build_search_body(
            cls,
            company_id: int,
            queries: Optional[Dict[str, Any]] = None,
            filters: Optional[Dict[str, Any]] = None,
            id_field_name: Optional[str] = None,
            aggregates: Optional[Dict[str, Any]] = None,
            exclude: Optional[List[Any]] = None,
            source: Optional[str] = None,
    ):
        """
        Builds the search query that will hit the elasticsearch indexes.

        :param company_id: The company ID that determines which documents to pull.
        :param queries: The data with which to generate a search query.
        :param filters: The data with which to filter the index on.
        :param id_field_name: Forces the results to only return this field.
        :param aggregates: A dictionary containing elasticsearch aggregations.
        :param exclude: A list of IDs to exclude from result.
        :param source: Sets the field that will only be returned in search.

        TODO: make more generic by removing `tags`, `skip_traced`, and `in_campaign` filters and
        move to utils file.
        """
        body: Dict[str, Any] = {
            "query": {
                "bool": {
                    "filter": [
                        {
                            "term": {
                                "company_id": company_id,
                            },
                        },
                    ],
                    "must": [],
                    "must_not": [],
                    "should": [],
                },
            },
        }

        if source is not None:
            body["_source"] = source

        if exclude is not None and id_field_name is not None:
            if not isinstance(exclude, list):
                raise TypeError("exclude must be a list")
            body["query"]["bool"]["must_not"].append({
                "terms": {id_field_name: exclude},
            })

        if not queries and not filters:
            return body

        if filters is not None:
            if not isinstance(filters, dict):
                raise TypeError("filters must be a dict")
            filters = filters.copy()  # Shallow copy to not change the original filters dict param
            property_tags = filters.pop("property_tags", None)
            skip_traced = filters.pop("skip_traced", None)
            in_campaign = filters.pop("in_campaign", None)
            in_dm_campaign = filters.pop("in_dm_campaign", None)
            lead_stage_id = filters.pop("lead_stage_id", [])
            last_sold_date = filters.pop("last_sold_date", {})
            has_reminder = filters.pop("is_reminder", None)
            zip_code = filters.pop("zip_code", None)
            inbound_date_lookup = filters.pop("inbound_date", {})
            outbound_date_lookup = filters.pop("outbound_date", {})
            skiptrace_date = filters.pop("skiptrace_date", {})
            prospect_status = filters.pop("prospect_status", {})
            first_import_date = filters.pop("first_import_date", {})
            last_import_date = filters.pop("last_import_date", {})

            if has_reminder is not None:
                body["query"]["bool"]["filter"].append({"term": {"has_reminder": has_reminder}})

            if skip_traced is not None:
                if skip_traced:
                    body["query"]["bool"]["filter"].append({"exists": {"field": "phone_raw"}})
                else:
                    body["query"]["bool"]["must_not"].append({"exists": {"field": "phone_raw"}})

            if in_campaign is not None:
                if in_campaign:
                    body["query"]["bool"]["filter"].append({"range": {"campaigns": {"gt": 0}}})
                else:
                    body["query"]["bool"]["filter"].append({"term": {"campaigns": 0}})

            if in_dm_campaign is not None:
                if in_dm_campaign:
                    body["query"]["bool"]["filter"].append({"range": {"dm_campaigns": {"gt": 0}}})
                else:
                    body["query"]["bool"]["filter"].append({"term": {"dm_campaigns": 0}})

            date_filter_map = {
                "last_contact_inbound": inbound_date_lookup,
                "last_contact": outbound_date_lookup,
                "last_sold_date": last_sold_date,
                "skiptrace_date": skiptrace_date,
                "last_import_date": last_import_date,
                "first_import_date": first_import_date,
            }
            for field, lookup in date_filter_map.items():
                if not lookup:
                    continue
                body["query"]["bool"]["filter"].extend([
                    {
                        "exists": {
                            "field": field,
                        },
                    },
                    {
                        "range": {
                            field: lookup,
                        },
                    },
                ])

            if property_tags is not None:
                for key, value in get_tag_filter(property_tags).items():
                    body["query"]["bool"][key].extend(value)
            if prospect_status:
                for key, value in get_tag_filter(
                    prospect_status,
                    "match",
                    cls.prospect_status_query_map,
                ).items():
                    body["query"]["bool"][key].extend(value)

            if lead_stage_id:
                body["query"]["bool"]["filter"].append({"terms": {"lead_stage_id": lead_stage_id}})

            if zip_code:
                body["query"]["bool"]["filter"].append({"term": {"zip_code": zip_code}})

            for bool_type, values in build_search_filters(filters).items():
                body["query"]["bool"][bool_type].extend(values)

        if queries is not None:
            body["query"]["bool"]["must"].extend(
                build_search_query(queries, query_map=cls.query_map),
            )

        if aggregates is not None:
            body["aggs"] = aggregates

        if body["query"]["bool"]["should"]:
            body["query"]["bool"]["minimum_should_match"] = 1
        return body
