"""Product media (LM-23..26, FG-MED-01/06..09, API-25/26/28): attach uploads through ``platform/files``, one primary
image, soft delete with reason and restore, own-scope management, authorised downloads."""

from __future__ import annotations

from types import MappingProxyType

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed, VersionConflict
from app.modules.catalogue import media
from app.modules.catalogue import service as catalogue
from app.modules.catalogue.media import MediaAttach, MediaDelete, MediaUpdate, MediaVersion
from app.modules.catalogue.models import ProductMedia
from app.modules.catalogue.schemas import CompletenessRule, ProductFilters
from app.platform.authz.permissions import Scope
from app.platform.files import service as files
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.catalogue.world import World, build_personas, upload_file
from tests.unit.files.test_sniff import PDF, image_bytes

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("media_storage")]

PRIYA, MEERA, SAHIL = keys.USERS.PRIYA, keys.USERS.MEERA, keys.USERS.SAHIL
PNG_A = image_bytes("PNG", (8, 6))
PNG_B = image_bytes("PNG", (9, 6))
PNG_C = image_bytes("PNG", (10, 6))


def _attach(  # type: ignore[no-untyped-def]
    world: World, who: str, product: str, data: bytes, name: str, media_type: str = "image", purpose: str = "", **kw: object
):
    actor = world.actor(who)
    file_id = upload_file(actor, data, name, purpose or ("document" if media_type == "document" else "image"))
    with UnitOfWork(actor) as uow:
        return media.attach_media(uow, world.ref(product), MediaAttach(file_id=file_id, media_type=media_type, **kw))  # type: ignore[arg-type]


def test_upload_sniffs_dedupes_and_single_primary(world: World) -> None:
    first = _attach(world, PRIYA, "OAK_TRAY", PNG_A, "front.png", alt_text="Front")
    assert first.is_primary and first.content_type == "image/png" and first.file_name == "front.png"
    second = _attach(world, PRIYA, "OAK_TRAY", PNG_B, "back.png")
    assert not second.is_primary  # the first stored image stays primary
    with pytest.raises(Conflict) as dup:  # the same bytes on the same product
        _attach(world, PRIYA, "OAK_TRAY", PNG_A, "front-again.png")
    assert dup.value.code == "media_duplicate"
    with pytest.raises(ValidationFailed):  # a PDF is not an image
        _attach(world, PRIYA, "OAK_TRAY", PDF, "spec.pdf", media_type="image", purpose="document")
    with UnitOfWork(world.actor(PRIYA)) as uow:
        made = media.make_primary(uow, second.id, MediaVersion(expected_version=second.version))
    groups = media.list_media(world.actor(PRIYA), world.ref("OAK_TRAY"))
    assert made.is_primary and [m.id for m in groups.image if m.is_primary] == [second.id]
    with pytest.raises(IntegrityError), UnitOfWork(world.actor(PRIYA)) as uow:  # the partial unique index
        uow.session.query(ProductMedia).filter(ProductMedia.id == first.id).update({"is_primary": True})
        uow.flush()
    detail = catalogue.get_product(world.actor(MEERA), world.ref("OAK_TRAY"))
    assert detail.primary_image is not None and detail.primary_image.media_id == second.id
    assert detail.media_count == 2


def test_list_grouped_by_type(world: World) -> None:
    _attach(world, PRIYA, "OAK_TRAY", PNG_A, "front.png")
    _attach(world, PRIYA, "OAK_TRAY", PNG_B, "carton.png", media_type="packaging_photo")
    _attach(world, PRIYA, "OAK_TRAY", PDF, "spec.pdf", media_type="document")
    groups = media.list_media(world.actor(MEERA), world.ref("OAK_TRAY"))
    assert [m.file_name for m in groups.image] == ["front.png"]
    assert [m.file_name for m in groups.packaging_photo] == ["carton.png"]
    assert [m.file_name for m in groups.document] == ["spec.pdf"]
    assert groups.document[0].previewable and groups.document[0].content_url
    assert all(not m.capabilities["delete"].allowed for m in groups.image)  # sales cannot manage media


def test_media_fields_round_trip(world: World) -> None:
    item = _attach(world, PRIYA, "OAK_TRAY", PNG_A, "front.png", alt_text="Front view", source_catalog_page="p. 12")
    with UnitOfWork(world.actor(PRIYA)) as uow:
        updated = media.update_media(
            uow, item.id, MediaUpdate(expected_version=item.version, alt_text="Front, oiled", sort_order=5)
        )
    assert updated.alt_text == "Front, oiled" and updated.sort_order == 5
    assert updated.media_type.value == "image" and updated.size_bytes == len(PNG_A)
    assert updated.uploaded_by_name and updated.uploaded_at and updated.source_kind == "upload"
    with pytest.raises(VersionConflict), UnitOfWork(world.actor(PRIYA)) as uow:
        media.update_media(uow, item.id, MediaUpdate(expected_version=item.version, alt_text="x"))


def test_soft_delete_restore_and_primary_promotion(world: World) -> None:
    first = _attach(world, PRIYA, "OAK_TRAY", PNG_A, "front.png")
    second = _attach(world, PRIYA, "OAK_TRAY", PNG_B, "back.png")
    with UnitOfWork(world.actor(PRIYA)) as uow:
        deleted = media.delete_media(uow, first.id, MediaDelete(expected_version=first.version, reason="blurred"))
    assert deleted.deleted_at is not None and deleted.delete_reason == "blurred" and not deleted.is_primary
    groups = media.list_media(world.actor(PRIYA), world.ref("OAK_TRAY"), include_deleted=True)
    assert [m.id for m in groups.image if m.is_primary] == [second.id]  # the next image was promoted
    assert [m.id for m in groups.deleted] == [first.id]
    with UnitOfWork(world.actor(PRIYA)) as uow:  # the stored object is kept
        assert files.get_readable(uow, first.file_id) is not None  # type: ignore[arg-type]
    with UnitOfWork(world.actor(PRIYA)) as uow:
        restored = media.restore_media(uow, first.id, MediaVersion(expected_version=deleted.version))
    assert restored.deleted_at is None and not restored.is_primary
    with pytest.raises(Conflict), UnitOfWork(world.actor(PRIYA)) as uow:
        media.restore_media(uow, first.id, MediaVersion(expected_version=restored.version))


def test_own_scope_cannot_delete_others_uploads(world: World) -> None:
    item = _attach(world, PRIYA, "OAK_TRAY", PNG_A, "front.png")
    base = world.actor(MEERA)
    own_scope = base.with_(
        permissions=MappingProxyType({**base.permissions, "catalogue.media.manage": Scope.OWN, "files.file.create": Scope.COMPANY})
    )
    with pytest.raises(Forbidden) as exc, UnitOfWork(own_scope) as uow:
        media.delete_media(uow, item.id, MediaDelete(expected_version=item.version, reason="mine?"))
    assert exc.value.code == "not_owner"
    file_id = upload_file(own_scope, PNG_C, "own.png")
    with UnitOfWork(own_scope) as uow:
        own = media.attach_media(uow, world.ref("OAK_TRAY"), MediaAttach(file_id=file_id, media_type="image"))  # type: ignore[arg-type]
    with UnitOfWork(own_scope) as uow:
        gone = media.delete_media(uow, own.id, MediaDelete(expected_version=own.version, reason="duplicate"))
    assert gone.deleted_at is not None
    with pytest.raises(Forbidden), UnitOfWork(world.actor(SAHIL)) as uow:  # no media key at all
        media.make_primary(uow, item.id, MediaVersion(expected_version=item.version))


def test_downloads_follow_product_visibility(world: World) -> None:
    item = _attach(world, PRIYA, "OAK_TRAY", PNG_A, "front.png")
    with UnitOfWork(world.actor(MEERA)) as uow:  # any product reader may download the linked file
        assert files.get_readable(uow, item.file_id).id == item.file_id  # type: ignore[arg-type]
    other = build_personas()
    with pytest.raises(NotFound), UnitOfWork(other.actor(PRIYA)) as uow:  # another company: 404
        files.get_readable(uow, item.file_id)  # type: ignore[arg-type]
    with pytest.raises(NotFound):
        media.list_media(other.actor(PRIYA), world.ref("OAK_TRAY"))


def test_media_completeness_rules_and_has_image_filter(world: World) -> None:
    summary = {r.code: r.count for r in catalogue.completeness_summary(world.actor(PRIYA)).rules}
    before = summary[CompletenessRule.NO_PRIMARY_IMAGE]
    _attach(world, PRIYA, "OAK_TRAY", PNG_A, "front.png")
    after = {r.code: r.count for r in catalogue.completeness_summary(world.actor(PRIYA)).rules}
    assert after[CompletenessRule.NO_PRIMARY_IMAGE] == before - 1
    assert after[CompletenessRule.NO_IMAGE] == before - 1
    with_image = catalogue.list_products(world.actor(PRIYA), ProductFilters(has_image=True))
    assert [p.id for p in with_image.items] == [world.ref("OAK_TRAY")] and with_image.total == 1
    assert with_image.items[0].primary_image is not None
    without = catalogue.list_products(world.actor(PRIYA), ProductFilters(has_image=False))
    assert world.ref("OAK_TRAY") not in {p.id for p in without.items}
