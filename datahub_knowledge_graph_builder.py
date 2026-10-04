#!/usr/bin/env python3
"""
=============================================================================
DataHub Knowledge Graph Builder & Apache AGE Integration
=============================================================================
Dynamically extracts dataset metadata from DataHub, identifies underlying
database groupings, infers semantic relationships, and constructs a rich
Knowledge Graph inside Apache AGE (PostgreSQL).

Graph Schema:
  - Nodes:
      (:Database {id, name, platform, table_count})
      (:Schema {id, name, database, platform})
      (:Table {id, name, full_name, schema, database, platform, urn, subtype, description, column_count, tags})
      (:Column {id, name, table, table_urn, type, is_pk, description})
  - Edges:
      (:Database)-[:CONTAINS]->(:Schema)
      (:Schema)-[:CONTAINS]->(:Table)
      (:Table)-[:CONTAINS]->(:Column)
      (:Table)-[:REFERENCES {from_column, to_column, is_inferred, confidence, match_rule}]->(:Table)
      (:Column)-[:REFERENCES {is_inferred, confidence, match_rule}]->(:Column)
      (:Table)-[:DERIVES_FROM {lineage_type, is_inferred, confidence}]->(:Table)
      (:Column)-[:DERIVES_FROM {is_inferred, confidence}]->(:Column)
      (:Table)-[:DEPENDS_ON {dependency_type}]->(:Table)

Author: Advanced Agentic Engineer
=============================================================================
"""

import os
import sys
import json
import logging
import requests
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict
import psycopg

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("DataHubKG")

# Configurations
DATAHUB_GMS_URL = os.getenv("DATAHUB_GMS_URL", "http://localhost:8080")
POSTGRES_HOST = os.getenv("AGE_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("AGE_PORT", "5455"))
POSTGRES_DB = os.getenv("AGE_DB", "knowledge_graph_demo")
POSTGRES_USER = os.getenv("AGE_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("AGE_PASSWORD", "postgres")
GRAPH_NAME = os.getenv("AGE_GRAPH_NAME", "datahub_knowledge_graph")

# Import DataHub SDK if available
try:
    from datahub.ingestion.graph.client import DataHubGraph
    from datahub.ingestion.graph.config import DatahubClientConfig
    from datahub.metadata.schema_classes import (
        SchemaMetadataClass,
        UpstreamLineageClass,
        DatasetPropertiesClass,
        GlobalTagsClass,
        SubTypesClass
    )
    DATAHUB_SDK_AVAILABLE = True
except ImportError:
    DATAHUB_SDK_AVAILABLE = False
    logger.warning("datahub package not available; fallback to REST API only.")


# =============================================================================
# 1. METADATA EXTRACTION FROM DATAHUB
# =============================================================================

class DataHubMetadataExtractor:
    """Dynamically extracts all datasets, schemas, and lineage from DataHub."""

    def __init__(self, gms_url: str = DATAHUB_GMS_URL):
        self.gms_url = gms_url.rstrip("/")
        self.graph_client = None
        if DATAHUB_SDK_AVAILABLE:
            try:
                self.graph_client = DataHubGraph(DatahubClientConfig(server=self.gms_url))
                logger.info("Initialized DataHubGraph SDK client connected to %s", self.gms_url)
            except Exception as e:
                logger.warning("Could not initialize DataHubGraph SDK: %s", e)

    def fetch_all_dataset_urns(self) -> List[str]:
        """Fetch all dataset URNs via DataHub OpenAPI."""
        url = f"{self.gms_url}/openapi/v3/entity/dataset?count=500"
        logger.info("Fetching dataset URNs from %s ...", url)
        try:
            res = requests.get(url, timeout=15)
            res.raise_for_status()
            data = res.json()
            entities = data.get("entities", [])
            urns = [e["urn"] for e in entities if "urn" in e]
            logger.info("Found %d dataset URNs in DataHub.", len(urns))
            return urns
        except Exception as e:
            logger.error("Failed to fetch dataset URNs: %s", e)
            return []

    def get_dataset_metadata(self, urn: str) -> Dict[str, Any]:
        """Retrieve full schema, properties, tags, and lineage for a dataset URN."""
        schema_meta = None
        lineage = None
        props = None
        subtypes = None
        tags = None

        if self.graph_client:
            try:
                schema_meta = self.graph_client.get_aspect(entity_urn=urn, aspect_type=SchemaMetadataClass)
            except Exception:
                pass
            try:
                lineage = self.graph_client.get_aspect(entity_urn=urn, aspect_type=UpstreamLineageClass)
            except Exception:
                pass
            try:
                props = self.graph_client.get_aspect(entity_urn=urn, aspect_type=DatasetPropertiesClass)
            except Exception:
                pass
            try:
                subtypes = self.graph_client.get_aspect(entity_urn=urn, aspect_type=SubTypesClass)
            except Exception:
                pass
            try:
                tags = self.graph_client.get_aspect(entity_urn=urn, aspect_type=GlobalTagsClass)
            except Exception:
                pass

        # Parse URN structure: urn:li:dataset:(urn:li:dataPlatform:<platform>,<dataset_name>,<env>)
        clean_urn = urn.replace("urn:li:dataset:(", "").rstrip(")")
        parts = clean_urn.split(",")
        platform = parts[0].replace("urn:li:dataPlatform:", "") if len(parts) > 0 else "unknown"
        full_name = parts[1] if len(parts) > 1 else "unknown"
        env = parts[2] if len(parts) > 2 else "PROD"

        # Split database, schema, table
        name_parts = full_name.split(".")
        if len(name_parts) >= 3:
            database = name_parts[0]
            schema = name_parts[1]
            table = ".".join(name_parts[2:])
        elif len(name_parts) == 2:
            database = "default"
            schema = name_parts[0]
            table = name_parts[1]
        else:
            database = "default"
            schema = "default"
            table = full_name

        # Parse fields
        fields = []
        if schema_meta and schema_meta.fields:
            for f in schema_meta.fields:
                native_type = f.nativeDataType
                if not native_type and f.type and hasattr(f.type, "type"):
                    native_type = type(f.type.type).__name__
                fields.append({
                    "name": f.fieldPath,
                    "type": native_type or "string",
                    "is_pk": bool(f.isPartOfKey),
                    "description": f.description or ""
                })

        # Parse lineage
        upstreams = []
        fine_grained = []
        if lineage:
            if lineage.upstreams:
                for u in lineage.upstreams:
                    upstreams.append({
                        "dataset": u.dataset,
                        "type": u.type or "TRANSFORMED"
                    })
            if lineage.fineGrainedLineages:
                for fg in lineage.fineGrainedLineages:
                    fine_grained.append({
                        "upstream_type": fg.upstreamType,
                        "upstreams": list(fg.upstreams) if fg.upstreams else [],
                        "downstream_type": fg.downstreamType,
                        "downstreams": list(fg.downstreams) if fg.downstreams else [],
                        "confidence": float(fg.confidenceScore) if fg.confidenceScore is not None else 1.0
                    })

        subtype_val = "Table"
        if subtypes and subtypes.typeNames:
            subtype_val = subtypes.typeNames[0].capitalize()

        description_val = props.description if props and props.description else ""
        tag_list = [t.tag.replace("urn:li:tag:", "") for t in tags.tags] if tags and tags.tags else []

        return {
            "urn": urn,
            "platform": platform,
            "database": database,
            "schema": schema,
            "table": table,
            "full_name": full_name,
            "env": env,
            "subtype": subtype_val,
            "description": description_val,
            "tags": tag_list,
            "fields": fields,
            "upstreams": upstreams,
            "fine_grained": fine_grained
        }

    def extract_catalog(self) -> List[Dict[str, Any]]:
        """Extract all metadata for all datasets registered in DataHub."""
        urns = self.fetch_all_dataset_urns()
        catalog = []
        for urn in urns:
            meta = self.get_dataset_metadata(urn)
            catalog.append(meta)
        logger.info("Successfully extracted complete metadata for %d datasets.", len(catalog))
        return catalog


# =============================================================================
# 2. GROUPING & RELATIONSHIP INFERENCE ENGINE
# =============================================================================

class KnowledgeGraphEngine:
    """
    Groups datasets by database, infers relationships, and constructs
    the complete graph topology (nodes and edges).
    """

    def __init__(self, catalog: List[Dict[str, Any]]):
        self.catalog = catalog
        self.nodes = []
        self.edges = []
        self.databases = {}
        self.schemas = {}
        self.tables = {}
        self.columns = {}
        self.db_groups = defaultdict(list)

    def build(self) -> Dict[str, Any]:
        """Run grouping, node generation, and relationship detection."""
        self._group_datasets()
        self._create_structural_nodes()
        self._detect_explicit_lineage()
        self._detect_semantic_references()
        return {
            "nodes": self.nodes,
            "edges": self.edges,
            "databases": list(self.databases.values()),
            "schemas": list(self.schemas.values()),
            "tables": list(self.tables.values()),
            "columns": list(self.columns.values()),
            "stats": self.get_summary_stats()
        }

    def _group_datasets(self):
        """Group datasets strictly by platform and database."""
        for d in self.catalog:
            db_key = f"{d['platform']}.{d['database']}"
            self.db_groups[db_key].append(d)
        logger.info("Grouped datasets into %d distinct database domains:", len(self.db_groups))
        for db_key, tbls in self.db_groups.items():
            logger.info("  • Database [%s]: %d tables/views", db_key, len(tbls))

    def _create_structural_nodes(self):
        """Create Database, Schema, Table, and Column vertices and CONTAINS edges."""
        for db_key, datasets in self.db_groups.items():
            first = datasets[0]
            platform = first["platform"]
            db_name = first["database"]

            db_node_id = f"db:{platform}.{db_name}"
            if db_node_id not in self.databases:
                db_node = {
                    "id": db_node_id,
                    "label": "Database",
                    "name": db_name,
                    "platform": platform,
                    "table_count": len(datasets)
                }
                self.databases[db_node_id] = db_node
                self.nodes.append(db_node)

            for d in datasets:
                schema_name = d["schema"]
                schema_node_id = f"schema:{platform}.{db_name}.{schema_name}"
                if schema_node_id not in self.schemas:
                    schema_node = {
                        "id": schema_node_id,
                        "label": "Schema",
                        "name": schema_name,
                        "database": db_name,
                        "platform": platform
                    }
                    self.schemas[schema_node_id] = schema_node
                    self.nodes.append(schema_node)

                    # Edge: Database -> Schema
                    self.edges.append({
                        "id": f"edge:contains:{db_node_id}->{schema_node_id}",
                        "label": "CONTAINS",
                        "from": db_node_id,
                        "to": schema_node_id,
                        "from_label": "Database",
                        "to_label": "Schema",
                        "properties": {}
                    })

                # Table node
                table_node_id = f"table:{d['urn']}"
                table_node = {
                    "id": table_node_id,
                    "label": "Table",
                    "name": d["table"],
                    "full_name": d["full_name"],
                    "schema": schema_name,
                    "database": db_name,
                    "platform": platform,
                    "urn": d["urn"],
                    "subtype": d["subtype"],
                    "description": d["description"],
                    "tags": d["tags"],
                    "column_count": len(d["fields"])
                }
                self.tables[table_node_id] = table_node
                self.nodes.append(table_node)

                # Edge: Schema -> Table
                self.edges.append({
                    "id": f"edge:contains:{schema_node_id}->{table_node_id}",
                    "label": "CONTAINS",
                    "from": schema_node_id,
                    "to": table_node_id,
                    "from_label": "Schema",
                    "to_label": "Table",
                    "properties": {}
                })

                # Column nodes & Table -> Column edges
                for f in d["fields"]:
                    col_node_id = f"col:{d['urn']}:{f['name']}"
                    col_node = {
                        "id": col_node_id,
                        "label": "Column",
                        "name": f["name"],
                        "table": d["table"],
                        "table_urn": d["urn"],
                        "type": f["type"],
                        "is_pk": f["is_pk"],
                        "description": f["description"]
                    }
                    self.columns[col_node_id] = col_node
                    self.nodes.append(col_node)

                    self.edges.append({
                        "id": f"edge:contains:{table_node_id}->{col_node_id}",
                        "label": "CONTAINS",
                        "from": table_node_id,
                        "to": col_node_id,
                        "from_label": "Table",
                        "to_label": "Column",
                        "properties": {}
                    })

    def _detect_explicit_lineage(self):
        """Extract explicit table-level and column-level lineage from DataHub."""
        urn_to_node_id = {d["urn"]: f"table:{d['urn']}" for d in self.catalog}

        for d in self.catalog:
            downstream_table_id = urn_to_node_id[d["urn"]]

            # Table-level lineage
            for up in d.get("upstreams", []):
                up_urn = up["dataset"]
                upstream_table_id = urn_to_node_id.get(up_urn)
                if not upstream_table_id:
                    # External or uncataloged upstream table
                    upstream_table_id = f"table:{up_urn}"

                lineage_type = up.get("type", "TRANSFORMED")

                # Edge: Downstream Table DERIVES_FROM Upstream Table
                self.edges.append({
                    "id": f"edge:derives:{downstream_table_id}->{upstream_table_id}",
                    "label": "DERIVES_FROM",
                    "from": downstream_table_id,
                    "to": upstream_table_id,
                    "from_label": "Table",
                    "to_label": "Table",
                    "properties": {
                        "lineage_type": lineage_type,
                        "is_inferred": False,
                        "confidence": 1.0
                    }
                })

                # Edge: Downstream Table DEPENDS_ON Upstream Table
                self.edges.append({
                    "id": f"edge:depends:{downstream_table_id}->{upstream_table_id}",
                    "label": "DEPENDS_ON",
                    "from": downstream_table_id,
                    "to": upstream_table_id,
                    "from_label": "Table",
                    "to_label": "Table",
                    "properties": {
                        "dependency_type": "data_lineage"
                    }
                })

            # Fine-grained column-level lineage
            for fg in d.get("fine_grained", []):
                score = fg.get("confidence", 1.0)
                for up_field_urn in fg.get("upstreams", []):
                    # up_field_urn format: urn:li:schemaField:(<dataset_urn>,<field_path>)
                    for down_field_urn in fg.get("downstreams", []):
                        col_up_id = self._parse_schema_field_urn(up_field_urn)
                        col_down_id = self._parse_schema_field_urn(down_field_urn)
                        if col_up_id and col_down_id:
                            self.edges.append({
                                "id": f"edge:col_derives:{col_down_id}->{col_up_id}",
                                "label": "DERIVES_FROM",
                                "from": col_down_id,
                                "to": col_up_id,
                                "from_label": "Column",
                                "to_label": "Column",
                                "properties": {
                                    "is_inferred": False,
                                    "confidence": score
                                }
                            })

    def _parse_schema_field_urn(self, field_urn: str) -> Optional[str]:
        """Convert DataHub schemaField URN into our Column node ID."""
        if not field_urn.startswith("urn:li:schemaField:("):
            return None
        inner = field_urn[len("urn:li:schemaField:("):].rstrip(")")
        # inner: urn:li:dataset:(urn:li:dataPlatform:postgres,healthcare_db.public.raw_patients,PROD),patient_id
        last_comma = inner.rfind(",")
        if last_comma == -1:
            return None
        dataset_urn = inner[:last_comma]
        field_name = inner[last_comma + 1:]
        return f"col:{dataset_urn}:{field_name}"

    def _detect_semantic_references(self):
        """
        Detects Foreign Key -> Primary Key relationships within the same database.
        Strict boundary: tables in different databases are never inferred to relate.
        """
        for db_key, datasets in self.db_groups.items():
            base_tables = [t for t in datasets if t["subtype"].lower() in ("table", "source")]
            view_tables = [t for t in datasets if t["subtype"].lower() in ("view", "model")]

            # Primary Key catalog: map entity PK column -> authoritative base table
            pk_catalog = {}
            for t in base_tables + view_tables:
                for f in t["fields"]:
                    if f.get("is_pk"):
                        if f["name"] not in pk_catalog or t["subtype"].lower() in ("table", "source"):
                            pk_catalog[f["name"]] = (t, f["name"])

            # Fallback heuristic for models without explicit is_pk aspect
            if not pk_catalog:
                for t in datasets:
                    candidates = [
                        f["name"] for f in t["fields"]
                        if f["name"] in (f"{t['table']}_id", f"{t['table'].rstrip('s')}_id", "id")
                    ]
                    for c in candidates:
                        if c not in pk_catalog:
                            pk_catalog[c] = (t, c)

            # Detect foreign key references across tables in this database
            for src_tbl in datasets:
                src_name = src_tbl["table"]
                src_cols = {f["name"]: f for f in src_tbl["fields"]}
                src_node_id = f"table:{src_tbl['urn']}"

                for target_pk_name, (target_tbl, target_pk_col) in pk_catalog.items():
                    target_name = target_tbl["table"]
                    target_node_id = f"table:{target_tbl['urn']}"

                    if src_name == target_name:
                        continue

                    # Check if src has a column referencing target PK
                    matched_col_name = None
                    if target_pk_name in src_cols:
                        matched_col_name = target_pk_name
                    elif target_pk_col == "id" and f"{target_name}_id" in src_cols:
                        matched_col_name = f"{target_name}_id"
                    elif target_pk_col == "id" and f"{target_name.rstrip('s')}_id" in src_cols:
                        matched_col_name = f"{target_name.rstrip('s')}_id"

                    if matched_col_name:
                        is_target_explicit_pk = any(
                            f["name"] == target_pk_col and f.get("is_pk")
                            for f in target_tbl["fields"]
                        )
                        confidence = 0.95 if is_target_explicit_pk else 0.85
                        match_rule = "explicit_pk_exact_match" if is_target_explicit_pk else "heuristic_id_match"

                        # Table REFERENCES Table edge
                        edge_id = f"edge:ref:{src_node_id}->{target_node_id}:{matched_col_name}"
                        self.edges.append({
                            "id": edge_id,
                            "label": "REFERENCES",
                            "from": src_node_id,
                            "to": target_node_id,
                            "from_label": "Table",
                            "to_label": "Table",
                            "properties": {
                                "from_column": matched_col_name,
                                "to_column": target_pk_col,
                                "is_inferred": True,
                                "confidence": confidence,
                                "match_rule": match_rule
                            }
                        })

                        # Column REFERENCES Column edge
                        col_src_id = f"col:{src_tbl['urn']}:{matched_col_name}"
                        col_tgt_id = f"col:{target_tbl['urn']}:{target_pk_col}"
                        self.edges.append({
                            "id": f"edge:col_ref:{col_src_id}->{col_tgt_id}",
                            "label": "REFERENCES",
                            "from": col_src_id,
                            "to": col_tgt_id,
                            "from_label": "Column",
                            "to_label": "Column",
                            "properties": {
                                "is_inferred": True,
                                "confidence": confidence,
                                "match_rule": match_rule
                            }
                        })

    def get_summary_stats(self) -> Dict[str, Any]:
        """Compute summary statistics for nodes and edges."""
        node_counts = defaultdict(int)
        for n in self.nodes:
            node_counts[n["label"]] += 1

        edge_counts = defaultdict(int)
        for e in self.edges:
            edge_counts[e["label"]] += 1

        explicit_edges = sum(1 for e in self.edges if not e.get("properties", {}).get("is_inferred", False))
        inferred_edges = sum(1 for e in self.edges if e.get("properties", {}).get("is_inferred", False))

        return {
            "total_nodes": len(self.nodes),
            "node_counts": dict(node_counts),
            "total_edges": len(self.edges),
            "edge_counts": dict(edge_counts),
            "explicit_edges": explicit_edges,
            "inferred_edges": inferred_edges,
            "database_count": len(self.databases),
            "schema_count": len(self.schemas),
            "table_count": len(self.tables),
            "column_count": len(self.columns)
        }


# =============================================================================
# 3. APACHE AGE LOADER (POSTGRESQL CYPHER)
# =============================================================================

class ApacheAGELoader:
    """Loads vertices and edges into PostgreSQL Apache AGE using Cypher."""

    def __init__(
        self,
        host: str = POSTGRES_HOST,
        port: int = POSTGRES_PORT,
        dbname: str = POSTGRES_DB,
        user: str = POSTGRES_USER,
        password: str = POSTGRES_PASSWORD,
        graph_name: str = GRAPH_NAME
    ):
        self.host = host
        self.port = port
        self.dbname = dbname
        self.user = user
        self.password = password
        self.graph_name = graph_name
        self.conn = None

    def connect(self):
        """Establish connection and initialize Apache AGE extension."""
        logger.info(
            "Connecting to PostgreSQL port %d (DB: %s, User: %s)...",
            self.port, self.dbname, self.user
        )
        self.conn = psycopg.connect(
            host=self.host,
            port=self.port,
            dbname=self.dbname,
            user=self.user,
            password=self.password
        )
        cur = self.conn.cursor()
        cur.execute("CREATE EXTENSION IF NOT EXISTS age;")
        cur.execute("LOAD 'age';")
        cur.execute('SET search_path = ag_catalog, "$user", public;')
        self.conn.commit()
        logger.info("Connected to PostgreSQL and loaded Apache AGE extension.")

    def reset_graph(self):
        """Drop existing graph if present and create a fresh graph."""
        cur = self.conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM ag_graph WHERE name = '{self.graph_name}';")
        exists = cur.fetchone()[0] > 0
        if exists:
            logger.info("Graph '%s' already exists. Dropping for clean idempotent build...", self.graph_name)
            cur.execute(f"SELECT drop_graph('{self.graph_name}', true);")
            self.conn.commit()
        logger.info("Creating graph '%s' in Apache AGE...", self.graph_name)
        cur.execute(f"SELECT create_graph('{self.graph_name}');")
        self.conn.commit()
        logger.info("Graph '%s' successfully created.", self.graph_name)

    @staticmethod
    def _clean_str(val: Any) -> str:
        """Sanitize strings for Cypher literals inside $$ blocks."""
        if val is None:
            return ""
        s = str(val)
        # Escape backslashes, single quotes, double quotes, and newlines
        return s.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"').replace("\n", " ").replace("\r", "")

    def load_graph(self, graph_data: Dict[str, Any]):
        """Load all nodes and edges into Apache AGE."""
        cur = self.conn.cursor()
        nodes = graph_data["nodes"]
        edges = graph_data["edges"]

        logger.info("Loading %d vertices into Apache AGE graph '%s'...", len(nodes), self.graph_name)

        # Batch 1: Database vertices
        for d in graph_data["databases"]:
            cypher = f"""
            CREATE (:Database {{
                id: '{self._clean_str(d['id'])}',
                name: '{self._clean_str(d['name'])}',
                platform: '{self._clean_str(d['platform'])}',
                table_count: {d['table_count']}
            }})
            """
            self._exec_cypher(cur, cypher)

        # Batch 2: Schema vertices
        for s in graph_data["schemas"]:
            cypher = f"""
            CREATE (:Schema {{
                id: '{self._clean_str(s['id'])}',
                name: '{self._clean_str(s['name'])}',
                database: '{self._clean_str(s['database'])}',
                platform: '{self._clean_str(s['platform'])}'
            }})
            """
            self._exec_cypher(cur, cypher)

        # Batch 3: Table vertices
        for t in graph_data["tables"]:
            tags_json = json.dumps(t["tags"])
            cypher = f"""
            CREATE (:Table {{
                id: '{self._clean_str(t['id'])}',
                name: '{self._clean_str(t['name'])}',
                full_name: '{self._clean_str(t['full_name'])}',
                schema: '{self._clean_str(t['schema'])}',
                database: '{self._clean_str(t['database'])}',
                platform: '{self._clean_str(t['platform'])}',
                urn: '{self._clean_str(t['urn'])}',
                subtype: '{self._clean_str(t['subtype'])}',
                description: '{self._clean_str(t['description'])}',
                column_count: {t['column_count']},
                tags: '{self._clean_str(tags_json)}'
            }})
            """
            self._exec_cypher(cur, cypher)

        # Batch 4: Column vertices
        for c in graph_data["columns"]:
            is_pk_str = "true" if c["is_pk"] else "false"
            cypher = f"""
            CREATE (:Column {{
                id: '{self._clean_str(c['id'])}',
                name: '{self._clean_str(c['name'])}',
                table: '{self._clean_str(c['table'])}',
                table_urn: '{self._clean_str(c['table_urn'])}',
                type: '{self._clean_str(c['type'])}',
                is_pk: {is_pk_str},
                description: '{self._clean_str(c['description'])}'
            }})
            """
            self._exec_cypher(cur, cypher)

        self.conn.commit()
        logger.info("All %d vertices loaded successfully.", len(nodes))

        # Batch 5: Edges
        logger.info("Loading %d edges into Apache AGE...", len(edges))
        edge_count = 0
        for e in edges:
            e_label = e["label"]
            from_id = self._clean_str(e["from"])
            to_id = self._clean_str(e["to"])
            from_lbl = e["from_label"]
            to_lbl = e["to_label"]
            props = e.get("properties", {})

            # Format properties string for Cypher
            prop_pairs = [f"id: '{self._clean_str(e['id'])}'"]
            for k, v in props.items():
                if isinstance(v, bool):
                    prop_pairs.append(f"{k}: {'true' if v else 'false'}")
                elif isinstance(v, (int, float)):
                    prop_pairs.append(f"{k}: {v}")
                else:
                    prop_pairs.append(f"{k}: '{self._clean_str(v)}'")
            props_str = "{" + ", ".join(prop_pairs) + "}"

            cypher = f"""
            MATCH (a:{from_lbl} {{id: '{from_id}'}})
            MATCH (b:{to_lbl} {{id: '{to_id}'}})
            CREATE (a)-[:{e_label} {props_str}]->(b)
            """
            try:
                self._exec_cypher(cur, cypher)
                edge_count += 1
            except Exception as ex:
                logger.warning("Failed to create edge %s -> %s (%s): %s", from_id, to_id, e_label, ex)

            if edge_count % 50 == 0:
                self.conn.commit()

        self.conn.commit()
        logger.info("Successfully loaded %d edges into Apache AGE.", edge_count)

    def _exec_cypher(self, cur, cypher_body: str):
        """Execute a single Cypher command via ag_catalog.cypher."""
        query = f"""
        SELECT * FROM ag_catalog.cypher(
            '{self.graph_name}',
            $$
            {cypher_body}
            $$
        ) AS (result agtype);
        """
        cur.execute(query)

    def verify_graph(self) -> Dict[str, Any]:
        """Execute verification queries to validate graph contents."""
        cur = self.conn.cursor()
        logger.info("Verifying Apache AGE graph '%s' contents...", self.graph_name)

        # Count total vertices
        cur.execute(f"""
        SELECT * FROM ag_catalog.cypher('{self.graph_name}', $$
            MATCH (n) RETURN count(n)
        $$) AS (cnt agtype);
        """)
        total_v = cur.fetchone()[0]

        # Count total edges
        cur.execute(f"""
        SELECT * FROM ag_catalog.cypher('{self.graph_name}', $$
            MATCH ()-[r]->() RETURN count(r)
        $$) AS (cnt agtype);
        """)
        total_e = cur.fetchone()[0]

        # Count per vertex label
        v_counts = {}
        for lbl in ["Database", "Schema", "Table", "Column"]:
            cur.execute(f"""
            SELECT * FROM ag_catalog.cypher('{self.graph_name}', $$
                MATCH (n:{lbl}) RETURN count(n)
            $$) AS (cnt agtype);
            """)
            v_counts[lbl] = cur.fetchone()[0]

        # Count per edge label
        e_counts = {}
        for lbl in ["CONTAINS", "REFERENCES", "DERIVES_FROM", "DEPENDS_ON"]:
            cur.execute(f"""
            SELECT * FROM ag_catalog.cypher('{self.graph_name}', $$
                MATCH ()-[r:{lbl}]->() RETURN count(r)
            $$) AS (cnt agtype);
            """)
            e_counts[lbl] = cur.fetchone()[0]

        logger.info("Verification results:")
        logger.info("  Total Vertices: %s (DB: %s, Schema: %s, Table: %s, Column: %s)",
                    total_v, v_counts.get("Database"), v_counts.get("Schema"), v_counts.get("Table"), v_counts.get("Column"))
        logger.info("  Total Edges: %s (CONTAINS: %s, REFERENCES: %s, DERIVES_FROM: %s, DEPENDS_ON: %s)",
                    total_e, e_counts.get("CONTAINS"), e_counts.get("REFERENCES"), e_counts.get("DERIVES_FROM"), e_counts.get("DEPENDS_ON"))

        return {
            "total_vertices": total_v,
            "vertex_counts": v_counts,
            "total_edges": total_e,
            "edge_counts": e_counts
        }

    def close(self):
        """Close database connection."""
        if self.conn and not self.conn.closed:
            self.conn.close()
            logger.info("Closed PostgreSQL connection.")


# =============================================================================
# 4. INTERACTIVE VISUALIZATION GENERATOR (HTML/JS)
# =============================================================================

class KnowledgeGraphVisualizer:
    """Generates a standalone, feature-rich interactive HTML visualization."""

    @staticmethod
    def generate_html(graph_data: Dict[str, Any], output_path: str):
        """Generate interactive HTML file with Vis.js network, search, and filters."""
        nodes_json = json.dumps(graph_data["nodes"])
        edges_json = json.dumps(graph_data["edges"])
        stats_json = json.dumps(graph_data["stats"])

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>DataHub Enterprise Knowledge Graph</title>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.2/css/bootstrap.min.css">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.2/css/all.min.css">
  <script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
  <style>
    body {{
      margin: 0;
      padding: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      background-color: #0f172a;
      color: #e2e8f0;
      overflow: hidden;
      height: 100vh;
    }}
    #app-container {{
      display: flex;
      height: 100vh;
      width: 100vw;
    }}
    #sidebar {{
      width: 380px;
      background: #1e293b;
      border-right: 1px solid #334155;
      display: flex;
      flex-direction: column;
      z-index: 10;
      box-shadow: 2px 0 10px rgba(0,0,0,0.4);
    }}
    #sidebar-header {{
      padding: 16px 20px;
      background: #0f172a;
      border-bottom: 1px solid #334155;
    }}
    #sidebar-header h5 {{
      margin: 0;
      font-weight: 700;
      color: #38bdf8;
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    #sidebar-controls {{
      padding: 16px 20px;
      overflow-y: auto;
      flex: 1;
    }}
    .control-section {{
      margin-bottom: 18px;
      background: #0f172a;
      padding: 12px 14px;
      border-radius: 8px;
      border: 1px solid #334155;
    }}
    .control-section h6 {{
      font-size: 0.82rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: #94a3b8;
      margin-bottom: 10px;
      font-weight: 600;
    }}
    .form-select, .form-control {{
      background-color: #1e293b;
      border: 1px solid #475569;
      color: #f1f5f9;
      font-size: 0.85rem;
    }}
    .form-select:focus, .form-control:focus {{
      background-color: #1e293b;
      border-color: #38bdf8;
      color: #ffffff;
      box-shadow: 0 0 0 0.2rem rgba(56, 189, 248, 0.25);
    }}
    .badge-pill {{
      padding: 4px 8px;
      border-radius: 12px;
      font-size: 0.72rem;
      font-weight: 600;
    }}
    #main-content {{
      flex: 1;
      display: flex;
      flex-direction: column;
      position: relative;
    }}
    #topbar {{
      height: 52px;
      background: #1e293b;
      border-bottom: 1px solid #334155;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 24px;
    }}
    #network-canvas {{
      flex: 1;
      height: calc(100vh - 52px);
      background: radial-gradient(circle at center, #1e293b 0%, #0f172a 100%);
    }}
    #details-panel {{
      position: absolute;
      top: 64px;
      right: 20px;
      width: 360px;
      max-height: calc(100vh - 90px);
      background: rgba(30, 41, 59, 0.95);
      backdrop-filter: blur(8px);
      border: 1px solid #475569;
      border-radius: 10px;
      padding: 18px;
      overflow-y: auto;
      box-shadow: 0 8px 30px rgba(0,0,0,0.6);
      display: none;
      z-index: 100;
    }}
    .legend-item {{
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 6px;
      font-size: 0.8rem;
    }}
    .legend-color {{
      width: 14px;
      height: 14px;
      border-radius: 50%;
    }}
    .btn-action {{
      font-size: 0.8rem;
      padding: 5px 10px;
    }}
    .prop-row {{
      display: flex;
      justify-content: space-between;
      padding: 4px 0;
      border-bottom: 1px solid #334155;
      font-size: 0.82rem;
    }}
    .prop-label {{
      color: #94a3b8;
    }}
    .prop-val {{
      color: #f8fafc;
      font-weight: 500;
      word-break: break-all;
      text-align: right;
    }}
  </style>
</head>
<body>
  <div id="app-container">
    <!-- SIDEBAR -->
    <div id="sidebar">
      <div id="sidebar-header">
        <h5><i class="fa-solid fa-diagram-project"></i> DataHub Knowledge Graph</h5>
        <div style="font-size: 0.75rem; color: #94a3b8; margin-top: 4px;">Powered by DataHub &amp; Apache AGE</div>
      </div>
      <div id="sidebar-controls">
        <!-- SEARCH -->
        <div class="control-section">
          <h6><i class="fa-solid fa-magnifying-glass"></i> Search Nodes</h6>
          <input type="text" id="search-input" class="form-control" placeholder="Search table, column, db...">
        </div>

        <!-- DATABASE FILTER -->
        <div class="control-section">
          <h6><i class="fa-solid fa-database"></i> Database Isolation</h6>
          <select id="db-select" class="form-select">
            <option value="ALL">All Databases (Complete Graph)</option>
          </select>
        </div>

        <!-- NODE TYPE FILTER -->
        <div class="control-section">
          <h6><i class="fa-solid fa-shapes"></i> Node Types</h6>
          <div class="form-check">
            <input class="form-check-input node-filter" type="checkbox" value="Database" id="chk-db" checked>
            <label class="form-check-label" for="chk-db">Database <span class="badge bg-purple badge-pill" style="background:#8b5cf6;" id="count-db">0</span></label>
          </div>
          <div class="form-check">
            <input class="form-check-input node-filter" type="checkbox" value="Schema" id="chk-schema" checked>
            <label class="form-check-label" for="chk-schema">Schema <span class="badge bg-info text-dark badge-pill" id="count-schema">0</span></label>
          </div>
          <div class="form-check">
            <input class="form-check-input node-filter" type="checkbox" value="Table" id="chk-table" checked>
            <label class="form-check-label" for="chk-table">Table / View <span class="badge bg-success badge-pill" id="count-table">0</span></label>
          </div>
          <div class="form-check">
            <input class="form-check-input node-filter" type="checkbox" value="Column" id="chk-col">
            <label class="form-check-label" for="chk-col">Columns (Detailed) <span class="badge bg-warning text-dark badge-pill" id="count-col">0</span></label>
          </div>
        </div>

        <!-- EDGE TYPE FILTER -->
        <div class="control-section">
          <h6><i class="fa-solid fa-route"></i> Edge Types</h6>
          <div class="form-check">
            <input class="form-check-input edge-filter" type="checkbox" value="CONTAINS" id="edge-contains" checked>
            <label class="form-check-label" for="edge-contains">CONTAINS (Hierarchy)</label>
          </div>
          <div class="form-check">
            <input class="form-check-input edge-filter" type="checkbox" value="REFERENCES" id="edge-references" checked>
            <label class="form-check-label" for="edge-references">REFERENCES (FK / Semantic)</label>
          </div>
          <div class="form-check">
            <input class="form-check-input edge-filter" type="checkbox" value="DERIVES_FROM" id="edge-derives" checked>
            <label class="form-check-label" for="edge-derives">DERIVES_FROM (Lineage)</label>
          </div>
          <div class="form-check">
            <input class="form-check-input edge-filter" type="checkbox" value="DEPENDS_ON" id="edge-depends" checked>
            <label class="form-check-label" for="edge-depends">DEPENDS_ON (Data Flow)</label>
          </div>
        </div>

        <!-- LAYOUT TOGGLE -->
        <div class="control-section">
          <h6><i class="fa-solid fa-sliders"></i> Layout Settings</h6>
          <div class="d-flex gap-2">
            <button id="btn-physics" class="btn btn-sm btn-outline-info flex-fill active">Force Directed</button>
            <button id="btn-hierarchical" class="btn btn-sm btn-outline-info flex-fill">Hierarchical</button>
          </div>
          <button id="btn-fit" class="btn btn-sm btn-outline-secondary w-100 mt-2"><i class="fa-solid fa-arrows-to-dot"></i> Fit to View</button>
        </div>

        <!-- LEGEND -->
        <div class="control-section">
          <h6><i class="fa-solid fa-palette"></i> Graph Legend</h6>
          <div class="legend-item"><div class="legend-color" style="background:#8b5cf6;"></div> Database</div>
          <div class="legend-item"><div class="legend-color" style="background:#0284c7;"></div> Schema</div>
          <div class="legend-item"><div class="legend-color" style="background:#10b981;"></div> Table / Model</div>
          <div class="legend-item"><div class="legend-color" style="background:#06b6d4;"></div> View</div>
          <div class="legend-item"><div class="legend-color" style="background:#f59e0b;"></div> Column (Primary Key)</div>
          <div class="legend-item"><div class="legend-color" style="background:#64748b;"></div> Column (Standard)</div>
        </div>
      </div>
    </div>

    <!-- MAIN CANVAS -->
    <div id="main-content">
      <div id="topbar">
        <div class="d-flex align-items-center gap-3">
          <span class="badge bg-primary" id="badge-total-nodes">0 Nodes</span>
          <span class="badge bg-success" id="badge-total-edges">0 Edges</span>
          <span class="badge bg-secondary" id="badge-db-active">Active DB: All</span>
        </div>
        <div>
          <button class="btn btn-sm btn-outline-light" onclick="exportGraphData()"><i class="fa-solid fa-download"></i> Export JSON</button>
        </div>
      </div>
      <div id="network-canvas"></div>

      <!-- DETAILS FLYOUT -->
      <div id="details-panel">
        <div class="d-flex justify-content-between align-items-center mb-3">
          <h6 class="m-0" id="detail-title" style="color: #38bdf8;">Node Details</h6>
          <button class="btn btn-sm btn-outline-secondary" onclick="closeDetails()">&times;</button>
        </div>
        <div id="detail-body"></div>
      </div>
    </div>
  </div>

  <script>
    const RAW_NODES = {nodes_json};
    const RAW_EDGES = {edges_json};
    const STATS = {stats_json};

    let network = null;
    let visNodes = new vis.DataSet([]);
    let visEdges = new vis.DataSet([]);

    // Initialize counts
    document.getElementById("count-db").innerText = STATS.node_counts.Database || 0;
    document.getElementById("count-schema").innerText = STATS.node_counts.Schema || 0;
    document.getElementById("count-table").innerText = STATS.node_counts.Table || 0;
    document.getElementById("count-col").innerText = STATS.node_counts.Column || 0;

    // Populate database dropdown
    const dbSelect = document.getElementById("db-select");
    const uniqueDbs = [...new Set(RAW_NODES.filter(n => n.label === "Table").map(n => n.platform + "." + n.database))];
    uniqueDbs.forEach(db => {{
      const opt = document.createElement("option");
      opt.value = db;
      opt.innerText = db;
      dbSelect.appendChild(opt);
    }});

    // Helper: format node color and icon
    function getNodeVisual(n) {{
      if (n.label === "Database") {{
        return {{ color: "#8b5cf6", shape: "box", size: 30, font: {{ color: "#ffffff", size: 16, bold: true }} }};
      }} else if (n.label === "Schema") {{
        return {{ color: "#0284c7", shape: "ellipse", size: 22, font: {{ color: "#ffffff", size: 14 }} }};
      }} else if (n.label === "Table") {{
        const isView = (n.subtype || "").toLowerCase() === "view";
        return {{
          color: isView ? "#06b6d4" : "#10b981",
          shape: isView ? "box" : "box",
          size: 25,
          font: {{ color: "#ffffff", size: 14, bold: true }}
        }};
      }} else if (n.label === "Column") {{
        return {{
          color: n.is_pk ? "#f59e0b" : "#64748b",
          shape: n.is_pk ? "star" : "dot",
          size: n.is_pk ? 14 : 10,
          font: {{ color: "#e2e8f0", size: 11 }}
        }};
      }}
      return {{ color: "#94a3b8", shape: "dot", size: 15 }};
    }}

    // Helper: format edge styling
    function getEdgeVisual(e) {{
      const isRef = e.label === "REFERENCES";
      const isDerives = e.label === "DERIVES_FROM";
      const isDepends = e.label === "DEPENDS_ON";

      let color = "#475569";
      let width = 1.2;
      let dashes = false;
      let label = "";

      if (isRef) {{
        color = "#22c55e";
        width = 2.4;
        const p = e.properties || {{}};
        label = p.from_column ? (p.from_column + " \u2192 " + p.to_column) : "REFERENCES";
      }} else if (isDerives) {{
        color = "#f97316";
        width = 2.4;
        label = "DERIVES_FROM";
      }} else if (isDepends) {{
        color = "#ef4444";
        width = 1.5;
        dashes = [5, 5];
        label = "DEPENDS_ON";
      }}

      return {{
        color: {{ color: color, highlight: "#38bdf8" }},
        width: width,
        dashes: dashes,
        label: label,
        font: {{ size: 9, color: color, strokeWidth: 2, strokeColor: "#0f172a", align: "middle" }},
        arrows: {{ to: {{ enabled: true, scaleFactor: 0.8 }} }}
      }};
    }}

    function filterAndRender() {{
      const selectedDb = dbSelect.getElementById ? "ALL" : dbSelect.value;
      const activeNodeTypes = Array.from(document.querySelectorAll(".node-filter:checked")).map(el => el.value);
      const activeEdgeTypes = Array.from(document.querySelectorAll(".edge-filter:checked")).map(el => el.value);
      const searchVal = document.getElementById("search-input").value.trim().toLowerCase();

      // Filter nodes
      const filteredNodes = RAW_NODES.filter(n => {{
        if (!activeNodeTypes.includes(n.label)) return false;
        if (selectedDb !== "ALL") {{
          if (n.label === "Database" && (n.platform + "." + n.name) !== selectedDb) return false;
          if (n.label === "Schema" && (n.platform + "." + n.database) !== selectedDb) return false;
          if (n.label === "Table" && (n.platform + "." + n.database) !== selectedDb) return false;
          if (n.label === "Column") {{
            // check parent table db
            const parentTbl = RAW_NODES.find(t => t.urn === n.table_urn);
            if (parentTbl && (parentTbl.platform + "." + parentTbl.database) !== selectedDb) return false;
          }}
        }}
        if (searchVal) {{
          const nameMatch = (n.name || "").toLowerCase().includes(searchVal);
          const descMatch = (n.description || "").toLowerCase().includes(searchVal);
          if (!nameMatch && !descMatch) return false;
        }}
        return true;
      }});

      const nodeIds = new Set(filteredNodes.map(n => n.id));

      // Filter edges
      const filteredEdges = RAW_EDGES.filter(e => {{
        if (!activeEdgeTypes.includes(e.label)) return false;
        if (!nodeIds.has(e.from) || !nodeIds.has(e.to)) return false;
        return true;
      }});

      // Update vis datasets
      const vNodes = filteredNodes.map(n => {{
        const visStyle = getNodeVisual(n);
        let title = `<b>${{n.label}}:</b> ${{n.name}}<br>`;
        if (n.database) title += `<b>Database:</b> ${{n.database}}<br>`;
        if (n.subtype) title += `<b>Type:</b> ${{n.subtype}}<br>`;
        if (n.type) title += `<b>DataType:</b> ${{n.type}}<br>`;
        if (n.is_pk) title += `<b>Primary Key:</b> Yes<br>`;
        if (n.description) title += `<b>Description:</b> ${{n.description}}<br>`;

        return {{
          id: n.id,
          label: n.name,
          title: title,
          raw: n,
          ...visStyle
        }};
      }});

      const vEdges = filteredEdges.map(e => {{
        const visStyle = getEdgeVisual(e);
        return {{
          id: e.id,
          from: e.from,
          to: e.to,
          raw: e,
          ...visStyle
        }};
      }});

      visNodes.clear();
      visEdges.clear();
      visNodes.add(vNodes);
      visEdges.add(vEdges);

      document.getElementById("badge-total-nodes").innerText = `${{vNodes.length}} Nodes`;
      document.getElementById("badge-total-edges").innerText = `${{vEdges.length}} Edges`;
      document.getElementById("badge-db-active").innerText = `Active DB: ${{selectedDb}}`;
    }}

    function initNetwork(hierarchical = false) {{
      const container = document.getElementById("network-canvas");
      const data = {{ nodes: visNodes, edges: visEdges }};
      const options = {{
        physics: {{
          enabled: !hierarchical,
          solver: "forceAtlas2Based",
          forceAtlas2Based: {{
            gravitationalConstant: -70,
            centralGravity: 0.008,
            springLength: 120,
            springConstant: 0.08
          }},
          stabilization: {{ iterations: 120 }}
        }},
        layout: {{
          hierarchical: {{
            enabled: hierarchical,
            direction: "UD",
            sortMethod: "directed",
            levelSeparation: 140,
            nodeSpacing: 160
          }}
        }},
        interaction: {{
          hover: true,
          tooltipDelay: 100,
          zoomView: true,
          dragView: true
        }}
      }};

      network = new vis.Network(container, data, options);

      network.on("click", function(params) {{
        if (params.nodes.length > 0) {{
          const clickedId = params.nodes[0];
          const nodeObj = visNodes.get(clickedId);
          if (nodeObj) showNodeDetails(nodeObj.raw);
        }} else if (params.edges.length > 0) {{
          const clickedEdgeId = params.edges[0];
          const edgeObj = visEdges.get(clickedEdgeId);
          if (edgeObj) showEdgeDetails(edgeObj.raw);
        }} else {{
          closeDetails();
        }}
      }});
    }}

    function showNodeDetails(n) {{
      const panel = document.getElementById("details-panel");
      const title = document.getElementById("detail-title");
      const body = document.getElementById("detail-body");

      title.innerHTML = `<i class="fa-solid fa-circle-info"></i> ${{n.label}}: ${{n.name}}`;
      let html = "";

      for (const [k, v] of Object.entries(n)) {{
        if (k === "raw" || v === null || v === "") continue;
        const valStr = (typeof v === "object") ? JSON.stringify(v) : String(v);
        html += `<div class="prop-row"><span class="prop-label">${{k}}</span><span class="prop-val">${{valStr}}</span></div>`;
      }}

      // Find incoming and outgoing edges
      const incoming = RAW_EDGES.filter(e => e.to === n.id);
      const outgoing = RAW_EDGES.filter(e => e.from === n.id);

      if (outgoing.length > 0) {{
        html += `<h6 class="mt-3 mb-2" style="font-size:0.8rem; color:#38bdf8;">Outgoing Edges (${{outgoing.length}})</h6>`;
        outgoing.forEach(e => {{
          const targetName = e.to.split(":").pop();
          html += `<div style="font-size:0.75rem; color:#cbd5e1; margin-bottom:3px;">
            <span class="badge bg-secondary">${{e.label}}</span> \u2192 ${{targetName}}
          </div>`;
        }});
      }}

      if (incoming.length > 0) {{
        html += `<h6 class="mt-3 mb-2" style="font-size:0.8rem; color:#38bdf8;">Incoming Edges (${{incoming.length}})</h6>`;
        incoming.forEach(e => {{
          const srcName = e.from.split(":").pop();
          html += `<div style="font-size:0.75rem; color:#cbd5e1; margin-bottom:3px;">
            ${{srcName}} \u2192 <span class="badge bg-secondary">${{e.label}}</span>
          </div>`;
        }});
      }}

      body.innerHTML = html;
      panel.style.display = "block";
    }}

    function showEdgeDetails(e) {{
      const panel = document.getElementById("details-panel");
      const title = document.getElementById("detail-title");
      const body = document.getElementById("detail-body");

      title.innerHTML = `<i class="fa-solid fa-link"></i> Edge: ${{e.label}}`;
      let html = `
        <div class="prop-row"><span class="prop-label">Type</span><span class="prop-val">${{e.label}}</span></div>
        <div class="prop-row"><span class="prop-label">From</span><span class="prop-val">${{e.from}}</span></div>
        <div class="prop-row"><span class="prop-label">To</span><span class="prop-val">${{e.to}}</span></div>
      `;

      if (e.properties) {{
        for (const [k, v] of Object.entries(e.properties)) {{
          html += `<div class="prop-row"><span class="prop-label">${{k}}</span><span class="prop-val">${{v}}</span></div>`;
        }}
      }}

      body.innerHTML = html;
      panel.style.display = "block";
    }}

    function closeDetails() {{
      document.getElementById("details-panel").style.display = "none";
    }}

    function exportGraphData() {{
      const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify({{ nodes: RAW_NODES, edges: RAW_EDGES, stats: STATS }}, null, 2));
      const downloadAnchor = document.createElement("a");
      downloadAnchor.setAttribute("href", dataStr);
      downloadAnchor.setAttribute("download", "datahub_knowledge_graph.json");
      document.body.appendChild(downloadAnchor);
      downloadAnchor.click();
      downloadAnchor.remove();
    }}

    // Event listeners
    document.querySelectorAll(".node-filter, .edge-filter").forEach(el => {{
      el.addEventListener("change", filterAndRender);
    }});
    dbSelect.addEventListener("change", filterAndRender);
    document.getElementById("search-input").addEventListener("input", filterAndRender);

    document.getElementById("btn-physics").addEventListener("click", function() {{
      this.classList.add("active");
      document.getElementById("btn-hierarchical").classList.remove("active");
      initNetwork(false);
      filterAndRender();
    }});

    document.getElementById("btn-hierarchical").addEventListener("click", function() {{
      this.classList.add("active");
      document.getElementById("btn-physics").classList.remove("active");
      initNetwork(true);
      filterAndRender();
    }});

    document.getElementById("btn-fit").addEventListener("click", function() {{
      if (network) network.fit({{ animation: true }});
    }});

    // Boot
    initNetwork(false);
    filterAndRender();
  </script>
</body>
</html>
"""
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        logger.info("Generated interactive Knowledge Graph HTML at: %s", output_path)


# =============================================================================
# 5. CLI REPORTER & FORMATTED OUTPUT
# =============================================================================

class GraphReporter:
    """Prints formatted hierarchical summaries and relationship matrices."""

    @staticmethod
    def print_tree(graph_data: Dict[str, Any]):
        """Prints an ASCII hierarchy tree of all databases, schemas, tables, and relationships."""
        print("\n" + "=" * 80)
        print("          DATAHUB ENTERPRISE KNOWLEDGE GRAPH HIERARCHY")
        print("=" * 80)

        tables_by_schema = defaultdict(list)
        for t in graph_data["tables"]:
            key = f"{t['platform']}.{t['database']}.{t['schema']}"
            tables_by_schema[key].append(t)

        schemas_by_db = defaultdict(set)
        for s in graph_data["schemas"]:
            db_key = f"{s['platform']}.{s['database']}"
            schemas_by_db[db_key].add(s["name"])

        # Map relationships for quick lookup
        table_refs = defaultdict(list)
        table_lineages = defaultdict(list)
        for e in graph_data["edges"]:
            if e["label"] == "REFERENCES" and e["from_label"] == "Table":
                table_refs[e["from"]].append(e)
            elif e["label"] == "DERIVES_FROM" and e["from_label"] == "Table":
                table_lineages[e["from"]].append(e)

        try:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

        for db in graph_data["databases"]:
            db_key = f"{db['platform']}.{db['name']}"
            print(f"\n[DATABASE] [{db['platform'].upper()}] {db['name']} (tables: {db['table_count']})")

            schemas = sorted(schemas_by_db.get(db_key, ["public"]))
            for schema in schemas:
                print(f"  +-- [SCHEMA] {schema}")
                schema_key = f"{db['platform']}.{db['name']}.{schema}"
                tables = tables_by_schema.get(schema_key, [])

                for i, t in enumerate(tables):
                    is_last_tbl = (i == len(tables) - 1)
                    prefix = "       \\--" if is_last_tbl else "       +--"
                    col_count = t["column_count"]
                    subtype = t["subtype"]
                    print(f"{prefix} [TABLE] {t['name']} [{subtype}] ({col_count} columns)")

                    # Print columns preview (highlighting PKs)
                    col_nodes = [c for c in graph_data["columns"] if c["table_urn"] == t["urn"]]
                    pks = [c["name"] for c in col_nodes if c["is_pk"]]
                    if pks:
                        print(f"       |    [PK] Primary Key: {pks}")

                    # Print lineage dependencies
                    t_node_id = t["id"]
                    if t_node_id in table_lineages:
                        for l_edge in table_lineages[t_node_id]:
                            target_tbl = l_edge["to"].split(":")[-1].split(",")[-2]
                            l_type = l_edge.get("properties", {}).get("lineage_type", "TRANSFORMED")
                            print(f"       |    --> LINEAGE: DERIVES_FROM -> {target_tbl} ({l_type})")

                    # Print foreign key references
                    if t_node_id in table_refs:
                        for r_edge in table_refs[t_node_id]:
                            target_tbl = r_edge["to"].split(":")[-1].split(",")[-2]
                            props = r_edge.get("properties", {})
                            from_c = props.get("from_column", "")
                            to_c = props.get("to_column", "")
                            conf = props.get("confidence", 1.0)
                            rule = props.get("match_rule", "fk_match")
                            print(f"       |    ==> REFERENCE: {from_c} -> {target_tbl}.{to_c} [conf: {conf:.2f}, rule: {rule}]")

        print("\n" + "=" * 80)
        print("                   KNOWLEDGE GRAPH METRICS & STATISTICS")
        print("=" * 80)
        stats = graph_data["stats"]
        print(f"  Total Vertices Loaded : {stats['total_nodes']}")
        for lbl, cnt in stats["node_counts"].items():
            print(f"    - {lbl:<12} : {cnt}")
        print(f"\n  Total Edges Created   : {stats['total_edges']}")
        for lbl, cnt in stats["edge_counts"].items():
            print(f"    - {lbl:<12} : {cnt}")
        print(f"\n  Relationship Breakdown:")
        print(f"    - Explicit Edges    : {stats['explicit_edges']} (Lineage & Structural Hierarchy)")
        print(f"    - Inferred Edges    : {stats['inferred_edges']} (Foreign Key & Semantic References)")
        print("=" * 80 + "\n")


# =============================================================================
# 6. MAIN EXECUTION PIPELINE
# =============================================================================

def build_knowledge_graph(
    skip_age_load: bool = False,
    output_dir: str = "C:/Users/varshini/age-viewer"
) -> Dict[str, Any]:
    """Execute end-to-end metadata extraction, graph construction, AGE loading, and visualization."""
    os.makedirs(output_dir, exist_ok=True)
    json_path = os.path.join(output_dir, "datahub_knowledge_graph.json")
    html_path = os.path.join(output_dir, "datahub_knowledge_graph.html")

    # Step 1: Extract metadata from DataHub
    logger.info("=== STEP 1: EXTRACTING METADATA FROM DATAHUB ===")
    extractor = DataHubMetadataExtractor()
    catalog = extractor.extract_catalog()
    if not catalog:
        logger.error("No dataset metadata could be extracted from DataHub. Aborting.")
        return {}

    # Step 2: Build Knowledge Graph model
    logger.info("=== STEP 2: GROUPING & INFERRING RELATIONSHIPS ===")
    engine = KnowledgeGraphEngine(catalog)
    graph_data = engine.build()

    # Step 3: Save JSON output
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(graph_data, f, indent=2)
    logger.info("Saved graph structure to: %s", json_path)

    # Step 4: Generate Interactive Visualization
    logger.info("=== STEP 3: GENERATING INTERACTIVE VISUALIZATION ===")
    KnowledgeGraphVisualizer.generate_html(graph_data, html_path)

    # Step 5: Load into Apache AGE (PostgreSQL)
    if not skip_age_load:
        logger.info("=== STEP 4: LOADING GRAPH INTO APACHE AGE (PORT %d) ===", POSTGRES_PORT)
        age_loader = ApacheAGELoader(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            dbname=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            graph_name=GRAPH_NAME
        )
        try:
            age_loader.connect()
            age_loader.reset_graph()
            age_loader.load_graph(graph_data)
            verification = age_loader.verify_graph()
            graph_data["verification"] = verification
        except Exception as e:
            logger.error("Failed to load into Apache AGE: %s", e)
            raise
        finally:
            age_loader.close()
    else:
        logger.info("Skipping Apache AGE load as requested.")

    # Step 6: Print human-readable report
    GraphReporter.print_tree(graph_data)

    logger.info("Knowledge Graph pipeline completed successfully!")
    return graph_data


if __name__ == "__main__":
    skip_age = "--no-age" in sys.argv
    build_knowledge_graph(skip_age_load=skip_age)
