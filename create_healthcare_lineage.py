"""
Step 2: Connect healthcare_db tables and views with table-level and column-level lineage.
"""
from datahub.emitter.rest_emitter import DatahubRestEmitter
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.metadata.schema_classes import (
    UpstreamLineageClass,
    UpstreamClass,
    DatasetLineageTypeClass,
    FineGrainedLineageClass,
    FineGrainedLineageUpstreamTypeClass,
    FineGrainedLineageDownstreamTypeClass
)

GMS_SERVER = "http://localhost:8080"
PLATFORM = "postgres"
DATABASE = "healthcare_db"
SCHEMA = "public"
ENV = "PROD"

emitter = DatahubRestEmitter(gms_server=GMS_SERVER)

def make_ds_urn(table_name: str) -> str:
    return f"urn:li:dataset:(urn:li:dataPlatform:{PLATFORM},{DATABASE}.{SCHEMA}.{table_name},{ENV})"

def make_field_urn(table_name: str, field_name: str) -> str:
    ds_urn = make_ds_urn(table_name)
    return f"urn:li:schemaField:({ds_urn},{field_name})"

LINEAGE_CONFIG = {
    # 1. stg_patients <- raw_patients
    "stg_patients": {
        "upstreams": ["raw_patients"],
        "column_mappings": [
            ("patient_id", [("raw_patients", "patient_id")]),
            ("full_name", [("raw_patients", "full_name")]),
            ("age_years", [("raw_patients", "date_of_birth")]),
            ("gender", [("raw_patients", "gender")]),
            ("blood_type", [("raw_patients", "blood_type")]),
            ("city", [("raw_patients", "city")]),
        ]
    },

    # 2. stg_appointments <- raw_appointments, raw_doctors
    "stg_appointments": {
        "upstreams": ["raw_appointments", "raw_doctors"],
        "column_mappings": [
            ("appointment_id", [("raw_appointments", "appointment_id")]),
            ("patient_id", [("raw_appointments", "patient_id")]),
            ("doctor_id", [("raw_appointments", "doctor_id")]),
            ("doctor_name", [("raw_doctors", "doctor_name")]),
            ("specialty", [("raw_doctors", "specialty")]),
            ("hospital_branch", [("raw_doctors", "hospital_branch")]),
            ("appointment_date", [("raw_appointments", "appointment_date")]),
            ("status", [("raw_appointments", "status")]),
            ("consultation_fee", [("raw_appointments", "consultation_fee")]),
        ]
    },

    # 3. fct_patient_encounters <- stg_patients, stg_appointments
    "fct_patient_encounters": {
        "upstreams": ["stg_patients", "stg_appointments"],
        "column_mappings": [
            ("encounter_id", [("stg_appointments", "appointment_id")]),
            ("patient_id", [("stg_patients", "patient_id")]),
            ("patient_name", [("stg_patients", "full_name")]),
            ("age_years", [("stg_patients", "age_years")]),
            ("gender", [("stg_patients", "gender")]),
            ("doctor_id", [("stg_appointments", "doctor_id")]),
            ("doctor_name", [("stg_appointments", "doctor_name")]),
            ("specialty", [("stg_appointments", "specialty")]),
            ("hospital_branch", [("stg_appointments", "hospital_branch")]),
            ("appointment_date", [("stg_appointments", "appointment_date")]),
            ("encounter_status", [("stg_appointments", "status")]),
            ("consultation_fee", [("stg_appointments", "consultation_fee")]),
        ]
    },

    # 4. patient_billing_summary <- fct_patient_encounters, raw_lab_tests
    "patient_billing_summary": {
        "upstreams": ["fct_patient_encounters", "raw_lab_tests"],
        "column_mappings": [
            ("patient_id", [("fct_patient_encounters", "patient_id")]),
            ("patient_name", [("fct_patient_encounters", "patient_name")]),
            ("total_visits", [("fct_patient_encounters", "encounter_id")]),
            ("total_consultation_fees", [("fct_patient_encounters", "consultation_fee")]),
            ("total_lab_fees", [("raw_lab_tests", "test_cost")]),
            ("grand_total_billed", [
                ("fct_patient_encounters", "consultation_fee"),
                ("raw_lab_tests", "test_cost")
            ]),
        ]
    },

    # 5. doctor_revenue_summary <- fct_patient_encounters
    "doctor_revenue_summary": {
        "upstreams": ["fct_patient_encounters"],
        "column_mappings": [
            ("doctor_id", [("fct_patient_encounters", "doctor_id")]),
            ("doctor_name", [("fct_patient_encounters", "doctor_name")]),
            ("specialty", [("fct_patient_encounters", "specialty")]),
            ("total_appointments", [("fct_patient_encounters", "encounter_id")]),
            ("completed_appointments", [("fct_patient_encounters", "encounter_status")]),
            ("total_consultation_revenue", [("fct_patient_encounters", "consultation_fee")]),
        ]
    }
}

print(f"Emitting multi-tier lineage to DataHub GMS at {GMS_SERVER}...")

for downstream_table, cfg in LINEAGE_CONFIG.items():
    downstream_urn = make_ds_urn(downstream_table)
    
    # Construct UpstreamClass list
    upstreams_list = [
        UpstreamClass(
            dataset=make_ds_urn(u_table),
            type=DatasetLineageTypeClass.TRANSFORMED
        )
        for u_table in cfg["upstreams"]
    ]
    
    # Construct FineGrainedLineageClass list (Column-Level Lineage)
    fine_grained_list = []
    for down_col, up_col_list in cfg["column_mappings"]:
        downstream_field_urn = make_field_urn(downstream_table, down_col)
        upstream_field_urns = [
            make_field_urn(u_tbl, u_col) for u_tbl, u_col in up_col_list
        ]
        
        fine_grained_list.append(
            FineGrainedLineageClass(
                upstreamType=FineGrainedLineageUpstreamTypeClass.FIELD_SET,
                upstreams=upstream_field_urns,
                downstreamType=FineGrainedLineageDownstreamTypeClass.FIELD,
                downstreams=[downstream_field_urn],
                confidenceScore=1.0
            )
        )
    
    lineage_aspect = UpstreamLineageClass(
        upstreams=upstreams_list,
        fineGrainedLineages=fine_grained_list
    )
    
    mcp = MetadataChangeProposalWrapper(
        entityUrn=downstream_urn,
        aspect=lineage_aspect
    )
    
    emitter.emit(mcp)
    print(f" Lineage established: {downstream_table} <- {cfg['upstreams']} ({len(fine_grained_list)} column mappings)")

print("\nStep 2 Complete: Lineage successfully established across all healthcare_db tables!")
