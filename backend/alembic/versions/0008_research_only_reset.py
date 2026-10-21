"""reset to research only: drop course, assessment and knowledge-registry tables"""

import importlib.util
from pathlib import Path

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

# Course workflow tables (0004) and the unused knowledge registry (0003), children first.
TABLES = [
    "learning_run_quiz_submissions", "learning_run_assignment_submissions", "learning_run_lesson_progress",
    "assessments_staging", "courses_staging", "claims_staging", "concepts_staging", "sections_staging",
    "resource_versions_staging", "resources_staging", "mastery_estimates", "evaluations", "attempts",
    "assessments", "enrollments", "courses", "coverage_ledger", "claims", "concepts", "sections",
    "resource_versions", "resources", "profiles",
]


def upgrade():
    for table in TABLES:
        op.drop_table(table, if_exists=True)


def _migration(filename: str):
    spec = importlib.util.spec_from_file_location(filename, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def downgrade():
    # Recreate the dropped schema exactly as the original migrations defined it.
    _migration("0003_knowledge_registry_security.py").upgrade()
    _migration("0004_learning_workflow_submissions.py").upgrade()
