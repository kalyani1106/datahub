#!/usr/bin/env python3
"""
=============================================================================
Ingest New Database into DataHub: fintech_db
=============================================================================
Registers a brand new enterprise database domain 'fintech_db' into DataHub
with 6 tables/views, rich schema definitions, primary keys, tags, descriptions,
and multi-tier lineage (raw tables -> staging view -> analytics mart).

This demonstrates that new databases added to DataHub are automatically
and dynamically detected and materialized into the Knowledge Graph.
=============================================================================
"""

import sys
import logging
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
    AuditStampClass,
    GlobalTagsClass,
    TagAssociationClass,
    UpstreamLineageClass,
    UpstreamClass,
    DatasetLineageTypeClass,
    FineGrainedLineageClass,
    FineGrainedLineageUpstreamTypeClass,
    FineGrainedLineageDownstreamTypeClass
)

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("FintechIngest")

GMS_SERVER = "http://localhost:8080"
PLATFORM = "postgres"
DATABASE = "fintech_db"
SCHEMA = "public"
ENV = "PROD"

emitter = DatahubRestEmitter(gms_server=GMS_SERVER)
audit_stamp = AuditStampClass(time=0, actor="urn:li:corpuser:fintech_engineer")

def make_ds_urn(table_name: str) -> str:
    return f"urn:li:dataset:(urn:li:dataPlatform:{PLATFORM},{DATABASE}.{SCHEMA}.{table_name},{ENV})"

def make_field_urn(table_name: str, field_name: str) -> str:
    ds_urn = make_ds_urn(table_name)
    return f"urn:li:schemaField:({ds_urn},{field_name})"

TABLES = {
    "accounts": {
        "subtype": "Table",
        "description": "Core banking deposit and checking accounts master register.",
        "tags": ["Fintech", "CoreBanking", "Confidential"],
        "fields": [
            ("account_id", NumberTypeClass(), "Primary key: unique system identifier for account", True),
            ("customer_id", NumberTypeClass(), "External customer identifier reference", False),
            ("account_number", StringTypeClass(), "Masked IBAN or customer account number", False),
            ("account_type", StringTypeClass(), "Checking, Savings, Business, or Escrow", False),
            ("balance", NumberTypeClass(), "Current ledger balance in base currency", False),
            ("currency", StringTypeClass(), "ISO 4217 currency code (USD, EUR, GBP)", False),
            ("status", StringTypeClass(), "Account lifecycle status: ACTIVE, FROZEN, CLOSED", False),
            ("opened_at", TimeTypeClass(), "Timestamp when account was created", False),
        ]
    },
    "transactions": {
        "subtype": "Table",
        "description": "Real-time ledger recording debits, credits, and wire transfers.",
        "tags": ["Fintech", "Ledger", "HighVolume"],
        "fields": [
            ("transaction_id", NumberTypeClass(), "Primary key: unique monetary event identifier", True),
            ("account_id", NumberTypeClass(), "Foreign key referencing accounts.account_id", False),
            ("transaction_type", StringTypeClass(), "DEBIT, CREDIT, TRANSFER, REFUND", False),
            ("amount", NumberTypeClass(), "Monetary transaction principal value", False),
            ("fee", NumberTypeClass(), "Processing or interchange fee", False),
            ("status", StringTypeClass(), "PENDING, SETTLED, DECLINED, REVERSED", False),
            ("created_at", TimeTypeClass(), "Timestamp when transaction was recorded", False),
        ]
    },
    "merchants": {
        "subtype": "Table",
        "description": "Commercial merchant vendor profiles and payment gateway terminals.",
        "tags": ["Fintech", "Merchants", "PCI-DSS"],
        "fields": [
            ("merchant_id", NumberTypeClass(), "Primary key: unique merchant profile ID", True),
            ("merchant_name", StringTypeClass(), "Official trade or business name", False),
            ("merchant_category", StringTypeClass(), "MCC code classification (e.g. Retail, Food, Tech)", False),
            ("country", StringTypeClass(), "Country jurisdiction code (ISO 3166-1)", False),
            ("account_id", NumberTypeClass(), "Settlement destination account ID", False),
        ]
    },
    "fraud_alerts": {
        "subtype": "Table",
        "description": "Automated fraud scoring flags for high-risk or anomalous transactions.",
        "tags": ["Fintech", "Security", "RiskCompliance"],
        "fields": [
            ("alert_id", NumberTypeClass(), "Primary key: unique fraud incident identifier", True),
            ("transaction_id", NumberTypeClass(), "Foreign key referencing transactions.transaction_id", False),
            ("account_id", NumberTypeClass(), "Foreign key referencing accounts.account_id", False),
            ("risk_score", NumberTypeClass(), "ML fraud probability score (0.00 to 1.00)", False),
            ("alert_severity", StringTypeClass(), "LOW, MEDIUM, HIGH, CRITICAL", False),
            ("is_blocked", BooleanTypeClass(), "Whether transaction was halted by risk engine", False),
            ("flagged_at", TimeTypeClass(), "Timestamp when risk alert was triggered", False),
        ]
    },
    "stg_account_transactions": {
        "subtype": "View",
        "description": "Cleansed staging view joining transactional events with account holder metadata.",
        "tags": ["Fintech", "Staging", "Analytical"],
        "fields": [
            ("transaction_id", NumberTypeClass(), "Primary key: unique transaction identifier", True),
            ("account_id", NumberTypeClass(), "Account reference", False),
            ("account_number", StringTypeClass(), "Account number", False),
            ("account_type", StringTypeClass(), "Account category", False),
            ("amount", NumberTypeClass(), "Transaction principal amount", False),
            ("transaction_type", StringTypeClass(), "Type of transaction", False),
            ("status", StringTypeClass(), "Transaction status", False),
            ("created_at", TimeTypeClass(), "Transaction timestamp", False),
        ]
    },
    "daily_settlement_summary": {
        "subtype": "View",
        "description": "Daily financial settlement mart summarizing transaction volume and merchant fees.",
        "tags": ["Fintech", "Mart", "Reporting"],
        "fields": [
            ("account_id", NumberTypeClass(), "Primary key: settlement account ID", True),
            ("total_transactions", NumberTypeClass(), "Count of daily settled transactions", False),
            ("total_settled_amount", NumberTypeClass(), "Sum of settled transaction amounts", False),
            ("total_fees_collected", NumberTypeClass(), "Sum of interchange and gateway fees", False),
            ("settlement_date", DateTypeClass(), "Calendar settlement date", False),
        ]
    }
}

LINEAGE_CONFIG = {
    # 1. stg_account_transactions derives from accounts and transactions
    "stg_account_transactions": {
        "upstreams": ["accounts", "transactions"],
        "column_mappings": [
            ("transaction_id", [("transactions", "transaction_id")]),
            ("account_id", [("transactions", "account_id")]),
            ("account_number", [("accounts", "account_number")]),
            ("account_type", [("accounts", "account_type")]),
            ("amount", [("transactions", "amount")]),
            ("transaction_type", [("transactions", "transaction_type")]),
            ("status", [("transactions", "status")]),
            ("created_at", [("transactions", "created_at")]),
        ]
    },
    # 2. daily_settlement_summary derives from stg_account_transactions and merchants
    "daily_settlement_summary": {
        "upstreams": ["stg_account_transactions", "merchants"],
        "column_mappings": [
            ("account_id", [("stg_account_transactions", "account_id")]),
            ("total_transactions", [("stg_account_transactions", "transaction_id")]),
            ("total_settled_amount", [("stg_account_transactions", "amount")]),
            ("total_fees_collected", [("stg_account_transactions", "amount")]),
            ("settlement_date", [("stg_account_transactions", "created_at")]),
        ]
    }
}

def ingest_tables():
    logger.info("Registering fintech_db tables and views in DataHub...")
    for table_name, meta in TABLES.items():
        ds_urn = make_ds_urn(table_name)
        
        # 1. Dataset properties
        prop_mcp = MetadataChangeProposalWrapper(
            entityUrn=ds_urn,
            aspect=DatasetPropertiesClass(
                name=table_name,
                description=meta["description"],
                customProperties={
                    "database": DATABASE,
                    "platform": PLATFORM,
                    "domain": "Fintech & Banking",
                    "sla": "Real-time"
                }
            )
        )
        emitter.emit(prop_mcp)

        # 2. Subtypes
        subtype_mcp = MetadataChangeProposalWrapper(
            entityUrn=ds_urn,
            aspect=SubTypesClass(typeNames=[meta["subtype"]])
        )
        emitter.emit(subtype_mcp)

        # 3. Tags
        tags = [TagAssociationClass(tag=f"urn:li:tag:{t}") for t in meta["tags"]]
        tag_mcp = MetadataChangeProposalWrapper(
            entityUrn=ds_urn,
            aspect=GlobalTagsClass(tags=tags)
        )
        emitter.emit(tag_mcp)

        # 4. Schema Metadata
        schema_fields = []
        for col_name, col_type, col_desc, is_pk in meta["fields"]:
            schema_fields.append(
                SchemaFieldClass(
                    fieldPath=col_name,
                    type=SchemaFieldDataTypeClass(type=col_type),
                    nativeDataType=type(col_type).__name__.replace("TypeClass", "").lower(),
                    description=col_desc,
                    isPartOfKey=is_pk,
                    nullable=not is_pk
                )
            )

        schema_mcp = MetadataChangeProposalWrapper(
            entityUrn=ds_urn,
            aspect=SchemaMetadataClass(
                schemaName=table_name,
                platform=f"urn:li:dataPlatform:{PLATFORM}",
                version=0,
                created=audit_stamp,
                lastModified=audit_stamp,
                hash="",
                platformSchema=OtherSchemaClass(rawSchema=f"CREATE TABLE {table_name} ..."),
                fields=schema_fields
            )
        )
        emitter.emit(schema_mcp)
        logger.info("  [+] Registered: %s.%s.%s (%s)", DATABASE, SCHEMA, table_name, meta["subtype"])

def ingest_lineage():
    logger.info("Connecting fintech_db lineage relationships...")
    for target_name, config in LINEAGE_CONFIG.items():
        target_urn = make_ds_urn(target_name)
        
        upstreams = [
            UpstreamClass(
                dataset=make_ds_urn(up_name),
                type=DatasetLineageTypeClass.TRANSFORMED,
                auditStamp=audit_stamp
            )
            for up_name in config["upstreams"]
        ]

        fine_grained = []
        for down_col, up_col_list in config["column_mappings"]:
            down_urn = make_field_urn(target_name, down_col)
            up_urns = [make_field_urn(up_t, up_c) for up_t, up_c in up_col_list]
            fine_grained.append(
                FineGrainedLineageClass(
                    upstreamType=FineGrainedLineageUpstreamTypeClass.FIELD_SET,
                    upstreams=up_urns,
                    downstreamType=FineGrainedLineageDownstreamTypeClass.FIELD,
                    downstreams=[down_urn],
                    confidenceScore=1.0
                )
            )

        lineage_mcp = MetadataChangeProposalWrapper(
            entityUrn=target_urn,
            aspect=UpstreamLineageClass(
                upstreams=upstreams,
                fineGrainedLineages=fine_grained
            )
        )
        emitter.emit(lineage_mcp)
        logger.info("  [+] Attached lineage to %s <- %s", target_name, config["upstreams"])

if __name__ == "__main__":
    logger.info("=== STARTING INGESTION OF NEW DATABASE: fintech_db ===")
    ingest_tables()
    ingest_lineage()
    logger.info("=== FINTECH_DB INGESTION COMPLETED SUCCESSFULLY ===")
