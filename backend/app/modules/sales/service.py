"""Sales services: the public entry point for routers, tools, jobs, seeds and other modules.

Implementation lives in ``enquiries`` (enquiries, customer messages), ``quotes`` (header, lines, snapshots,
persisted totals, reads), ``transitions`` (the state machine), ``approvals`` (the review handler),
``documents`` (issued revision snapshot and the PDF), ``readers`` (source readers) and ``tools``.
"""

from __future__ import annotations

from app.modules.sales.configurator import configurator_resolve
from app.modules.sales.currency import change_currency, change_currency_command, preview_currency_change
from app.modules.sales.custom_products import (
    archive_custom_product,
    create_custom_product,
    custom_history,
    custom_status_counts,
    decide_spec_revision,
    duplicate_custom_product,
    execute_promotion,
    export_custom_products_csv,
    get_custom_product,
    list_costing,
    list_custom_products,
    record_costing,
    record_spec_revision,
    request_promotion,
    transition_custom_product,
    unarchive_custom_product,
    update_custom_product,
)
from app.modules.sales.custom_products import create_command as create_custom_product_command
from app.modules.sales.custom_products import detail as custom_product_detail
from app.modules.sales.custom_products import duplicate_command as duplicate_custom_product_command
from app.modules.sales.documents import (
    build_revision_snapshot,
    document_filename,
    render_quote_pdf,
    sha256_of,
    store_rendered_document,
)
from app.modules.sales.duplicate import (
    change_owner,
    change_owner_command,
    duplicate_quote,
    duplicate_quote_command,
)
from app.modules.sales.enquiries import (
    create_customer_message_command,
    create_enquiry,
    create_enquiry_command,
    get_customer_message,
    get_enquiry,
    list_customer_messages,
    list_enquiries,
    mark_replied,
    mark_replied_command,
    record_customer_message,
    update_customer_message,
    update_customer_message_command,
    update_enquiry,
    update_enquiry_command,
)
from app.modules.sales.exports import export_quote_lines_csv, export_quotes_csv
from app.modules.sales.quote_settings import get_quote_settings, update_quote_settings
from app.modules.sales.quotes import (
    add_line,
    add_line_command,
    calculate_preview,
    create_quote,
    create_quote_command,
    delete_quote,
    delete_quote_command,
    detail,
    find_repeat_quote_basis,
    get_quote,
    get_quote_by_number,
    get_revision,
    list_quotes,
    list_revisions,
    list_status_history,
    refresh_snapshots,
    refresh_snapshots_command,
    remove_line,
    remove_line_command,
    revision_document,
    revision_row,
    status_counts,
    update_line,
    update_line_command,
    update_quote,
    update_quote_command,
)
from app.modules.sales.readers import read_enquiry_facts, read_message_facts, read_quote_facts
from app.modules.sales.revisions import compare_revisions, restore_revision, restore_revision_command
from app.modules.sales.sample_lineage import lineage as sample_lineage
from app.modules.sales.sample_lineage import link_command as sample_link_challan_command
from app.modules.sales.samples import create_command as create_sample_command
from app.modules.sales.samples import (
    create_sample,
    get_sample,
    list_samples,
    sample_status_counts,
    transition_sample,
    update_sample,
)
from app.modules.sales.samples import read as sample_read
from app.modules.sales.samples import transition_command as sample_transition_command
from app.modules.sales.tools import draft_quote
from app.modules.sales.transitions import transition_quote, transition_quote_command


def custom_product_row(uow, custom_product_id):  # type: ignore[no-untyped-def]
    """The custom product row the actor may read (404 otherwise), for composing reads after commands."""
    from app.modules.sales.models import CustomProduct

    return uow.repo(CustomProduct).get(custom_product_id)


__all__ = [
    "add_line",
    "archive_custom_product",
    "change_currency",
    "change_currency_command",
    "change_owner",
    "change_owner_command",
    "compare_revisions",
    "configurator_resolve",
    "create_custom_product",
    "create_custom_product_command",
    "create_sample",
    "create_sample_command",
    "custom_history",
    "custom_product_detail",
    "custom_product_row",
    "custom_status_counts",
    "decide_spec_revision",
    "duplicate_custom_product",
    "duplicate_custom_product_command",
    "duplicate_quote",
    "duplicate_quote_command",
    "execute_promotion",
    "export_custom_products_csv",
    "export_quote_lines_csv",
    "export_quotes_csv",
    "get_custom_product",
    "get_quote_settings",
    "get_sample",
    "list_costing",
    "list_custom_products",
    "list_samples",
    "preview_currency_change",
    "record_costing",
    "record_spec_revision",
    "request_promotion",
    "restore_revision",
    "restore_revision_command",
    "sample_lineage",
    "sample_link_challan_command",
    "sample_read",
    "sample_status_counts",
    "sample_transition_command",
    "transition_custom_product",
    "transition_sample",
    "unarchive_custom_product",
    "update_custom_product",
    "update_quote_settings",
    "update_sample",
    "add_line_command",
    "build_revision_snapshot",
    "calculate_preview",
    "create_customer_message_command",
    "create_enquiry",
    "create_enquiry_command",
    "create_quote",
    "create_quote_command",
    "delete_quote",
    "delete_quote_command",
    "detail",
    "document_filename",
    "draft_quote",
    "find_repeat_quote_basis",
    "get_customer_message",
    "get_enquiry",
    "get_quote",
    "get_quote_by_number",
    "get_revision",
    "list_customer_messages",
    "list_enquiries",
    "list_quotes",
    "list_revisions",
    "list_status_history",
    "mark_replied",
    "mark_replied_command",
    "read_enquiry_facts",
    "read_message_facts",
    "read_quote_facts",
    "record_customer_message",
    "refresh_snapshots",
    "refresh_snapshots_command",
    "remove_line",
    "remove_line_command",
    "render_quote_pdf",
    "revision_document",
    "revision_row",
    "sha256_of",
    "status_counts",
    "store_rendered_document",
    "transition_quote",
    "transition_quote_command",
    "update_customer_message",
    "update_customer_message_command",
    "update_enquiry",
    "update_enquiry_command",
    "update_line",
    "update_line_command",
    "update_quote",
    "update_quote_command",
]
