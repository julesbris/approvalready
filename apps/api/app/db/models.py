"""Import every module that defines mapped tables so Alembic autogenerate sees them."""

from app.modules.ai import models as ai_models  # noqa: F401
from app.modules.assessments import models as assessments_models  # noqa: F401
from app.modules.audit import models as audit_models  # noqa: F401
from app.modules.billing import models as billing_models  # noqa: F401
from app.modules.checklists import models as checklists_models  # noqa: F401
from app.modules.documents import models as documents_models  # noqa: F401
from app.modules.entities import models as entities_models  # noqa: F401
from app.modules.grants import models as grants_models  # noqa: F401
from app.modules.identity import models as identity_models  # noqa: F401
from app.modules.leads import models as leads_models  # noqa: F401
from app.modules.marketplace import models as marketplace_models  # noqa: F401
from app.modules.notifications import models as notifications_models  # noqa: F401
from app.modules.ops import models as ops_models  # noqa: F401
from app.modules.partners import models as partners_models  # noqa: F401
from app.modules.privacy import models as privacy_models  # noqa: F401
from app.modules.projects import models as projects_models  # noqa: F401
from app.modules.questionnaires import models as questionnaires_models  # noqa: F401
from app.modules.regulatory import models as regulatory_models  # noqa: F401
from app.modules.rentals import models as rentals_models  # noqa: F401
from app.modules.review import models as review_models  # noqa: F401
from app.modules.rules import models as rules_models  # noqa: F401
from app.modules.sales import models as sales_models  # noqa: F401
from app.modules.tenancy import models as tenancy_models  # noqa: F401
from app.modules.vessels import models as vessels_models  # noqa: F401
