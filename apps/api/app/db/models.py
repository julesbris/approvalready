"""Import every module that defines mapped tables so Alembic autogenerate sees them."""

from app.modules.audit import models as audit_models  # noqa: F401
from app.modules.entities import models as entities_models  # noqa: F401
from app.modules.identity import models as identity_models  # noqa: F401
from app.modules.projects import models as projects_models  # noqa: F401
from app.modules.questionnaires import models as questionnaires_models  # noqa: F401
from app.modules.tenancy import models as tenancy_models  # noqa: F401
