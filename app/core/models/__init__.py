"""Domain models: importing this package registers every table on ``Base.metadata``.

Anything that needs the full schema present (``Base.metadata.create_all``,
Alembic autogenerate, a fresh test database) must import
``app.core.models`` — importing ``app.core.db.base`` alone is not
enough, since ``Base`` starts out with no tables until each model
module has been imported at least once.
"""

from app.core.db.base import Base
from app.core.models.approval import ApprovalRecord
from app.core.models.asset import Asset
from app.core.models.character import Character, CharacterReference, CharacterVersion
from app.core.models.episode import (
    Episode,
    Scene,
    Script,
    Short,
    Song,
    episode_characters,
    scene_characters,
    short_scenes,
)
from app.core.models.generation_job import GenerationJob
from app.core.models.license import LicenseRecord
from app.core.models.production_task import ProductionTask
from app.core.models.prompt import PromptTemplate

__all__ = [
    "ApprovalRecord",
    "Asset",
    "Base",
    "Character",
    "CharacterReference",
    "CharacterVersion",
    "Episode",
    "GenerationJob",
    "LicenseRecord",
    "ProductionTask",
    "PromptTemplate",
    "Scene",
    "Script",
    "Short",
    "Song",
    "episode_characters",
    "scene_characters",
    "short_scenes",
]
