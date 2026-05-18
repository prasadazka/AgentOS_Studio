"""Seed the GWDB Data Cleaning & Export workflow into AgentOS Studio."""

import json
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.database import get_db
from core.workflow_manager import create_workflow


GWDB_WORKFLOW = {
    "name": "GWDB Data Cleaning & Export",
    "description": "Upload GWDB file → remove duplicates → fill missing fields → apply SQL schema → review → export (DB/JSON/Excel)",
    "graph_json": {
        "nodes": [
            # ── 1. START: Accept file + export format ──
            {
                "id": "start_1",
                "type": "start",
                "position": {"x": 50, "y": 200},
                "data": {
                    "type": "start",
                    "label": "Upload & Configure",
                    "inputFields": [
                        {
                            "name": "file_path",
                            "label": "GWDB File Path",
                            "type": "file",
                            "required": True,
                            "placeholder": "e.g. WellMain.txt or DB_WellData.txt"
                        },
                        {
                            "name": "export_format",
                            "label": "Export Format",
                            "type": "select",
                            "required": True,
                            "options": ["sqlite", "json", "excel", "csv", "parquet"],
                            "defaultValue": "sqlite"
                        }
                    ]
                }
            },

            # ── 2. AGENT: Load & Profile Data ──
            {
                "id": "agent_load_2",
                "type": "agent",
                "position": {"x": 300, "y": 200},
                "data": {
                    "type": "agent",
                    "label": "Load & Profile",
                    "agentName": "GWDBDataAgent",
                    "agentSystemPrompt": (
                        "You are a data loading specialist. Given a file path:\n"
                        "1. Load the file using gwdb_load_wellmain (for WellMain) or gwdb_load_file (for others)\n"
                        "2. Run gwdb_data_profile to get a full quality report\n"
                        "3. Report: total rows, columns, missing value counts, duplicate counts\n"
                        "Return a clear summary of the data quality issues found."
                    ),
                    "agentTools": [
                        "gwdb_load_wellmain", "gwdb_load_file",
                        "gwdb_data_profile", "gwdb_missing_values", "gwdb_duplicates"
                    ]
                }
            },

            # ── 3. AGENT: Clean Data (Remove Duplicates + Fill Missing) ──
            {
                "id": "agent_clean_3",
                "type": "agent",
                "position": {"x": 550, "y": 200},
                "data": {
                    "type": "agent",
                    "label": "Clean Data",
                    "agentName": "GWDBDataAgent",
                    "agentSystemPrompt": (
                        "You are a data cleaning specialist. Based on the quality profile from the previous step:\n"
                        "1. Use gwdb_duplicates to identify duplicate rows\n"
                        "2. Use gwdb_remove_duplicates to remove duplicate rows (keeps first occurrence)\n"
                        "3. Use gwdb_missing_values to identify columns with missing values\n"
                        "4. Use gwdb_fill_missing with strategy='median' for numeric columns\n"
                        "5. Use gwdb_fill_missing with strategy='unknown' for text columns\n"
                        "6. Run gwdb_data_profile again to confirm cleaning results\n"
                        "Report: rows removed, fields filled, before/after comparison."
                    ),
                    "agentTools": [
                        "gwdb_duplicates", "gwdb_missing_values",
                        "gwdb_remove_duplicates", "gwdb_fill_missing",
                        "gwdb_data_profile", "gwdb_count"
                    ]
                }
            },

            # ── 4. AGENT: Apply SQL Schema Mapping ──
            {
                "id": "agent_schema_4",
                "type": "agent",
                "position": {"x": 800, "y": 200},
                "data": {
                    "type": "agent",
                    "label": "Apply Schema",
                    "agentName": "GWDBDataAgent",
                    "agentSystemPrompt": (
                        "You are a database schema specialist. Your job:\n"
                        "1. Use gwdb_map_to_tables to show how the cleaned data maps to normalized SQL tables\n"
                        "2. Use gwdb_preview_push to do a dry-run showing what each target table will contain\n"
                        "3. Report the mapping: source columns → target tables, with row counts per table\n"
                        "DO NOT execute the push. Just show the mapping and preview."
                    ),
                    "agentTools": [
                        "gwdb_map_to_tables", "gwdb_preview_push",
                        "gwdb_show_schema", "gwdb_table_info"
                    ]
                }
            },

            # ── 5. APPROVAL: Review before export ──
            {
                "id": "approval_5",
                "type": "approval",
                "position": {"x": 1050, "y": 200},
                "data": {
                    "type": "approval",
                    "label": "Review & Approve",
                    "approvalPrompt": "Review the data cleaning results and schema mapping above. Approve to proceed with export, or reject to cancel.",
                    "approvalTimeout": 600,
                    "autoApprove": False
                }
            },

            # ── 6. AGENT: Export Data ──
            {
                "id": "agent_export_6",
                "type": "agent",
                "position": {"x": 1300, "y": 200},
                "data": {
                    "type": "agent",
                    "label": "Export Data",
                    "agentName": "GWDBDataAgent",
                    "agentSystemPrompt": (
                        "You are a data export specialist. The user has approved the data for export.\n"
                        "Based on the export format requested in the original input:\n"
                        "- sqlite: Use gwdb_to_sqlite to export all mapped tables to a .db file\n"
                        "- json: Use gwdb_to_json to export as JSON\n"
                        "- excel: Use gwdb_to_excel to export as .xlsx\n"
                        "- csv: Use gwdb_to_csv to export as CSV\n"
                        "- parquet: Use gwdb_to_parquet to export as Parquet\n"
                        "Use the output_dir if provided in context. Name the file 'gwdb_cleaned_export' with the appropriate extension.\n"
                        "Report: file path, file size, format, row count."
                    ),
                    "agentTools": [
                        "gwdb_to_sqlite", "gwdb_to_json", "gwdb_to_excel",
                        "gwdb_to_csv", "gwdb_to_parquet", "gwdb_save_as"
                    ]
                }
            },

            # ── 7. END ──
            {
                "id": "end_7",
                "type": "end",
                "position": {"x": 1550, "y": 200},
                "data": {
                    "type": "end",
                    "label": "Done"
                }
            }
        ],
        "edges": [
            {"id": "e1", "source": "start_1", "target": "agent_load_2", "animated": True, "style": {"stroke": "#94a3b8", "strokeWidth": 2}},
            {"id": "e2", "source": "agent_load_2", "target": "agent_clean_3", "animated": True, "style": {"stroke": "#94a3b8", "strokeWidth": 2}},
            {"id": "e3", "source": "agent_clean_3", "target": "agent_schema_4", "animated": True, "style": {"stroke": "#94a3b8", "strokeWidth": 2}},
            {"id": "e4", "source": "agent_schema_4", "target": "approval_5", "animated": True, "style": {"stroke": "#94a3b8", "strokeWidth": 2}},
            {"id": "e5", "source": "approval_5", "target": "agent_export_6", "animated": True, "style": {"stroke": "#94a3b8", "strokeWidth": 2}},
            {"id": "e6", "source": "agent_export_6", "target": "end_7", "animated": True, "style": {"stroke": "#94a3b8", "strokeWidth": 2}},
        ]
    }
}


def seed():
    """Create or update the GWDB workflow in the database."""
    from core.workflow_manager import list_workflows, update_workflow

    get_db()  # ensures tables are created

    # Check if workflow already exists (avoid duplicates)
    existing = list_workflows()
    for w in existing:
        if w["name"] == GWDB_WORKFLOW["name"]:
            wf = update_workflow(
                w["id"],
                description=GWDB_WORKFLOW["description"],
                graph_json=GWDB_WORKFLOW["graph_json"],
            )
            print(f"Updated workflow: {wf['name']} (ID: {wf['id']})")
            print(f"  Nodes: {len(GWDB_WORKFLOW['graph_json']['nodes'])}")
            print(f"  Edges: {len(GWDB_WORKFLOW['graph_json']['edges'])}")
            print("  Flow: Upload -> Load & Profile -> Clean Data -> Apply Schema -> Review -> Export -> Done")
            return wf

    wf = create_workflow(
        name=GWDB_WORKFLOW["name"],
        description=GWDB_WORKFLOW["description"],
        graph_json=GWDB_WORKFLOW["graph_json"],
    )
    print(f"Created workflow: {wf['name']} (ID: {wf['id']})")
    print(f"  Nodes: {len(GWDB_WORKFLOW['graph_json']['nodes'])}")
    print(f"  Edges: {len(GWDB_WORKFLOW['graph_json']['edges'])}")
    print("  Flow: Upload -> Load & Profile -> Clean Data -> Apply Schema -> Review -> Export -> Done")
    return wf


if __name__ == "__main__":
    seed()
