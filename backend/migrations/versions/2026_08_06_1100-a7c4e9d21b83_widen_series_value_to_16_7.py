"""widen_series_value_to_16_7

Revision ID: a7c4e9d21b83
Revises: b2c3d4e5f6a1

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c4e9d21b83"
down_revision: Union[str, None] = "b2c3d4e5f6a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Numeric(10,3) quantized every sample value to 3 decimals, which is fine
    # for bpm/steps/watts but destroys GPS coordinates: latitude 52.229676 was
    # stored as 52.230, i.e. ~110 m of positional error. Widen to 7 decimals
    # (the GPS convention, ~1 cm) and keep a 9-digit integer part so step and
    # energy magnitudes retain their previous headroom.
    for table in ("data_point_series", "data_point_series_archive"):
        op.alter_column(
            table,
            "value",
            existing_type=sa.Numeric(precision=10, scale=3),
            type_=sa.Numeric(precision=16, scale=7),
            existing_nullable=False,
        )


def downgrade() -> None:
    # Narrowing re-quantizes to 3 decimals; coordinates written at full
    # precision lose it again (Postgres rounds, it does not fail).
    for table in ("data_point_series", "data_point_series_archive"):
        op.alter_column(
            table,
            "value",
            existing_type=sa.Numeric(precision=16, scale=7),
            type_=sa.Numeric(precision=10, scale=3),
            existing_nullable=False,
        )
