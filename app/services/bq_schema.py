from google.cloud.bigquery import SchemaField

AI_AUDITS_SCHEMA = [
    SchemaField("audit_id", "STRING", mode="REQUIRED"),
    SchemaField("session_id", "STRING", mode="NULLABLE"),
    SchemaField("driver_id", "STRING", mode="NULLABLE"),
    SchemaField("check_type", "STRING", mode="NULLABLE"),
    SchemaField("consensus_plate", "STRING", mode="NULLABLE"),
    SchemaField("consensus_color", "STRING", mode="NULLABLE"),
    SchemaField("identity_status", "STRING", mode="NULLABLE"),
    SchemaField("identity_reason", "STRING", mode="NULLABLE"),
    SchemaField("total_images", "INTEGER", mode="NULLABLE"),
    SchemaField("passed_images", "INTEGER", mode="NULLABLE"),
    SchemaField("failed_images", "INTEGER", mode="NULLABLE"),
    SchemaField("damage_flagged_count", "INTEGER", mode="NULLABLE"),
    SchemaField("overall_damage_score", "INTEGER", mode="NULLABLE"),
    SchemaField("llm_used", "STRING", mode="NULLABLE"),
    SchemaField("input_timestamp", "TIMESTAMP", mode="NULLABLE"),
    SchemaField("output_timestamp", "TIMESTAMP", mode="NULLABLE"),
    SchemaField("processing_ms", "INTEGER", mode="NULLABLE"),
]

AI_AUDIT_IMAGES_SCHEMA = [
    SchemaField("audit_id", "STRING", mode="REQUIRED"),
    SchemaField("image_index", "INTEGER", mode="NULLABLE"),
    SchemaField("filename", "STRING", mode="NULLABLE"),
    SchemaField("gcs_uri", "STRING", mode="NULLABLE"),
    SchemaField("valid", "BOOLEAN", mode="NULLABLE"),
    SchemaField("reason", "STRING", mode="NULLABLE"),
    SchemaField("plate", "STRING", mode="NULLABLE"),
    SchemaField("color", "STRING", mode="NULLABLE"),
    SchemaField("damage_detected", "BOOLEAN", mode="NULLABLE"),
    SchemaField("damage_details", "STRING", mode="NULLABLE"),
    SchemaField("has_exif", "BOOLEAN", mode="NULLABLE"),
    SchemaField("capture_date", "DATE", mode="NULLABLE"),
    SchemaField("current_date", "DATE", mode="NULLABLE"),
    SchemaField("is_same_day", "BOOLEAN", mode="NULLABLE"),
]

AI_AUDIT_VEHICLE_PARTS_SCHEMA = [
    SchemaField("audit_id", "STRING", mode="REQUIRED"),
    SchemaField("part", "STRING", mode="NULLABLE"),
    SchemaField("visible_in_image", "BOOLEAN", mode="NULLABLE"),
    SchemaField("source_image_index", "INTEGER", mode="NULLABLE"),
    SchemaField("damaged", "BOOLEAN", mode="NULLABLE"),
    SchemaField("damage_types", "STRING", mode="NULLABLE"),
    SchemaField("severity", "INTEGER", mode="NULLABLE"),
    SchemaField("confidence", "FLOAT", mode="NULLABLE"),
]

AI_LLM_API_CALLS_SCHEMA = [
    SchemaField("date", "DATE", mode="NULLABLE"),
    SchemaField("model_name", "STRING", mode="NULLABLE"),
    SchemaField("total_calls", "INTEGER", mode="NULLABLE"),
    SchemaField("failed_count", "INTEGER", mode="NULLABLE"),
    SchemaField("last_error", "STRING", mode="NULLABLE"),
]

TABLE_SCHEMAS = {
    "AI_audits": AI_AUDITS_SCHEMA,
    "AI_audit_images": AI_AUDIT_IMAGES_SCHEMA,
    "AI_audit_vehicle_parts": AI_AUDIT_VEHICLE_PARTS_SCHEMA,
    "AI_llm_api_calls": AI_LLM_API_CALLS_SCHEMA,
}
