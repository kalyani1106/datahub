"""
Step 1: Register all healthcare_db tables and views in DataHub without lineage.
"""
import sys
from datahub.emitter.rest_emitter import DatahubRestEmitter
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.metadata.schema_classes import (
    DatasetPropertiesClass,
    SubTypesClass,
    SchemaMetadataClass,
    SchemaFieldClass,
    SchemaFieldDataTypeClass,
    OtherSchemaClass,
    NumberTypeClass,
    StringTypeClass,
    DateTypeClass,
    TimeTypeClass,
    BooleanTypeClass,
    AuditStampClass
)

GMS_SERVER = "http://localhost:8080"
PLATFORM = "postgres"
DATABASE = "healthcare_db"
SCHEMA = "public"
ENV = "PROD"

emitter = DatahubRestEmitter(gms_server=GMS_SERVER)
audit_stamp = AuditStampClass(time=0, actor="urn:li:corpuser:data_engineer")

def make_urn(table_name: str) -> str:
    return f"urn:li:dataset:(urn:li:dataPlatform:{PLATFORM},{DATABASE}.{SCHEMA}.{table_name},{ENV})"

# Define table metadata and schemas
TABLES = {
    "raw_patients": {
        "type": "Table",
        "description": "Raw patient master records captured from hospital intake registration systems.",
        "fields": [
            ("patient_id", NumberTypeClass(), "Unique system-generated primary key for each patient", True),
            ("full_name", StringTypeClass(), "Patient legal full name", False),
            ("date_of_birth", DateTypeClass(), "Patient official date of birth", False),
            ("gender", StringTypeClass(), "Patient administrative gender (Male, Female, Other)", False),
            ("blood_type", StringTypeClass(), "ABO and Rh blood group system (e.g. O+, A+, B+)", False),
            ("city", StringTypeClass(), "Primary residential city of the patient", False),
            ("registered_at", TimeTypeClass(), "Timestamp when patient record was initially created", False),
        ]
    },
    "raw_doctors": {
        "type": "Table",
        "description": "Raw physician roster with assigned medical departments and hospital branches.",
        "fields": [
            ("doctor_id", NumberTypeClass(), "Unique identifier for licensed hospital physician", True),
            ("doctor_name", StringTypeClass(), "Doctor full name and title", False),
            ("specialty", StringTypeClass(), "Clinical medical specialty (e.g., Cardiology, Neurology)", False),
            ("department", StringTypeClass(), "Hospital organizational department name", False),
            ("hospital_branch", StringTypeClass(), "Physical facility or hospital campus location", False),
        ]
    },
    "raw_appointments": {
        "type": "Table",
        "description": "Raw consultation and clinic appointment booking events.",
        "fields": [
            ("appointment_id", NumberTypeClass(), "Unique primary key for the scheduled appointment", True),
            ("patient_id", NumberTypeClass(), "Foreign key reference to raw_patients", False),
            ("doctor_id", NumberTypeClass(), "Foreign key reference to raw_doctors", False),
            ("appointment_date", TimeTypeClass(), "Scheduled consultation date and time", False),
            ("status", StringTypeClass(), "Appointment status: SCHEDULED, COMPLETED, CANCELLED", False),
            ("consultation_fee", NumberTypeClass(), "Base fee charged for physician consultation", False),
        ]
    },
    "raw_lab_tests": {
        "type": "Table",
        "description": "Raw laboratory test orders, clinical diagnostics, and lab test results.",
        "fields": [
            ("test_id", NumberTypeClass(), "Unique identifier for clinical diagnostic lab order", True),
            ("appointment_id", NumberTypeClass(), "Foreign key linking lab test to appointment", False),
            ("test_name", StringTypeClass(), "Name of diagnostic procedure (e.g. Lipid Profile, MRI, ECG)", False),
            ("test_cost", NumberTypeClass(), "Direct cost billed for performing the lab diagnostic", False),
            ("test_result", StringTypeClass(), "Clinical diagnostic outcome or status flag", False),
            ("completed_at", TimeTypeClass(), "Timestamp when laboratory report was finalized", False),
        ]
    },
    "stg_patients": {
        "type": "View",
        "description": "Cleansed patient staging view with standardized demographics and computed patient age.",
        "fields": [
            ("patient_id", NumberTypeClass(), "Standardized patient identifier", True),
            ("full_name", StringTypeClass(), "Validated patient full name", False),
            ("age_years", NumberTypeClass(), "Computed current age in completed years from birth date", False),
            ("gender", StringTypeClass(), "Standardized demographic gender", False),
            ("blood_type", StringTypeClass(), "Verified blood group classification", False),
            ("city", StringTypeClass(), "Residential municipality", False),
        ]
    },
    "stg_appointments": {
        "type": "View",
        "description": "Enriched appointment staging view joining appointment transactions with physician metadata.",
        "fields": [
            ("appointment_id", NumberTypeClass(), "Appointment reference number", True),
            ("patient_id", NumberTypeClass(), "Patient reference key", False),
            ("doctor_id", NumberTypeClass(), "Attending physician key", False),
            ("doctor_name", StringTypeClass(), "Attending physician full name", False),
            ("specialty", StringTypeClass(), "Physician clinical medical specialty", False),
            ("hospital_branch", StringTypeClass(), "Hospital campus where consultation occurred", False),
            ("appointment_date", TimeTypeClass(), "Consultation timestamp", False),
            ("status", StringTypeClass(), "Finalized encounter status", False),
            ("consultation_fee", NumberTypeClass(), "Standardized consultation charge", False),
        ]
    },
    "fct_patient_encounters": {
        "type": "View",
        "description": "Core dimensional fact view uniting patient demographics with clinical encounter events.",
        "fields": [
            ("encounter_id", NumberTypeClass(), "Surrogate encounter key (from appointment_id)", True),
            ("patient_id", NumberTypeClass(), "Conformed patient dimensional identifier", False),
            ("patient_name", StringTypeClass(), "Patient full name", False),
            ("age_years", NumberTypeClass(), "Patient age at time of encounter", False),
            ("gender", StringTypeClass(), "Patient demographic gender", False),
            ("doctor_id", NumberTypeClass(), "Attending physician dimensional identifier", False),
            ("doctor_name", StringTypeClass(), "Physician full name", False),
            ("specialty", StringTypeClass(), "Clinical specialty for the encounter", False),
            ("hospital_branch", StringTypeClass(), "Hospital branch location", False),
            ("appointment_date", TimeTypeClass(), "Timestamp of clinical encounter", False),
            ("encounter_status", StringTypeClass(), "Encounter lifecycle completion status", False),
            ("consultation_fee", NumberTypeClass(), "Encounter consultation revenue", False),
        ]
    },
    "patient_billing_summary": {
        "type": "View",
        "description": "Analytical financial mart aggregating visit counts, consultation charges, and lab testing fees per patient.",
        "fields": [
            ("patient_id", NumberTypeClass(), "Patient master identifier", True),
            ("patient_name", StringTypeClass(), "Patient full name", False),
            ("total_visits", NumberTypeClass(), "Count of clinical appointments attended by patient", False),
            ("total_consultation_fees", NumberTypeClass(), "Cumulative doctor consultation fees billed", False),
            ("total_lab_fees", NumberTypeClass(), "Cumulative clinical laboratory diagnostics fees billed", False),
            ("grand_total_billed", NumberTypeClass(), "Combined grand total billing amount (consultation + lab fees)", False),
        ]
    },
    "doctor_revenue_summary": {
        "type": "View",
        "description": "Operational analytics mart tracking appointment volume, completion rates, and total revenue per physician.",
        "fields": [
            ("doctor_id", NumberTypeClass(), "Physician unique staff identifier", True),
            ("doctor_name", StringTypeClass(), "Physician full name", False),
            ("specialty", StringTypeClass(), "Medical specialty area", False),
            ("total_appointments", NumberTypeClass(), "Total appointment slots booked", False),
            ("completed_appointments", NumberTypeClass(), "Count of successfully completed appointments", False),
            ("total_consultation_revenue", NumberTypeClass(), "Total consultation revenue generated by doctor", False),
        ]
    }
}

print(f"Connecting to DataHub GMS at {GMS_SERVER}...")

for table_name, meta in TABLES.items():
    dataset_urn = make_urn(table_name)
    print(f"Creating table in DataHub: {DATABASE}.{SCHEMA}.{table_name} ({meta['type']})")
    
    # 1. Dataset Properties
    props = DatasetPropertiesClass(
        name=table_name,
        description=meta["description"],
        customProperties={
            "database": DATABASE,
            "schema": SCHEMA,
            "table_type": meta["type"],
            "domain": "Healthcare Analytics"
        }
    )
    mcp_props = MetadataChangeProposalWrapper(
        entityUrn=dataset_urn,
        aspect=props
    )
    emitter.emit(mcp_props)
    
    # 2. SubTypes
    subtypes = SubTypesClass(typeNames=[meta["type"]])
    mcp_subtypes = MetadataChangeProposalWrapper(
        entityUrn=dataset_urn,
        aspect=subtypes
    )
    emitter.emit(mcp_subtypes)
    
    # 3. Schema Metadata
    fields = []
    for col_name, col_type, col_desc, is_key in meta["fields"]:
        fields.append(
            SchemaFieldClass(
                fieldPath=col_name,
                type=SchemaFieldDataTypeClass(type=col_type),
                nativeDataType="NUMERIC" if isinstance(col_type, NumberTypeClass) else "VARCHAR",
                description=col_desc,
                isPartOfKey=is_key,
                nullable=not is_key,
                recursive=False
            )
        )
    
    schema = SchemaMetadataClass(
        schemaName=f"{DATABASE}.{SCHEMA}.{table_name}",
        platform=f"urn:li:dataPlatform:{PLATFORM}",
        version=0,
        hash="",
        platformSchema=OtherSchemaClass(rawSchema=""),
        created=audit_stamp,
        lastModified=audit_stamp,
        fields=fields
    )
    mcp_schema = MetadataChangeProposalWrapper(
        entityUrn=dataset_urn,
        aspect=schema
    )
    emitter.emit(mcp_schema)

print("\nStep 1 Complete: All 9 tables and views successfully created in DataHub!")
