"""
These SQL queries are used during creating and updating of elasticsearch stacker documents.
"""

property_create_sql = """
SELECT DISTINCT
    prop.company_id
    , ARRAY_REMOVE(ARRAY_AGG(DISTINCT pros.id), NULL) AS prospect_id
    , prop.id AS property_id
    , prop.address_id as address_id
    , ARRAY_REMOVE(ARRAY_AGG(
        DISTINCT pros.first_name || ' ' || pros.last_name
    ), NULL) AS name
    , addr.address
    , addr.city
    , addr.state
    , addr.zip_code
    , at.deed_last_sale_date AS last_sold_date
    , ARRAY_REMOVE(ARRAY_AGG(DISTINCT pta.tag_id ORDER BY pta.tag_id), NULL) AS tags
    , COUNT(DISTINCT pt.id) AS tags_length
    , COUNT(DISTINCT pt.id) FILTER (WHERE pt.distress_indicator = true)
    AS distress_indicators
    , ARRAY_REMOVE(ARRAY_AGG(DISTINCT NULLIF(pros.phone_raw, '')), NULL) AS phone_raw
    , ARRAY_REMOVE(ARRAY_AGG(DISTINCT pros.lead_stage_id), NULL) AS lead_stage_id
    , COALESCE(BOOL_OR(pros.is_blocked), false) AS is_blocked
    , COALESCE(BOOL_OR(pros.do_not_call), false) AS do_not_call
    , COALESCE(BOOL_OR(pros.is_priority), false) AS is_priority
    , COALESCE(BOOL_OR(pros.is_qualified_lead), false) AS is_qualified_lead
    , COALESCE(BOOL_OR(pros.wrong_number), false) AS wrong_number
    , COALESCE(BOOL_OR(pros.opted_out), false) AS opted_out
    , ARRAY_REMOVE(ARRAY_AGG(DISTINCT pros.owner_verified_status), NULL) AS owner_status
    , COALESCE(prop.is_archived, false) AS archived
    , MAX(GREATEST(cp.last_outbound_call::date, pros.last_sms_sent_utc::date)) AS last_contact
    , MAX(
        GREATEST(
            cp.last_inbound_call::date
            , pros.last_sms_received_utc::date
        )
    ) AS last_contact_inbound
    , prop.created::date AS created_date
    , COALESCE(prop.last_modified::date, prop.created::date) AS last_modified
    , COUNT(DISTINCT c.id) FILTER (
        WHERE c.is_direct_mail = false or cp.removed_datetime::date IS NOT NULL) AS campaigns
    , COUNT(DISTINCT c.id) FILTER (
        WHERE c.is_direct_mail = true and cp.removed_datetime::date IS NULL) AS dm_campaigns
    , COALESCE(BOOL_OR(pros.has_reminder), false) AS has_reminder
    , COALESCE(BOOL_OR(pt.name = 'Vacant' and pta.assigned_at >= now()::date - 30),
    false) as recently_vacant
    , NULLIF(sk.bankruptcy, '')::date as bankruptcy_date
    , sk.returned_judgment_date::date as judgment_date
    , sk.returned_foreclosure_date::date as foreclosure_date
    , sk.returned_lien_date::date as lien_date
    , sk.created::date AS skiptrace_date
    , ARRAY_REMOVE(ARRAY_AGG(DISTINCT cp.campaign_id ORDER BY cp.campaign_id), NULL) AS campaign_id
    , JSONB_AGG(
        DISTINCT JSONB_BUILD_OBJECT('title', act.title, 'date_utc', act.date_utc)
    ) FILTER (WHERE act.title IN (
        'Added to DNC'
        , 'Added Wrong Number'
        , 'Added as Priority'
        , 'Qualified Lead Added'
    )) AS prospect_status
    , JSONB_AGG(
        DISTINCT JSONB_BUILD_OBJECT('title', pt.name, 'date_utc', pta.assigned_at)
    ) FILTER (WHERE pt.name IS NOT NULL) AS property_status
    , MAX(GREATEST(pros.created_date::date, prop.created::date)) AS first_import_date
    , MAX(GREATEST(
        pros.created_date::date
        , prop.created::date
        , uskt.created::date
        , upros.created::date
    )) AS last_import_date
FROM properties_property prop
INNER JOIN properties_address addr ON addr.id = prop.address_id
LEFT JOIN properties_attomassessor at ON at.attom_id = addr.attom_id
LEFT JOIN properties_propertytagassignment pta ON pta.prop_id = prop.id
LEFT JOIN properties_propertytag pt ON pta.tag_id = pt.id
LEFT JOIN sherpa_prospect pros ON pros.prop_id = prop.id
LEFT JOIN sherpa_activity act on act.prospect_id = pros.id
LEFT JOIN sherpa_campaignprospect cp ON cp.prospect_id = pros.id
LEFT JOIN sherpa_campaign c ON c.id = cp.campaign_id
LEFT JOIN sherpa_skiptraceproperty sk ON sk.prop_id = prop.id
LEFT JOIN sherpa_uploadskiptrace uskt ON uskt.id = prop.upload_skip_trace_id
LEFT JOIN sherpa_uploadprospects upros ON upros.id = prop.upload_prospects_id
WHERE prop.company_id in %s
GROUP BY
    prop.id
    , prop.address_id
    , addr.address
    , addr.city
    , addr.state
    , addr.zip_code
    , prop.is_archived
    , prop.company_id
    , at.deed_last_sale_date::date
    , prop.created::date
    , prop.last_modified::date
    , NULLIF(sk.bankruptcy, '')::date
    , sk.returned_foreclosure_date::date
    , sk.returned_lien_date::date
    , sk.returned_judgment_date::date
    , sk.created::date
"""

prospect_create_sql = """
SELECT DISTINCT
    pros.company_id
    , pros.id AS prospect_id
    , prop.id AS property_id
    , prop.address_id as address_id
    , pros.first_name || ' ' || pros.last_name AS name
    , addr.address
    , addr.city
    , addr.state
    , addr.zip_code
    , at.deed_last_sale_date::date AS last_sold_date
    , ARRAY_REMOVE(ARRAY_AGG(DISTINCT pta.tag_id ORDER BY pta.tag_id), NULL) AS tags
    , COUNT(DISTINCT pt.id) AS tags_length
    , COUNT(DISTINCT pt.id) FILTER (WHERE pt.distress_indicator = true)
    AS distress_indicators
    , NULLIF(pros.phone_raw, '') AS phone_raw
    , pros.lead_stage_id
    , COALESCE(pros.is_blocked, false) AS is_blocked
    , COALESCE(pros.do_not_call, false) AS do_not_call
    , COALESCE(pros.is_priority, false) AS is_priority
    , COALESCE(pros.is_qualified_lead, false) AS is_qualified_lead
    , COALESCE(pros.wrong_number, false) AS wrong_number
    , COALESCE(pros.opted_out, false) AS opted_out
    , pros.owner_verified_status
    , COALESCE(pros.is_archived, false) AS archived
    , MAX(GREATEST(cp.last_outbound_call::date, pros.last_sms_sent_utc::date)) AS last_contact
    , MAX(
        GREATEST(
            cp.last_inbound_call::date
            , pros.last_sms_received_utc::date
        )
    ) AS last_contact_inbound
    , pros.created_date::date AS created_date
    , COALESCE(pros.last_modified::date, pros.created_date::date) AS last_modified
    , COUNT(DISTINCT c.id) FILTER (
        WHERE c.is_direct_mail = false or cp.removed_datetime::date IS NOT NULL) AS campaigns
    , COUNT(DISTINCT c.id) FILTER (
        WHERE c.is_direct_mail = true and cp.removed_datetime::date IS NULL) AS dm_campaigns
    , COALESCE(pros.has_reminder, false) AS has_reminder
    , COALESCE(BOOL_OR(pt.name = 'Vacant' and pta.assigned_at >= now()::date - 30),
    false) as recently_vacant
    , NULLIF(sk.bankruptcy, '')::date as bankruptcy_date
    , sk.returned_judgment_date::date as judgment_date
    , sk.returned_foreclosure_date::date as foreclosure_date
    , sk.returned_lien_date::date as lien_date
    , sk.created::date AS skiptrace_date
    , ARRAY_REMOVE(ARRAY_AGG(DISTINCT cp.campaign_id ORDER BY cp.campaign_id), NULL) AS campaign_id
    , JSONB_AGG(
        DISTINCT JSONB_BUILD_OBJECT('title', act.title, 'date_utc', act.date_utc)
    ) FILTER (WHERE act.title IN (
        'Added to DNC'
        , 'Added Wrong Number'
        , 'Added as Priority'
        , 'Qualified Lead Added'
    )) AS prospect_status
    , JSONB_AGG(
        DISTINCT JSONB_BUILD_OBJECT('title', pt.name, 'date_utc', pta.assigned_at)
    ) FILTER (WHERE pt.name IS NOT NULL) AS property_status
    , MAX(GREATEST(pros.created_date::date, prop.created::date)) AS first_import_date
    , MAX(GREATEST(
        pros.created_date::date
        , prop.created::date
        , uskt.created::date
        , upros.created::date
    )) AS last_import_date
FROM sherpa_prospect pros
LEFT JOIN sherpa_activity act on act.prospect_id = pros.id
LEFT JOIN sherpa_campaignprospect cp ON cp.prospect_id = pros.id
LEFT JOIN sherpa_campaign c on c.id = cp.campaign_id
LEFT JOIN properties_property prop ON prop.id = pros.prop_id
LEFT JOIN properties_address addr ON addr.id = prop.address_id
LEFT JOIN properties_attomassessor at ON at.attom_id = addr.attom_id
LEFT JOIN properties_propertytagassignment pta ON pta.prop_id = prop.id
LEFT JOIN properties_propertytag pt ON pta.tag_id = pt.id
LEFT JOIN sherpa_skiptraceproperty sk ON sk.prop_id = prop.id
LEFT JOIN sherpa_uploadskiptrace uskt ON uskt.id = prop.upload_skip_trace_id
LEFT JOIN sherpa_uploadprospects upros ON upros.id = prop.upload_prospects_id
WHERE pros.company_id in %s
GROUP BY
    pros.id
    , pros.company_id
    , pros.first_name
    , pros.last_name
    , pros.phone_raw
    , pros.owner_verified_status
    , pros.is_archived
    , pros.is_blocked
    , pros.do_not_call
    , pros.is_priority
    , pros.is_qualified_lead
    , pros.wrong_number
    , pros.opted_out
    , pros.lead_stage_id
    , pros.created_date::date
    , pros.last_modified::date
    , prop.id
    , addr.address
    , addr.city
    , addr.state
    , addr.zip_code
    , at.deed_last_sale_date::date
    , NULLIF(sk.bankruptcy, '')::date
    , sk.returned_foreclosure_date::date
    , sk.returned_lien_date::date
    , sk.returned_judgment_date::date
    , sk.created::date
"""

property_update_sql = """
SELECT DISTINCT
    prop.company_id
    , ARRAY_REMOVE(ARRAY_AGG(DISTINCT pros.id), NULL) AS prospect_id
    , prop.id AS property_id
    , prop.address_id as address_id
    , ARRAY_REMOVE(ARRAY_AGG(
        DISTINCT pros.first_name || ' ' || pros.last_name
    ), NULL) AS name
    , addr.address
    , addr.city
    , addr.state
    , addr.zip_code
    , at.deed_last_sale_date AS last_sold_date
    , ARRAY_REMOVE(ARRAY_AGG(DISTINCT pta.tag_id ORDER BY pta.tag_id), NULL) AS tags
    , COUNT(DISTINCT pt.id) AS tags_length
    , COUNT(DISTINCT pt.id) FILTER (WHERE pt.distress_indicator = true)
    AS distress_indicators
    , ARRAY_REMOVE(ARRAY_AGG(DISTINCT NULLIF(pros.phone_raw, '')), NULL) AS phone_raw
    , ARRAY_REMOVE(ARRAY_AGG(DISTINCT pros.lead_stage_id), NULL) AS lead_stage_id
    , COALESCE(BOOL_OR(pros.is_blocked), false) AS is_blocked
    , COALESCE(BOOL_OR(pros.do_not_call), false) AS do_not_call
    , COALESCE(BOOL_OR(pros.is_priority), false) AS is_priority
    , COALESCE(BOOL_OR(pros.is_qualified_lead), false) AS is_qualified_lead
    , COALESCE(BOOL_OR(pros.wrong_number), false) AS wrong_number
    , COALESCE(BOOL_OR(pros.opted_out), false) AS opted_out
    , ARRAY_REMOVE(ARRAY_AGG(DISTINCT pros.owner_verified_status), NULL) AS owner_status
    , COALESCE(prop.is_archived, false) AS archived
    , MAX(GREATEST(cp.last_outbound_call::date, pros.last_sms_sent_utc::date)) AS last_contact
    , MAX(
        GREATEST(
            cp.last_inbound_call::date
            , pros.last_sms_received_utc::date
        )
    ) AS last_contact_inbound
    , prop.created::date AS created_date
    , COALESCE(prop.last_modified::date, prop.created::date) AS last_modified
    , COUNT(DISTINCT c.id) FILTER (
        WHERE c.is_direct_mail = false or cp.removed_datetime::date IS NOT NULL) AS campaigns
    , COUNT(DISTINCT c.id) FILTER (
        WHERE c.is_direct_mail = true and cp.removed_datetime::date IS NULL)  AS dm_campaigns
    , COALESCE(BOOL_OR(pros.has_reminder), false) AS has_reminder
    , COALESCE(BOOL_OR(pt.name = 'Vacant' and pta.assigned_at >= now()::date - 30),
    false) as recently_vacant
    , NULLIF(sk.bankruptcy, '')::date as bankruptcy_date
    , sk.returned_judgment_date::date as judgment_date
    , sk.returned_foreclosure_date::date as foreclosure_date
    , sk.returned_lien_date::date as lien_date
    , sk.created::date AS skiptrace_date
    , ARRAY_REMOVE(ARRAY_AGG(DISTINCT cp.campaign_id ORDER BY cp.campaign_id), NULL) AS campaign_id
    , JSONB_AGG(
        DISTINCT JSONB_BUILD_OBJECT('title', act.title, 'date_utc', act.date_utc)
    ) FILTER (WHERE act.title IN (
        'Added to DNC'
        , 'Added Wrong Number'
        , 'Added as Priority'
        , 'Qualified Lead Added'
    )) AS prospect_status
    , JSONB_AGG(
        DISTINCT JSONB_BUILD_OBJECT('title', pt.name, 'date_utc', pta.assigned_at)
    ) FILTER (WHERE pt.name IS NOT NULL) AS property_status
    , MAX(GREATEST(pros.created_date::date, prop.created::date)) AS first_import_date
    , MAX(GREATEST(
        pros.created_date::date
        , prop.created::date
        , uskt.created::date
        , upros.created::date
    )) AS last_import_date
FROM properties_property prop
INNER JOIN properties_address addr ON addr.id = prop.address_id
LEFT JOIN properties_attomassessor at ON at.attom_id = addr.attom_id
LEFT JOIN properties_propertytagassignment pta ON pta.prop_id = prop.id
LEFT JOIN properties_propertytag pt ON pta.tag_id = pt.id
LEFT JOIN sherpa_prospect pros ON pros.prop_id = prop.id
LEFT JOIN sherpa_activity act on act.prospect_id = pros.id
LEFT JOIN sherpa_campaignprospect cp ON cp.prospect_id = pros.id
LEFT JOIN sherpa_campaign c ON c.id = cp.campaign_id
LEFT JOIN sherpa_skiptraceproperty sk ON sk.prop_id = prop.id
LEFT JOIN sherpa_uploadskiptrace uskt ON uskt.id = prop.upload_skip_trace_id
LEFT JOIN sherpa_uploadprospects upros ON upros.id = prop.upload_prospects_id
WHERE prop.id in %s
GROUP BY
    prop.id
    , prop.address_id
    , addr.address
    , addr.city
    , addr.state
    , addr.zip_code
    , prop.is_archived
    , prop.company_id
    , at.deed_last_sale_date::date
    , prop.created::date
    , prop.last_modified::date
    , NULLIF(sk.bankruptcy, '')::date
    , sk.returned_judgment_date::date
    , sk.returned_foreclosure_date::date
    , sk.returned_lien_date::date
    , sk.created::date
"""

prospect_update_sql = """
SELECT DISTINCT
    pros.company_id
    , pros.id AS prospect_id
    , prop.id AS property_id
    , prop.address_id as address_id
    , pros.first_name || ' ' || pros.last_name AS name
    , addr.address
    , addr.city
    , addr.state
    , addr.zip_code
    , at.deed_last_sale_date::date AS last_sold_date
    , ARRAY_REMOVE(ARRAY_AGG(DISTINCT pta.tag_id ORDER BY pta.tag_id), NULL) AS tags
    , COUNT(DISTINCT pt.id) AS tags_length
    , COUNT(DISTINCT pt.id) FILTER (WHERE pt.distress_indicator = true)
    AS distress_indicators
    , NULLIF(pros.phone_raw, '') AS phone_raw
    , pros.lead_stage_id
    , COALESCE(pros.is_blocked, false) AS is_blocked
    , COALESCE(pros.do_not_call, false) AS do_not_call
    , COALESCE(pros.is_priority, false) AS is_priority
    , COALESCE(pros.is_qualified_lead, false) AS is_qualified_lead
    , COALESCE(pros.wrong_number, false) AS wrong_number
    , COALESCE(pros.opted_out, false) AS opted_out
    , pros.owner_verified_status
    , COALESCE(pros.is_archived, false) AS archived
    , MAX(GREATEST(cp.last_outbound_call::date, pros.last_sms_sent_utc::date)) AS last_contact
    , MAX(
        GREATEST(
            cp.last_inbound_call::date
            , pros.last_sms_received_utc::date
        )
    ) AS last_contact_inbound
    , pros.created_date::date AS created_date
    , COALESCE(pros.last_modified::date, pros.created_date::date) AS last_modified
    , COUNT(DISTINCT c.id) FILTER (
        WHERE c.is_direct_mail = false or cp.removed_datetime::date IS NOT NULL) AS campaigns
    , COUNT(DISTINCT c.id) FILTER (
        WHERE c.is_direct_mail = true and cp.removed_datetime::date IS NULL) AS dm_campaigns
    , COALESCE(pros.has_reminder, false) AS has_reminder
    , COALESCE(BOOL_OR(pt.name = 'Vacant' and pta.assigned_at >= now()::date - 30),
    false) as recently_vacant
    , NULLIF(sk.bankruptcy, '')::date as bankruptcy_date
    , sk.returned_judgment_date::date as judgment_date
    , sk.returned_foreclosure_date::date as foreclosure_date
    , sk.returned_lien_date::date as lien_date
    , sk.created::date AS skiptrace_date
    , ARRAY_REMOVE(ARRAY_AGG(DISTINCT cp.campaign_id ORDER BY cp.campaign_id), NULL) AS campaign_id
    , JSONB_AGG(
        DISTINCT JSONB_BUILD_OBJECT('title', act.title, 'date_utc', act.date_utc)
    ) FILTER (WHERE act.title IN (
        'Added to DNC'
        , 'Added Wrong Number'
        , 'Added as Priority'
        , 'Qualified Lead Added'
    )) AS prospect_status
    , JSONB_AGG(
        DISTINCT JSONB_BUILD_OBJECT('title', pt.name, 'date_utc', pta.assigned_at)
    ) FILTER (WHERE pt.name IS NOT NULL) AS property_status
    , MAX(GREATEST(pros.created_date::date, prop.created::date)) AS first_import_date
    , MAX(GREATEST(
        pros.created_date::date
        , prop.created::date
        , uskt.created::date
        , upros.created::date
    )) AS last_import_date
FROM sherpa_prospect pros
LEFT JOIN sherpa_activity act on act.prospect_id = pros.id
LEFT JOIN sherpa_campaignprospect cp ON cp.prospect_id = pros.id
LEFT JOIN sherpa_campaign c on c.id = cp.campaign_id
LEFT JOIN properties_property prop ON prop.id = pros.prop_id
LEFT JOIN properties_address addr ON addr.id = prop.address_id
LEFT JOIN properties_attomassessor at ON at.attom_id = addr.attom_id
LEFT JOIN properties_propertytagassignment pta ON pta.prop_id = prop.id
LEFT JOIN properties_propertytag pt ON pta.tag_id = pt.id
LEFT JOIN sherpa_skiptraceproperty sk ON sk.prop_id = prop.id
LEFT JOIN sherpa_uploadskiptrace uskt ON uskt.id = prop.upload_skip_trace_id
LEFT JOIN sherpa_uploadprospects upros ON upros.id = prop.upload_prospects_id
WHERE pros.id in %s
GROUP BY
    pros.id
    , pros.company_id
    , pros.first_name
    , pros.last_name
    , pros.phone_raw
    , pros.owner_verified_status
    , pros.is_archived
    , pros.is_blocked
    , pros.do_not_call
    , pros.is_priority
    , pros.is_qualified_lead
    , pros.wrong_number
    , pros.opted_out
    , pros.lead_stage_id
    , pros.created_date::date
    , pros.last_modified::date
    , prop.id
    , addr.address
    , addr.city
    , addr.state
    , addr.zip_code
    , at.deed_last_sale_date::date
    , NULLIF(sk.bankruptcy, '')::date
    , sk.returned_judgment_date::date
    , sk.returned_foreclosure_date::date
    , sk.returned_lien_date::date
    , sk.created::date
"""
