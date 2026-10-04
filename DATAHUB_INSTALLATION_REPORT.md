# DataHub Local Installation & Architecture Report

## 1. Executive Summary
DataHub Core (v1.7.0.1) was successfully deployed on Windows 11 using Docker Compose. The deployment runs in a containerized topology with isolated services for metadata persistence, search indexing, streaming logs, and the web user interface.

This deployment method bypassed a critical Python 3.14 dependency conflict (`PyO3`/`pydantic-core`) by running the platform purely on Docker, leaving the host operating system and system Python environment clean and unmodified.

---

## 2. Environment & System Specifications

| Component | Host / Runtime Specification |
| :--- | :--- |
| **Operating System** | Windows 11 Pro / Enterprise x86_64 |
| **Docker Engine** | 29.6.2 (API: 1.55, Context: `desktop-linux`) |
| **Docker Compose** | v5.3.1 |
| **Docker Resources** | 8.0 GB RAM, 16 vCPUs |
| **Host Python** | Python 3.14.6 (Default) & Python 3.13 (Available via `py -3.13`) |
| **Working Directory** | `C:\Users\varshini\datahub` |
| **DataHub URL** | [http://localhost:9002](http://localhost:9002) |
| **Default Credentials** | `datahub` / `datahub` |

---

## 3. What Was Installed & Configured

1. **Docker Compose Configuration (`docker-compose.yml`)**:
   * Derived from the official DataHub Quickstart Profile specification.
   * Defines 7 services categorized into storage, event backbone, metadata service, and frontend.
   * Configured host port isolation to resolve local Windows port collisions.

2. **Environment Variable Configuration (`.env`)**:
   * `DATAHUB_VERSION=v1.7.0.1`: Anchors image tags across all microservices.
   * `DATAHUB_MAPPED_MYSQL_PORT=3307`: Remaps the host MySQL port to 3307 to prevent conflict with the host's existing `mysqld` service (PID 6708 listening on 3306).
   * `HOME=C:/Users/varshini`: Corrects path translation for Docker volume mounts on Windows.
   * `DATAHUB_TOKEN_SERVICE_SIGNING_KEY` & `DATAHUB_TOKEN_SERVICE_SALT`: High-entropy 32-byte cryptographic keys for signing and validating session access tokens.

3. **Persistent Host Directories**:
   * `C:\Users\varshini\.datahub\plugins` (Plugin storage mount)
   * `C:\Users\varshini\.datahub\search` (Local search indices mount)

---

## 4. Docker Containers & Microservices Breakdown

| Service Name | Docker Container | Image Tag | Host Port | Role & Architecture |
| :--- | :--- | :--- | :--- | :--- |
| **Frontend** | `datahub-frontend-quickstart-1` | `acryldata/datahub-frontend-react:v1.7.0.1` | `9002 -> 9002` | React Single Page Application (SPA) providing the web UI and user auth session management. |
| **GMS Backend** | `datahub-datahub-gms-quickstart-1` | `acryldata/datahub-gms:v1.7.0.1` | `8080 -> 8080`, `4319 -> 4319` | Generalized Metadata Service. The central REST and GraphQL API engine processing metadata reads and writes. |
| **Search Engine** | `datahub-opensearch-1` | `opensearchproject/opensearch:2.19.3` | `9200 -> 9200` | OpenSearch document store indexing entities, schema fields, tags, and terms for full-text search and filtering. |
| **Relational DB** | `datahub-mysql-1` | `mysql:8.2` | `3307 -> 3306` | Relational store maintaining entity aspects (versioned JSON state) using EBean ORM. |
| **Event Stream** | `datahub-kafka-broker-1` | `confluentinc/cp-kafka:8.2.2` | `9092 -> 9092` | Apache Kafka running in KRaft mode (no ZooKeeper required) managing MCL (Metadata Change Log) and MCP (Metadata Change Proposal) topics. |
| **Actions Framework** | `datahub-datahub-actions-quickstart-1` | `acryldata/datahub-actions:v1.7.0.1-slim` | *Internal* | Event-driven framework executing workflows, alerts, and automated propagation based on Kafka metadata events. |
| **Schema Migration** | `datahub-system-update-quickstart-1` | `acryldata/datahub-upgrade:v1.7.0.1` | *Completed (Exited)* | Bootstrapping job that runs on startup to verify/migrate MySQL schemas and OpenSearch index mappings. |

---

## 5. Current Metadata Inventory
* **Status**: Clean / Fresh Installation.
* **Entities**:
  * Datasets: 0
  * Dashboards & Charts: 0
  * Data Pipelines: 0
  * Domains & Glossary Terms: 0
* **Storage Model**: In DataHub, every asset is identified by a unique **URN** (Uniform Resource Name, e.g. `urn:li:dataset:(urn:li:dataPlatform:postgres,my_db.users,PROD)`) composed of individual, versioned **Aspects** (SchemaMetadata, Ownership, GlobalTags, UpstreamLineage).

---

## 6. How dbt Integration Works

DataHub provides deep, bidirectional integration with **dbt Core** and **dbt Cloud**:

```
[dbt compile / run] 
        │
        ▼
Generates JSON Artifacts:
  - manifest.json (models, sources, column descriptions, tests)
  - catalog.json (inferred types, table statistics)
  - run_results.json (status, execution times)
        │
        ▼
[DataHub dbt Ingestion Source]
        │
        ├── Extracts Column Schemas & YAML descriptions
        ├── Builds DAG lineage (Sources ➔ Staging ➔ Marts)
        ├── Attaches dbt Tests as Data Quality assertions
        └── Extracts Owners & Tags from YAML config
        │
        ▼
Pushes Metadata Change Proposals (MCPs) to GMS (port 8080)
```

### Ingestion Execution Methods for dbt:
1. **Web UI Managed Ingestion (Zero-Install)**:
   * Go to **DataHub UI ➔ Data Sources ➔ Create Source ➔ dbt**.
   * Upload the `manifest.json` and `catalog.json` directly or point to an S3/GCS bucket or Git repository.
2. **Containerized Ingestion (Zero Python dependencies on host)**:
   ```powershell
   docker run --rm --net=datahub_network `
     -v "C:\path\to\dbt\target:/data" `
     acryldata/datahub-ingestion ingest -c /data/dbt_recipe.dhub.yaml
   ```
3. **CLI Ingestion via Isolated Python 3.13 venv**:
   * Running `datahub ingest -c recipe.dhub.yaml` within a clean `py -3.13 -m venv .venv`.

---

## 7. How SQL / Database Metadata Ingestion Works

DataHub ingests metadata from relational engines (PostgreSQL, MySQL, Snowflake, BigQuery, SQL Server, Oracle, Redshift) via declarative recipes:

```
[SQL Database]
  ├─ information_schema.tables / columns
  ├─ pg_catalog / sys.objects (Primary/Foreign Keys)
  └─ Query History / Audit Logs (for column-level lineage)
        │
        ▼
[DataHub SQL Source Plugin]
        │
        ├── Converts relational columns into SchemaMetadata aspects
        ├── Parses SQL queries into table and column lineage
        └── Ingests table row counts and column profiles (if profiling is enabled)
        │
        ▼
[Sink: DataHub REST (http://localhost:8080)]
```

### Typical SQL Ingestion Recipe (`mysql_recipe.dhub.yaml`):
```yaml
source:
  type: mysql
  config:
    host_port: "localhost:3306"
    database: "analytics_db"
    username: "readonly_user"
    password: "${DB_PASSWORD}"
    profiling:
      enabled: false

sink:
  type: datahub-rest
  config:
    server: "http://localhost:8080"
```

---

## 8. Observations, Root Causes & Limitations

1. **Host Python 3.14 Incompatibility**:
   * **Root Cause**: Python 3.14 is currently pre-release/bleeding-edge. The underlying C/Rust compilation bindings (`PyO3` within `pydantic-core`) enforce strict upper bounds on Python versions (`PyO3 < 3.14`).
   * **Resolution**: Bypassing host pip installation and utilizing Docker containerization prevents environment corruption and rust compilation failures.

2. **Port 3306 Conflict**:
   * **Root Cause**: Host system was already running a native `mysqld` service on port 3306.
   * **Resolution**: Remapped container published port to `3307`. Inter-container communication within Docker uses the virtual network `datahub_network` where MySQL remains accessible at `mysql:3306`, completely isolating it from the host.

3. **Hardware & Resource Demands**:
   * Running Kafka, OpenSearch, and GMS simultaneously requires roughly 4–6 GB of active RAM. Allocating 8 GB in Docker Desktop ensures stability during burst indexing operations.
