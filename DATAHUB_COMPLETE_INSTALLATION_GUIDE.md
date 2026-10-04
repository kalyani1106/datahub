# Complete End-to-End Installation & Setup Guide for DataHub on Windows 11

## 1. Environment & System Overview

* **Operating System**: Windows 11 x86_64
* **Working Directory**: `C:\Users\varshini\datahub`
* **Docker Engine**: `29.6.2` (API `1.55`)
* **Docker Compose**: `v5.3.1`
* **Allocated Resources**: 8 GB RAM, 16 vCPUs (WSL2 Backend)
* **Host Python**: Python 3.14.6 (Default) & Python 3.13 (`py -3.13`)
* **Database Service**: PostgreSQL 18.4 (Native Windows Service on port `5432`)
* **DataHub Platform Version**: **`v1.7.0.1`**
* **DataHub Web UI URL**: [http://localhost:9002](http://localhost:9002)
* **DataHub GMS REST API URL**: [http://localhost:8080](http://localhost:8080)
* **Default Login Credentials**: `username: datahub` | `password: datahub`

---

## 2. Root Cause Analysis: Why `pip install acryl-datahub` Failed

When attempting to install the DataHub CLI on Python 3.14 using:
```bash
python -m pip install --upgrade acryl-datahub
```
The installation failed during the compilation of `pydantic-core` with the error:
> *"the configured Python interpreter version (3.14) is newer than PyO3's maximum supported version (3.13)"*

### Technical Cause:
1. `pydantic-core` (a foundational dependency of DataHub) is written in Rust and uses `PyO3` bindings.
2. `PyO3` contains an intentional compile-time check enforcing a strict upper bound on supported Python versions (currently capped at Python 3.13).
3. Python 3.14 does not have pre-compiled binary wheels on PyPI, and compilation from source is blocked by `PyO3`.

### Solution Architecture:
Instead of forcing host Python changes or recompilation, we use DataHub's official **Docker-based deployment architecture**. DataHub runs as a cluster of pre-compiled Docker images, completely isolating the platform from the host Python interpreter and leaving your system Python 3.14 untouched.

---

## 3. Pre-Installation: System & Environment Checks

### Command 1: Verify Docker Engine
```powershell
docker version
```
* **Purpose**: Confirms that Docker Desktop is installed, running, and accessible from the command line.

### Command 2: Verify Docker Compose
```powershell
docker compose version
```
* **Purpose**: Verifies that Docker Compose v2+ is installed as a Docker plugin.

### Command 3: Create Local Mount Directories
```powershell
New-Item -ItemType Directory -Force -Path "$HOME\.datahub\plugins", "$HOME\.datahub\search"
```
* **Purpose**: Creates the local directories on Windows (`C:\Users\varshini\.datahub\plugins` and `search`) needed by DataHub's bind mounts for plugins and local search cache.

---

## 4. Setting Up Configuration Files

In your project directory (`C:\Users\varshini\datahub`), two configuration files were established:

### File 1: Download Official Docker Compose Profile (`docker-compose.yml`)
```powershell
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/datahub-project/datahub/master/docker/quickstart/docker-compose.quickstart-profile.yml" -OutFile "docker-compose.yml"
```
* **Purpose**: Fetches the official multi-service quickstart Docker Compose definition directly from DataHub's GitHub repository.

### File 2: Create Environment Variables (`.env`)
Create a file named `.env` in `C:\Users\varshini\datahub\.env` with the following configuration:
```env
DATAHUB_VERSION=v1.7.0.1
HOME=C:/Users/varshini
DATAHUB_SYSTEM_CLIENT_SECRET=JohnSnowKnowsNothing
DATAHUB_TOKEN_SERVICE_SIGNING_KEY=zDrkA4KMvXIwPSKiRX/dx0Rvsrm1qhKeEWJWHQZCZPk=
DATAHUB_TOKEN_SERVICE_SALT=jp3FsV7heXBIjS1Ny0YPdC593E+/ywnpdhOajcQTN5w=
UI_INGESTION_DEFAULT_CLI_VERSION=1.7.0.9
DATAHUB_MAPPED_MYSQL_PORT=3307
```

* **Variable Breakdown**:
  * `DATAHUB_VERSION`: Sets the container image tag for GMS, Frontend, Upgrade, and Actions.
  * `HOME`: Corrects Windows forward-slash path resolution for Docker volume mounts.
  * `DATAHUB_MAPPED_MYSQL_PORT=3307`: Prevents host port collisions (see section 5).
  * `UI_INGESTION_DEFAULT_CLI_VERSION=1.7.0.9`: Points UI-based Ingestion to a valid, existing PyPI release of `acryl-datahub` (without the `v` prefix).
  * `DATAHUB_TOKEN_SERVICE_SIGNING_KEY` / `SALT`: 32-byte cryptographic base64 tokens required by DataHub GMS for secure session token signing.

---

## 5. Port Conflict Diagnosis & Resolution

### The Error Encountered on First Launch:
```
Error response from daemon: ports are not available: exposing port TCP 0.0.0.0:3306 -> 127.0.0.1:0: 
listen tcp 0.0.0.0:3306: bind: Only one usage of each socket address (protocol/network address/port) is normally permitted.
```

### Diagnosis:
Checking the local listening ports revealed that a local MySQL service (`mysqld`, PID `6708`) was already running natively on Windows port `3306`:
```powershell
Get-NetTCPConnection -LocalPort 3306 | Select-Object LocalAddress, LocalPort, OwningProcess, State
Get-Process -Id 6708
```

### The Resolution:
DataHub's internal microservices communicate over Docker's internal virtual network (`datahub_network`) using `mysql:3306`. The host port mapping is only used for external host access.
In `docker-compose.yml`, the MySQL port mapping was updated from `3306:3306` to:
```yaml
    ports:
    - mode: ingress
      target: 3306
      published: ${DATAHUB_MAPPED_MYSQL_PORT:-3307}
      protocol: tcp
```
This maps DataHub's MySQL container to host port **`3307`**, leaving your native Windows MySQL completely undisturbed.

---

## 6. Starting and Verifying DataHub

### Command 4: Launch DataHub Cluster
```cmd
docker compose --profile quickstart up -d
```
* **Purpose**: Instructs Docker Compose to download all container images and launch the 7 DataHub services in detached (background) mode.

### Command 5: Verify Running Containers
```cmd
docker compose --profile quickstart ps
```

### Expected Output:
```
NAME                                   IMAGE                                       STATUS                    PORTS
datahub-datahub-actions-quickstart-1   acryldata/datahub-actions:v1.7.0.1-slim     Up                        
datahub-datahub-gms-quickstart-1       acryldata/datahub-gms:v1.7.0.1              Up (healthy)              0.0.0.0:8080->8080/tcp, 0.0.0.0:4319->4319/tcp
datahub-frontend-quickstart-1          acryldata/datahub-frontend-react:v1.7.0.1   Up (healthy)              0.0.0.0:9002->9002/tcp
datahub-kafka-broker-1                 confluentinc/cp-kafka:8.2.2                 Up (healthy)              0.0.0.0:9092->9092/tcp
datahub-mysql-1                        mysql:8.2                                   Up (healthy)              0.0.0.0:3307->3306/tcp
datahub-opensearch-1                   opensearchproject/opensearch:2.19.3         Up (healthy)              0.0.0.0:9200->9200/tcp
```

### Container Architecture & Roles:
1. **`datahub-frontend-react` (Port 9002)**: Web interface built on React.
2. **`datahub-gms` (Port 8080)**: Generalized Metadata Service — core REST and GraphQL API engine.
3. **`opensearch` (Port 9200)**: Document indexing engine for full-text search, schema indexing, and filtering.
4. **`mysql` (Port 3307 $\rightarrow$ 3306)**: Relational store preserving versioned entity aspects using EBean ORM.
5. **`kafka-broker` (Port 9092)**: Confluent Kafka in KRaft mode managing metadata change streams (`MCP` and `MCL`).
6. **`datahub-actions`**: Background worker for event-driven workflows, automations, and UI ingestion executions.
7. **`datahub-upgrade`**: Migration bootstrap job that runs once on startup to initialize schemas and indices, then exits (`Exited 0`).

---

## 7. Demo Database Setup (PostgreSQL)

To test DataHub ingestion with a realistic business dataset, we utilized the local native PostgreSQL 18.4 server.

### Command 6: Test Native PostgreSQL Connection
```cmd
"C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -p 5432 -c "\l"
```
* **Purpose**: Verifies that native PostgreSQL is accessible and lists existing databases.

### Command 7: Create Isolated Demo Database
```cmd
"C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -p 5432 -c "CREATE DATABASE ecommerce_db;"
```
* **Purpose**: Creates an isolated database named `ecommerce_db` so existing databases (`dbt_demo`, `dremio_demo`, etc.) remain untouched.

### Command 8: Create Tables and Populate Sample Data
Save the schema and insert statements in `init_ecommerce.sql`, then execute:
```cmd
"C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -p 5432 -d ecommerce_db -f "C:\Users\varshini\datahub\init_ecommerce.sql"
```

#### Schema Defined:
* `customers`: `customer_id` (PK), `first_name`, `last_name`, `email`, `city`, `created_at`
* `products`: `product_id` (PK), `product_name`, `category`, `price`, `stock_quantity`
* `orders`: `order_id` (PK), `customer_id` (FK $\rightarrow$ `customers`), `order_date`, `status`, `total_amount`
* `order_items`: `order_item_id` (PK), `order_id` (FK $\rightarrow$ `orders`), `product_id` (FK $\rightarrow$ `products`), `quantity`, `unit_price`
* `payments`: `payment_id` (PK), `order_id` (FK $\rightarrow$ `orders`), `payment_method`, `payment_status`, `amount`, `payment_date`

### Command 9: Run Demonstration Analytical Queries
Save test queries in `sample_queries.sql`, then execute:
```cmd
"C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -p 5432 -d ecommerce_db -f "C:\Users\varshini\datahub\sample_queries.sql"
```
* **Executed Queries**:
  1. Filtered `JOIN` of `customers` and `orders` where `total_amount > 100`.
  2. Multi-table `JOIN` with `COUNT()`, `SUM()`, and `GROUP BY` computing customer lifetime spend.
  3. 4-Table `JOIN` (`customers` $\rightarrow$ `orders` $\rightarrow$ `order_items` $\rightarrow$ `products`) calculating basket itemization.
  4. 1-to-1 payment reconciliation `JOIN` (`orders` $\rightarrow$ `payments`).

### Command 10: Create SQL Views for Query Logic & Lineage
To store SQL query definitions and lineage inside DataHub, execute `create_views.sql`:
```cmd
"C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -p 5432 -d ecommerce_db -f "C:\Users\varshini\datahub\create_views.sql"
```
* **Views Created**:
  * `customer_order_summary`: Aggregates orders per customer.
  * `order_item_details`: Joins order items with product catalog details.

---

## 8. Ingesting Database Metadata into DataHub

### Understanding the Key Distinction:
* **Ad-hoc `SELECT` Queries**: Running ad-hoc SQL queries in a terminal executes within database memory. PostgreSQL does not push ad-hoc queries to DataHub.
* **Database Metadata Ingestion**: DataHub queries system catalogs (`information_schema.tables`, `information_schema.columns`, foreign key constraints, `information_schema.views`) to extract:
  * Database and schema hierarchy
  * Table names, columns, and data types
  * Primary keys and Foreign keys
  * View SQL definitions and automated query-level lineage

### Ingestion Steps via DataHub UI (Zero Host Python Installation):
1. Open your browser and navigate to **`http://localhost:9002`**.
2. Log in with `datahub` / `datahub`.
3. In the left navigation bar, click **Data Sources** (under the *Admin* section).
4. Click **`+ Create new source`** (top right).
5. Select **Postgres**.
6. Enter connection parameters:
   * **Host**: `host.docker.internal:5432` *(Maps from Docker containers directly to your Windows host)*
   * **Database**: `ecommerce_db`
   * **Username**: `postgres`
   * **Password**: `[Your PostgreSQL Password]`
7. Click **Next** $\rightarrow$ **Next** (keep defaults).
8. Name the source (e.g. `Postgres E-Commerce DB`) and click **Save & Run**.
9. The ingestion task will run and transition to **`Succeeded`** within ~30 seconds, indexing:
   * **5 Tables**: `customers`, `products`, `orders`, `order_items`, `payments`
   * **2 Views**: `customer_order_summary`, `order_item_details` (with query SQL stored)
   * **Lineage Relationships**: Table $\rightarrow$ View dependencies visually rendered in the DataHub Lineage graph.

---

## 9. Everyday Lifecycle Commands

| Action | Command (Run in `C:\Users\varshini\datahub`) |
| :--- | :--- |
| **Start DataHub** | `docker compose --profile quickstart up -d` |
| **Stop DataHub** | `docker compose --profile quickstart down` |
| **Check Container Status** | `docker compose --profile quickstart ps` |
| **View Live Logs** | `docker compose --profile quickstart logs -f` |
| **View GMS Logs** | `docker logs -f datahub-datahub-gms-quickstart-1` |
| **View Actions Logs** | `docker logs -f datahub-datahub-actions-quickstart-1` |

*Note: DataHub stores all ingested metadata in Docker named volumes (`datahub_mysqldata`, `datahub_osdata`, `datahub_broker`). Stopping and starting DataHub with `down` and `up -d` will **not** lose any ingested metadata.*
