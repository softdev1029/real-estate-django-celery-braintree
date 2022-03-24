from copy import deepcopy
from datetime import datetime

from elasticsearch import helpers

from django.contrib.auth import get_user_model
from django.db import connection

from campaigns.directmail import DirectMailProvider
from sherpa.models import Campaign

User = get_user_model()


def build_search_query(query_params, query_map):
    queries = []
    for field_name, value in query_params.items():
        if query_map[field_name]["type"] == "multi_match":
            queries.append({
                query_map[field_name]["type"]: {
                    "query": value,
                    "fields": query_map[field_name]["fields"],
                },
            })
        else:
            queries.append({
                query_map[field_name]["type"]: {
                    field_name: value,
                },
            })

    return queries


def build_search_filters(filter_params):
    filters = {
        "filter": [],
        "must": [],
        "must_not": [],
    }

    for key, value in filter_params.items():
        key = 'has_reminder' if key == 'is_reminder' else key
        filter_key = "terms" if isinstance(value, list) else "term"
        filters["filter"].append({
            filter_key: {
                key: value,
            },
        })

    return filters


def execute_sql_and_index(es, id_field, index_name, sql, sql_parameters, fields):
    """
    Executes provided SQL and inserts data into specified index.

    :param index string: The index to insert into.
    :param sql string: The raw SQL to execute.
    :param company_id int: The company ID to pass into the SQL statement.
    :param fields list: The list of field names in the ES indexes which will be used to convert
    the list of rows to a list of dictionaries required for insert into the ES index.
    """
    chunk_size = 5000
    with connection.cursor() as cursor:
        cursor.execute(sql, sql_parameters)
        actions = stream_sql(cursor, id_field, index_name, fields, chunk_size=chunk_size)
        helpers.bulk(es, actions, chunk_size=chunk_size, max_retries=1)


def stream_sql(cursor, id_field, index_name, fields, chunk_size=500):
    """
    Yields a generator of returned rows from a SQL cursor.
    """
    with cursor:
        while True:
            if cursor.closed:
                break
            rows = cursor.fetchmany(chunk_size)
            if not rows:
                break
            for body in [dict(zip(fields, row)) for row in rows]:
                yield {
                    "_id": body[id_field],
                    "_index": index_name,
                    "_op_type": "index",
                    "_source": body,
                }


def build_elasticsearch_painless_scripts(changes):
    """
    Generates a painless script used during an `update_by_query` call.

    :param changes dictionary: An object containing the field that is changing and it's new value.
    """
    script = []
    for key in changes:
        if type(changes[key]) is str:
            script.append(f"ctx._source.{key}='{changes[key]}'")
        elif type(changes[key]) is bool:
            script.append(f"ctx._source.{key}={'true' if changes[key] else 'false'}")
        else:
            script.append(f"ctx._source.{key}={changes[key]}")
    return ";".join(script) + ";"


def build_update_for_query_body(model, id, script_source):
    lookup = "terms" if isinstance(id, list) else "term"
    return {
        "query": {
            "bool": {
                "must": [
                    {
                        lookup: {
                            f"{model}_id": id,
                        },
                    },
                ],
            },
        },
        "script": {
            "source": script_source,
            "lang": "painless",
        },
    }


def generate_sort_object(field, order, missing, id_field):
    """
    Generates a 'painless' sorting script for elasticsearch queries.

    :param field string: The primary field to sort on.
    :param order string: The order of the primary field.
    :param missing any: The missing value to use if sort field has a null value.
    :param id_field string: The additional field to sort on.
    """
    if field == "tags":
        field = "tags_length"

    sort_list = []
    if field == "_score":
        sort_list.append({"_score": {"order": order}})
    else:
        sort_list.append({field: {"order": order, "missing": missing}})

    if field != id_field:
        sort_list.append({id_field: {"order": order}})
    return sort_list


def build_filters_and_queries(serializer, forced_type=None, force_skip=None, not_in_campaign=None,
                              id_field_name=None):
    # We make a deep copy to prevent any changes on the original data
    request_data = deepcopy(serializer.validated_data)

    model_name = request_data.get("type", forced_type)
    id_list = request_data.get("id_list", [])
    id_field_name = id_field_name or f"{model_name}_id"
    filters = request_data.get("search", {}).get("filters", {})

    has_reminder = filters.pop('is_reminder', None)
    if has_reminder is not None:
        filters['has_reminder'] = has_reminder

    if force_skip:
        filters["skip_traced"] = True
    if id_list:
        filters[id_field_name] = id_list
    if not_in_campaign:
        filters["in_campaign"] = False

    return {
        "filters": filters,
        "queries": request_data.get("search", {}).get("query", {}),
    }


def get_or_create_campaign(task):
    """
    Get or create campaign for task.
    """
    attributes = task.attributes

    try:
        if attributes.get("campaign_id"):
            campaign = Campaign.objects.get(
                id=attributes.get("campaign_id"),
                company_id=task.company_id,
            )
        else:
            campaign = Campaign.objects.create(
                company_id=task.company_id,
                created_by_id=attributes.get("user_id"),
                market_id=attributes.get("market_id"),
                name=attributes.get("campaign_name"),
                owner=attributes.get("owner", None),
            )
            attributes["campaign_id"] = campaign.id
            task.attributes = attributes
            task.save(update_fields=["attributes"])

        if attributes.get("direct_mail") and not hasattr(campaign, 'directmail'):
            create_direct_mail_from_attributes(attributes, campaign)

        access = attributes.get("access", [])
        if access is None:
            access = []
        campaign.update_access(
            set(access),
            User.objects.get(id=attributes.get("user_id")),
        )

        return campaign

    except Campaign.DoesNotExist:
        task.set_error(error_msg="Campaign could not be found.")
        task.restart_task()
        return None


def create_direct_mail_from_attributes(attributes, campaign):
    """
    Create `DirectMailCampaign` from task attributes and `Campaign`.
    """
    from campaigns.models import DirectMailCampaign
    if not any([
        attributes.get("user_id"),
        attributes.get("return_address"),
        attributes.get("return_city"),
        attributes.get("return_state"),
        attributes.get("return_zip"),
        attributes.get("return_phone"),
        attributes.get("drop_date"),
        attributes.get("template"),
        attributes.get("creative_type"),
        attributes.get("budget_per_order"),
    ]):
        raise Exception("Missing required parameters to create DirectMailCampaign.")

    from_id = int(attributes.get("user_id"))
    if not User.objects.filter(pk=from_id).exists():
        raise Exception("Valid User ID required in 'from_id'.")

    from_user = User.objects.get(pk=from_id)

    direct_mail = DirectMailCampaign.objects.create(
        campaign=campaign,
        provider=DirectMailProvider.YELLOWLETTER,
        budget_per_order=attributes["budget_per_order"],
    )
    direct_mail.setup_return_address(
        from_user,
        attributes["return_address"],
        attributes["return_city"],
        attributes["return_state"],
        attributes["return_zip"],
        attributes["return_phone"],
    )
    drop_date = datetime.strptime(attributes["drop_date"], "%Y-%m-%d").date()

    template = attributes["template"]
    creative_type = attributes["creative_type"]
    note = attributes.get("note_for_processor", "")
    direct_mail.setup_order(drop_date, template, creative_type, note)


def get_date_query_based_on_criteria(field, date_criteria, date_to, date_from):
    """
    Builds ES date query for fields.
    """
    if date_criteria == "tagBefore":
        return {"range": {field: {"lte": date_to}}}
    elif date_criteria == "tagBetween":
        return {
            "range": {
                field: {
                    "gte": date_from,
                    "lte": date_to,
                },
            },
        }
    elif date_criteria == "tagAfter":
        return {"range": {field: {"gte": date_from}}}


def get_tag_filter(data, filter_type="term", mapping=None):
    body = {
        "must": [],
        "must_not": [],
        "should": [],
    }
    bool_type = "must" if data["option"] == "all" else "should"
    if "include" in data:
        for key in data["include"]:
            filter_data = {"tags": key}
            if mapping:
                filter_data = mapping[key]
            body[bool_type].append({filter_type: filter_data})
    if "exclude" in data:
        for key in data["exclude"]:
            filter_data = {"tags": key}
            if mapping:
                filter_data = mapping[key]
            body["must_not"].append({filter_type: filter_data})

    if data.get("criteria"):
        field = "property_status.date_utc"
        if mapping:
            field = "prospect_status.date_utc"
        body["must"].append(
            get_date_query_based_on_criteria(
                field,
                data.get("criteria"),
                data.get("date_to"),
                data.get("date_from"),
            ),
        )
    return body
