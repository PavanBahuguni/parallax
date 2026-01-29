"""add_test_clusters_selectors

Revision ID: 002_add_test_clusters_selectors
Revises: 001_add_projects_tasks
Create Date: 2026-01-26 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '002_add_test_clusters_selectors'
down_revision: Union[str, None] = '001_add_projects_tasks'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create test_clusters table
    op.create_table(
        'test_clusters',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('task_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('cluster_name', sa.String(255), nullable=False),
        sa.Column('test_case_id', sa.String(255), nullable=False),
        sa.Column('target_node', sa.String(255), nullable=False),
        sa.Column('purpose', sa.Text(), nullable=True),
        sa.Column('mission_file', sa.String(500), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='active'),
        sa.Column('extra_data', postgresql.JSONB(), nullable=True, server_default='{}'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='SET NULL'),
    )

    # Create selector_corrections table
    op.create_table(
        'selector_corrections',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('node_id', sa.String(255), nullable=False),
        sa.Column('component_role', sa.String(255), nullable=True),
        sa.Column('original_selector', sa.Text(), nullable=False),
        sa.Column('corrected_selector', sa.Text(), nullable=False),
        sa.Column('action_type', sa.String(50), nullable=True),
        sa.Column('context', postgresql.JSONB(), nullable=True, server_default='{}'),
        sa.Column('success_count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('last_used_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    )

    # Create indexes for efficient lookups
    op.create_index('ix_test_clusters_project_id', 'test_clusters', ['project_id'])
    op.create_index('ix_test_clusters_cluster_name', 'test_clusters', ['cluster_name'])
    op.create_index('ix_test_clusters_target_node', 'test_clusters', ['target_node'])
    op.create_index('ix_test_clusters_status', 'test_clusters', ['status'])
    
    op.create_index('ix_selector_corrections_project_id', 'selector_corrections', ['project_id'])
    op.create_index('ix_selector_corrections_node_id', 'selector_corrections', ['node_id'])
    op.create_index('ix_selector_corrections_original', 'selector_corrections', ['original_selector'])
    
    # Unique constraint to prevent duplicate corrections for same selector
    op.create_unique_constraint(
        'uq_selector_correction_original',
        'selector_corrections',
        ['project_id', 'node_id', 'original_selector']
    )


def downgrade() -> None:
    op.drop_constraint('uq_selector_correction_original', 'selector_corrections', type_='unique')
    op.drop_index('ix_selector_corrections_original', table_name='selector_corrections')
    op.drop_index('ix_selector_corrections_node_id', table_name='selector_corrections')
    op.drop_index('ix_selector_corrections_project_id', table_name='selector_corrections')
    op.drop_index('ix_test_clusters_status', table_name='test_clusters')
    op.drop_index('ix_test_clusters_target_node', table_name='test_clusters')
    op.drop_index('ix_test_clusters_cluster_name', table_name='test_clusters')
    op.drop_index('ix_test_clusters_project_id', table_name='test_clusters')
    op.drop_table('selector_corrections')
    op.drop_table('test_clusters')
