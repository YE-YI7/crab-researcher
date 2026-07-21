"""ORM model registry.

Importing this package registers every table with SQLAlchemy metadata.
"""

from app.models.growth import *  # noqa: F401,F403
from app.models.growth_memory import *  # noqa: F401,F403
from app.models.browser import *  # noqa: F401,F403
from app.models.scan import *  # noqa: F401,F403
from app.models.task import *  # noqa: F401,F403
