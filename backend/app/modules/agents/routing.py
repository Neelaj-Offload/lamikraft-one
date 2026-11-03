"""The routing table (ai-routing.md section 2) and the ``ai_routing`` org setting.

Defaults come from the environment (``LK_MODEL_*``); a company can override models, caps, quotas, the price table
used by the usage dashboard and record the DPDP approval (section 8) in Settings → AI routing
(``agents.ai_routing.manage``: MFA + recent authentication through the platform's step-up helper, applied by
``org.service.update_setting``; read with ``agents.ai_usage.read``).

``RoutingTable`` is a frozen value the worker resolves once per run (``resolve``); nothing here calls a provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.config import get_settings
from app.core.money import DecimalStr
from app.modules.agents.policies import AI_ROUTING_MANAGE
from app.platform.org.settings import SettingDef

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork

AI_ROUTING_KEY = "ai_routing"
ModelId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=80, pattern=r"^[a-z0-9][a-z0-9.\-]*$")]
Effort = Literal["low", "medium", "high"]

#: per task class: step budget, time budget (s), input-token budget, per-call max_tokens cap (section 2)
TASK_BUDGETS: dict[str, dict[str, int]] = {
    "orchestration": {"steps": 8, "seconds": 45, "input_tokens": 120_000, "max_tokens": 8_192},
    "escalation": {"steps": 10, "seconds": 90, "input_tokens": 200_000, "max_tokens": 16_000},
    "routing": {"steps": 1, "seconds": 10, "input_tokens": 8_000, "max_tokens": 1_024},
    "phrasing": {"steps": 1, "seconds": 15, "input_tokens": 8_000, "max_tokens": 600},
}
PHRASING_CAPS = {"phrasing": 600, "narration": 1_200, "explain": 800, "notification": 400}
#: section 7 defaults
DEFAULT_QUOTAS = {"orchestrator_runs_per_user": 150, "escalations_per_user": 10, "vision_calls_per_user": 60,
                  "company_escalations": 100}
#: list prices at the time of writing (USD per million tokens); the setting is authoritative for the dashboard
DEFAULT_PRICES: tuple[dict[str, Any], ...] = (
    {"model": "claude-haiku-5-5", "input": "0.10", "output": "0.50", "cache_read": "0.01", "cache_write": "0.125"},
    {"model": "claude-sonnet-5-5", "input": "2.00", "output": "10.00", "cache_read": "0.20", "cache_write": "2.50"},
    {"model": "claude-opus-5-5", "input": "4.00", "output": "20.00", "cache_read": "0.20", "cache_write": "5.00"},
)


class _Value(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RoutingModels(_Value):
    """Empty values fall back to the environment (``LK_MODEL_*``)."""

    phrasing: ModelId | None = None
    orchestrator: ModelId | None = None
    escalation: ModelId | None = None
    vision: ModelId | None = None


class RoutingQuotas(_Value):
    orchestrator_runs_per_user: int = Field(default=DEFAULT_QUOTAS["orchestrator_runs_per_user"], ge=0, le=100_000)
    escalations_per_user: int = Field(default=DEFAULT_QUOTAS["escalations_per_user"], ge=0, le=100_000)
    vision_calls_per_user: int = Field(default=DEFAULT_QUOTAS["vision_calls_per_user"], ge=0, le=100_000)
    company_escalations: int = Field(default=DEFAULT_QUOTAS["company_escalations"], ge=0, le=1_000_000)


class PriceRow(_Value):
    """USD per million tokens. Used only to estimate cost at report time; never stored as money."""

    model: ModelId
    input: DecimalStr = Field(ge=0)
    output: DecimalStr = Field(ge=0)
    cache_read: DecimalStr = Field(default="0", ge=0)
    cache_write: DecimalStr = Field(default="0", ge=0)


class DpdpApproval(_Value):
    """Section 8: live AI stays off in production until the owner records approval under India's DPDP Act."""

    approved: bool = False
    approved_on: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    approved_by: Annotated[str, StringConstraints(max_length=120)] | None = None
    scope: Annotated[str, StringConstraints(max_length=500)] | None = None
    decision_ref: Annotated[str, StringConstraints(max_length=40)] | None = None


class AiRoutingSetting(_Value):
    models: RoutingModels = Field(default_factory=RoutingModels)
    orchestrator_effort: Effort = "medium"
    escalation_effort: Effort = "medium"
    quotas: RoutingQuotas = Field(default_factory=RoutingQuotas)
    prices: list[PriceRow] = Field(default_factory=lambda: [PriceRow(**row) for row in DEFAULT_PRICES], max_length=20)
    price_currency: Literal["USD"] = "USD"
    dpdp: DpdpApproval = Field(default_factory=DpdpApproval)


AI_ROUTING_SETTING = SettingDef(
    key=AI_ROUTING_KEY,
    model=AiRoutingSetting,
    description="AI routing: models per task class, effort, daily quotas, the price table for usage estimates and the DPDP approval.",
    # the generic settings endpoints read with org.settings.read; agents.ai_usage.read holders see the effective
    # table through GET /admin/ai/status
    read_permission="org.settings.read",
    manage_permission=AI_ROUTING_MANAGE,
    owner_module="agents",
)


@dataclass(frozen=True)
class RoutingTable:
    phrasing_model: str
    orchestrator_model: str
    escalation_model: str
    vision_model: str
    orchestrator_effort: str
    escalation_effort: str
    quotas: dict[str, int]
    prices: tuple[PriceRow, ...]
    dpdp: DpdpApproval
    mode: str

    def model_for(self, task_class: str) -> str:
        return {
            "routing": self.phrasing_model, "phrasing": self.phrasing_model, "verify": self.phrasing_model,
            "escalation": self.escalation_model, "vision": self.vision_model,
        }.get(task_class, self.orchestrator_model)

    def effort_for(self, task_class: str) -> str:
        if task_class == "escalation":
            return self.escalation_effort
        if task_class == "orchestration":
            return self.orchestrator_effort
        return "low"

    def budget(self, task_class: str) -> dict[str, int]:
        return dict(TASK_BUDGETS.get(task_class, TASK_BUDGETS["orchestration"]))

    def price_for(self, model: str) -> PriceRow | None:
        return next((p for p in self.prices if p.model == model), None)

    def estimate_usd(self, model: str, *, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0) -> Decimal | None:
        """Estimated cost in USD from the price table; None when the model has no row (never a guess)."""
        price = self.price_for(model)
        if price is None:
            return None
        per = Decimal(1_000_000)
        total = (Decimal(input_tokens) * Decimal(price.input) + Decimal(output_tokens) * Decimal(price.output)
                 + Decimal(cache_read) * Decimal(price.cache_read) + Decimal(cache_write) * Decimal(price.cache_write)) / per
        return total.quantize(Decimal("0.000001"))

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "models": {"phrasing": self.phrasing_model, "orchestrator": self.orchestrator_model,
                       "escalation": self.escalation_model, "vision": self.vision_model},
            "effort": {"orchestration": self.orchestrator_effort, "escalation": self.escalation_effort, "routing": "low", "phrasing": "low"},
            "budgets": {k: dict(v) for k, v in TASK_BUDGETS.items()},
            "quotas": dict(self.quotas),
            "price_currency": "USD",
            "prices": [p.model_dump(mode="json") for p in self.prices],
            "dpdp": self.dpdp.model_dump(mode="json"),
        }


def table_from(value: AiRoutingSetting | None = None) -> RoutingTable:
    settings = get_settings()
    value = value or AiRoutingSetting()
    return RoutingTable(
        phrasing_model=value.models.phrasing or settings.model_phrasing,
        orchestrator_model=value.models.orchestrator or settings.model_orchestrator,
        escalation_model=value.models.escalation or settings.model_escalation,
        vision_model=value.models.vision or settings.model_vision,
        orchestrator_effort=value.orchestrator_effort,
        escalation_effort=value.escalation_effort,
        quotas=value.quotas.model_dump(),
        prices=tuple(value.prices),
        dpdp=value.dpdp,
        mode=settings.ai_mode,
    )


def resolve(uow: UnitOfWork) -> RoutingTable:
    """The effective table for the actor's company (permission-free: the worker runs as the member)."""
    from app.platform.org.service import stored_or_default

    try:
        value = stored_or_default(uow, AI_ROUTING_KEY)
    except KeyError:  # setting not registered (module loaded without the org registry)
        return table_from()
    return table_from(value if isinstance(value, AiRoutingSetting) else AiRoutingSetting.model_validate(value.model_dump()))


__all__ = [
    "AI_ROUTING_KEY",
    "AI_ROUTING_SETTING",
    "DEFAULT_PRICES",
    "DEFAULT_QUOTAS",
    "PHRASING_CAPS",
    "TASK_BUDGETS",
    "AiRoutingSetting",
    "DpdpApproval",
    "PriceRow",
    "RoutingTable",
    "resolve",
    "table_from",
]
