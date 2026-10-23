"""Commercial rule sets are company configuration read with ``commercial.rule_set.read``."""

from __future__ import annotations

from app.modules.commercial.models import RuleSet
from app.platform.authz.policy import ResourcePolicy

RULE_SET_POLICY = ResourcePolicy(
    resource_type="commercial.rule_set",
    model=RuleSet,
    permission_prefix="commercial.rule_set",
    label=lambda r: f"{r.code} v{r.version_no}",
)

POLICIES = [RULE_SET_POLICY]
