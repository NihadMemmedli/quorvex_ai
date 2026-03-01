"""Add scalability indexes for 100K+ scale.

Composite indexes for high-traffic query patterns across all major models:
TestRun, SpecMetadata, RegressionBatch, LoadTestRun, SecurityScanRun,
SecurityFinding, DbTestRun, LlmTestRun, LlmTestResult, ChatConversation,
AutoPilotSession.

Revision ID: 006
Revises: 005
Create Date: 2026-02-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # TestRun - project+status, project+created_at, status, batch+status
    # Note: ix_testrun_spec_name already exists from migration 002
    op.create_index("ix_testrun_project_status", "testrun", ["project_id", "status"])
    op.create_index("ix_testrun_project_created", "testrun", ["project_id", "created_at"])
    op.create_index("ix_testrun_status", "testrun", ["status"])
    op.create_index("ix_testrun_batch_status", "testrun", ["batch_id", "status"])

    # SpecMetadata - project+spec_name
    op.create_index("ix_specmetadata_project_spec", "specmetadata", ["project_id", "spec_name"])

    # RegressionBatch - project+status, project+created_at
    op.create_index("ix_regressionbatch_project_status", "regression_batches", ["project_id", "status"])
    op.create_index("ix_regressionbatch_project_created", "regression_batches", ["project_id", "created_at"])

    # LoadTestRun - project+status
    op.create_index("ix_loadtestrun_project_status", "load_test_runs", ["project_id", "status"])

    # SecurityScanRun - project+status
    op.create_index("ix_securityscanrun_project_status", "security_scan_runs", ["project_id", "status"])

    # SecurityFinding - project+severity+status, scan+severity
    op.create_index("ix_securityfinding_project_severity", "security_findings", ["project_id", "severity", "status"])
    op.create_index("ix_securityfinding_scan_severity", "security_findings", ["scan_id", "severity"])

    # DbTestRun - project+status
    op.create_index("ix_dbtestrun_project_status", "db_test_runs", ["project_id", "status"])

    # LlmTestRun - project+status, project+created_at
    op.create_index("ix_llmtestrun_project_status", "llm_test_runs", ["project_id", "status"])
    op.create_index("ix_llmtestrun_project_created", "llm_test_runs", ["project_id", "created_at"])

    # LlmTestResult - run+test_case_id
    op.create_index("ix_llmtestresult_run_case", "llm_test_results", ["run_id", "test_case_id"])

    # ChatConversation - project+created_at
    op.create_index("ix_chatconversation_project_created", "chat_conversations", ["project_id", "created_at"])

    # AutoPilotSession - project+status
    op.create_index("ix_autopilotsession_project_status", "autopilot_sessions", ["project_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_autopilotsession_project_status", table_name="autopilot_sessions")
    op.drop_index("ix_chatconversation_project_created", table_name="chat_conversations")
    op.drop_index("ix_llmtestresult_run_case", table_name="llm_test_results")
    op.drop_index("ix_llmtestrun_project_created", table_name="llm_test_runs")
    op.drop_index("ix_llmtestrun_project_status", table_name="llm_test_runs")
    op.drop_index("ix_dbtestrun_project_status", table_name="db_test_runs")
    op.drop_index("ix_securityfinding_scan_severity", table_name="security_findings")
    op.drop_index("ix_securityfinding_project_severity", table_name="security_findings")
    op.drop_index("ix_securityscanrun_project_status", table_name="security_scan_runs")
    op.drop_index("ix_loadtestrun_project_status", table_name="load_test_runs")
    op.drop_index("ix_regressionbatch_project_created", table_name="regression_batches")
    op.drop_index("ix_regressionbatch_project_status", table_name="regression_batches")
    op.drop_index("ix_specmetadata_project_spec", table_name="specmetadata")
    op.drop_index("ix_testrun_batch_status", table_name="testrun")
    op.drop_index("ix_testrun_status", table_name="testrun")
    op.drop_index("ix_testrun_project_created", table_name="testrun")
    op.drop_index("ix_testrun_project_status", table_name="testrun")
