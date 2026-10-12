"""Sequence definitions. Defaults preserve the legacy formats (owner to confirm reset policies)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ResetPolicy = Literal["never", "yearly", "financial_year"]


@dataclass(frozen=True)
class SequenceDef:
    key: str
    name: str
    format_template: str  # tokens: {yyyy} {yy} {fy} {seq:04} plus caller-supplied tokens like {brand}
    reset_policy: ResetPolicy
    resource_type: str
    start_value: int = 1

    def __post_init__(self) -> None:
        if "{seq" not in self.format_template:
            raise ValueError(f"sequence {self.key} format must contain {{seq:N}}")
        if self.reset_policy == "yearly" and "{yyyy}" not in self.format_template and "{yy}" not in self.format_template:
            raise ValueError(f"yearly sequence {self.key} must include {{yyyy}} or {{yy}}")
        if self.reset_policy == "financial_year" and "{fy}" not in self.format_template:
            raise ValueError(f"financial-year sequence {self.key} must include {{fy}}")
