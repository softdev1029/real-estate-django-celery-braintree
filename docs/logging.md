Log Destination: logs.papertrailapp.com:15976

System is setup to only log when DEPLOY_TARGET=production

Global Filters set here:

https://papertrailapp.com/destinations/25574841/filter

As of this writing, they are:

[INFO].*(stacker_full_update|stacker_update_property_tag|telnyx_status_callback_task|attempt_batch_text|run_open_tasks|record_skipped_send|update_total_initial_sent_skipped_task|update_total_qualified_leads_count_task|validate_skip_trace_returned_address_task|sms_message_received_router|record_phone_number_auto_dead|record_phone_number_stats_received|track_sms_reponse_time_task|update_pending_numbers|verify_spam_counts|update_prospect_async|update_prospect_after_create|validate_address_single_task)
