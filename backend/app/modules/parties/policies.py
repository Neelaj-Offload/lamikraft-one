"""Party record scope: own (owner), team (owner among peers), branch (party branch), company.

Contacts, addresses and tax identifiers are children authorised only through their party.
"""

from __future__ import annotations

from app.modules.parties.models import Party, PartyAddress, PartyContact, PartyTaxIdentifier
from app.platform.authz.policy import ParentRef, ResourcePolicy

PARTY_POLICY = ResourcePolicy(
    resource_type="parties.party",
    model=Party,
    permission_prefix="parties.party",
    owner_columns=("owner_user_id",),
    branch_column="branch_id",
    business_key_column="party_number",
    label=lambda p: f"{p.party_number} · {p.display_name}",
    canonical_path=lambda p: f"/sales/parties/{p.id}",
)

CONTACT_POLICY = ResourcePolicy(
    resource_type="parties.party_contact",
    model=PartyContact,
    permission_prefix="parties.party",
    parent=ParentRef("parties.party", "party_id"),
)
ADDRESS_POLICY = ResourcePolicy(
    resource_type="parties.party_address",
    model=PartyAddress,
    permission_prefix="parties.party",
    parent=ParentRef("parties.party", "party_id"),
)
TAX_IDENTIFIER_POLICY = ResourcePolicy(
    resource_type="parties.party_tax_identifier",
    model=PartyTaxIdentifier,
    permission_prefix="parties.party",
    parent=ParentRef("parties.party", "party_id"),
)

POLICIES = [PARTY_POLICY, CONTACT_POLICY, ADDRESS_POLICY, TAX_IDENTIFIER_POLICY]
