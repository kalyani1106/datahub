#!/usr/bin/env python3
"""
=============================================================================
DataHub Knowledge Graph Query Utility (Apache AGE)
=============================================================================
Runs Cypher queries against the `datahub_knowledge_graph` inside Apache AGE.
Provides quick CLI commands to inspect databases, tables, lineages, and
foreign key references.

Usage:
  python query_knowledge_graph.py --summary
  python query_knowledge_graph.py --db healthcare_db
  python query_knowledge_graph.py --db ecommerce_db
  python query_knowledge_graph.py --lineage
  python query_knowledge_graph.py --references
  python query_knowledge_graph.py --cypher "MATCH (t:Table) RETURN t.name, t.database LIMIT 5"
=============================================================================
"""

import os
import sys
import argparse
import psycopg

HOST = os.getenv("AGE_HOST", "localhost")
PORT = int(os.getenv("AGE_PORT", "5455"))
DBNAME = os.getenv("AGE_DB", "knowledge_graph_demo")
USER = os.getenv("AGE_USER", "postgres")
PASSWORD = os.getenv("AGE_PASSWORD", "postgres")
GRAPH_NAME = os.getenv("AGE_GRAPH_NAME", "datahub_knowledge_graph")


def get_conn():
    conn = psycopg.connect(
        host=HOST,
        port=PORT,
        dbname=DBNAME,
        user=USER,
        password=PASSWORD
    )
    cur = conn.cursor()
    cur.execute("LOAD 'age';")
    cur.execute('SET search_path = ag_catalog, "$user", public;')
    return conn


def run_cypher(cypher_query: str, return_types: str = "result agtype"):
    conn = get_conn()
    cur = conn.cursor()
    sql = f"""
    SELECT * FROM ag_catalog.cypher(
        '{GRAPH_NAME}',
        $$
        {cypher_query}
        $$
    ) AS ({return_types});
    """
    try:
        cur.execute(sql)
        rows = cur.fetchall()
        return rows
    finally:
        conn.close()


def print_summary():
    print("\n" + "=" * 70)
    print("      DATAHUB KNOWLEDGE GRAPH SUMMARY (Apache AGE)")
    print("=" * 70)

    rows = run_cypher("MATCH (d:Database) RETURN d.name, d.platform, d.table_count", "name agtype, platform agtype, tbls agtype")
    print("\nDatabases:")
    for r in rows:
        print(f"  • {r[0]} (Platform: {r[1]}, Tables: {r[2]})")

    rows = run_cypher("""
    MATCH (t:Table)
    RETURN t.database, count(t)
    """, "db agtype, cnt agtype")
    print("\nTables per Database:")
    for r in rows:
        print(f"  • {r[0]}: {r[1]} tables")

    rows = run_cypher("""
    MATCH ()-[r]->()
    RETURN label(r), count(r)
    """, "edge_type agtype, cnt agtype")
    print("\nEdges by Type:")
    for r in rows:
        print(f"  • {r[0]}: {r[1]} edges")
    print("=" * 70 + "\n")


def print_database(db_name: str):
    print(f"\n================ Database: {db_name} ================")
    rows = run_cypher(f"""
    MATCH (t:Table {{database: '{db_name}'}})
    RETURN t.name, t.subtype, t.column_count
    """, "name agtype, subtype agtype, cols agtype")
    print("Tables & Views:")
    for r in rows:
        print(f"  • {r[0]} [{r[1]}] - {r[2]} columns")

    rows = run_cypher(f"""
    MATCH (a:Table {{database: '{db_name}'}})-[r:REFERENCES]->(b:Table)
    RETURN a.name, r.from_column, b.name, r.to_column, r.confidence
    """, "a agtype, fc agtype, b agtype, tc agtype, conf agtype")
    print("\nReferences (FK -> PK):")
    for r in rows:
        print(f"  • {r[0]}.{r[1]} -> {r[2]}.{r[3]} (conf: {r[4]})")

    rows = run_cypher(f"""
    MATCH (a:Table {{database: '{db_name}'}})-[r:DERIVES_FROM]->(b:Table)
    RETURN a.name, b.name, r.lineage_type
    """, "a agtype, b agtype, lt agtype")
    print("\nLineages (DERIVES_FROM):")
    for r in rows:
        print(f"  • {r[0]} -> {r[1]} (type: {r[2]})")
    print("=" * 55 + "\n")


def print_lineages():
    print("\n" + "=" * 70)
    print("             DATAHUB LINEAGE RELATIONSHIPS (Cypher)")
    print("=" * 70)
    rows = run_cypher("""
    MATCH (a:Table)-[r:DERIVES_FROM]->(b:Table)
    RETURN a.name, a.database, b.name, b.database, r.lineage_type
    """, "src agtype, src_db agtype, tgt agtype, tgt_db agtype, ltype agtype")
    for r in rows:
        same_db = "(internal)" if r[1] == r[3] else f"(cross-platform: {r[1]} -> {r[3]})"
        print(f"  • [{r[1]}] {r[0]}  ==DERIVES_FROM==>  [{r[3]}] {r[2]}  [{r[4]}] {same_db}")
    print("=" * 70 + "\n")


def print_references():
    print("\n" + "=" * 70)
    print("             DATAHUB SEMANTIC REFERENCES (Cypher)")
    print("=" * 70)
    rows = run_cypher("""
    MATCH (a:Table)-[r:REFERENCES]->(b:Table)
    RETURN a.name, a.database, r.from_column, b.name, r.to_column, r.confidence, r.is_inferred
    """, "src agtype, db agtype, fc agtype, tgt agtype, tc agtype, conf agtype, inf agtype")
    for r in rows:
        inf_label = "INFERRED" if str(r[6]).lower() == "true" else "EXPLICIT"
        print(f"  • [{r[1]}] {r[0]}.{r[2]}  ==REFERENCES==>  {r[3]}.{r[4]}  [conf: {r[5]}, {inf_label}]")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Query DataHub Knowledge Graph in Apache AGE")
    parser.add_argument("--summary", action="store_true", help="Print summary statistics")
    parser.add_argument("--db", type=str, help="Print details for a specific database (e.g. healthcare_db)")
    parser.add_argument("--lineage", action="store_true", help="List all lineage edges")
    parser.add_argument("--references", action="store_true", help="List all reference edges")
    parser.add_argument("--cypher", type=str, help="Execute custom Cypher query")
    args = parser.parse_args()

    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if args.summary:
        print_summary()
    elif args.db:
        print_database(args.db)
    elif args.lineage:
        print_lineages()
    elif args.references:
        print_references()
    elif args.cypher:
        print(f"\nExecuting Cypher: {args.cypher}")
        results = run_cypher(args.cypher)
        for row in results:
            print(row)
    else:
        print_summary()
