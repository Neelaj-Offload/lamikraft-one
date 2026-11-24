"use client";

import { useMutation } from "@tanstack/react-query";
import type { Route } from "next";
import { useState } from "react";
import { createCategory, deleteTaxonomy, fieldErrors, updateTaxonomy } from "@/features/catalogue/api";
import type { TaxonomyReferences } from "@/features/catalogue/types";
import { conflictFromError, ProblemError } from "@/lib/api/errors";
import { formatCount } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { PRODUCTS_READ, TAXONOMY_MANAGE, useCatalogueRefresh, useCategories, useReorderTaxonomy, useTaxonomyReferences, type CategoryRead, type SubcategoryRead } from "~/data/products";
import { Page, PageHeader, Split } from "~/shell/page";
import { ErrorBlock, NotPermitted, QueryView } from "~/shell/states";
import {
  Badge,
  Banner,
  Button,
  EmptyState,
  GlassPanel,
  IconButton,
  IntegerField,
  KeyValue,
  Menu,
  Modal,
  Select,
  SkeletonRows,
  SkeletonText,
  Switch,
  Textarea,
  TextField,
  TextLink,
  toast,
  type MenuItem,
} from "~/ui";
import { riseStyle } from "./motion";

/**
 * How the catalogue is organised: categories in catalogue order, each with its subcategories and
 * the number of products inside. People with the right role can add, rename, reorder, switch off
 * and delete; a delete first shows what still points at the entry and moves it somewhere safe.
 */

type Target = { kind: "category"; row: CategoryRead } | { kind: "subcategory"; row: SubcategoryRead; parent: CategoryRead };
type Editing = { mode: "create"; parent: CategoryRead | null } | { mode: "edit"; target: Target };

const NONE = "none";

/** Moves an id one place up or down; the reorder call sends the whole order. */
function moved(ids: readonly string[], id: string, delta: -1 | 1): string[] {
  const index = ids.indexOf(id);
  const to = index + delta;
  if (index < 0 || to < 0 || to >= ids.length) return [...ids];
  const out = [...ids];
  [out[index], out[to]] = [out[to]!, out[index]!];
  return out;
}

/** Whether a delete must first move what still points at the entry, and whether it can at all. */
function deletePlan(refs: TaxonomyReferences): { blocked: boolean; needsTarget: boolean; counts: Record<string, number> } {
  return {
    blocked: refs.references.some((reference) => !reference.reassignable),
    needsTarget: refs.total > 0,
    counts: Object.fromEntries(refs.references.map((reference) => [reference.table, reference.count])),
  };
}

function productsHref(categoryId: string, subcategoryId?: string): Route {
  const query = new URLSearchParams({ category_id: categoryId });
  if (subcategoryId) query.set("subcategory_id", subcategoryId);
  return `/products?${query.toString()}` as Route;
}

function EditDialog({ editing, onClose }: { editing: Editing; onClose: () => void }) {
  const refresh = useCatalogueRefresh();
  const initial = editing.mode === "edit" ? editing.target.row : null;
  const [name, setName] = useState(initial?.name ?? "");
  const [order, setOrder] = useState<number | null>(initial?.display_order ?? 0);
  const [active, setActive] = useState(initial?.is_active ?? true);
  const [description, setDescription] = useState(initial?.description ?? "");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [conflict, setConflict] = useState(false);

  const save = useMutation({
    mutationFn: () => {
      const body = { name: name.trim(), display_order: order ?? 0, is_active: active, description: description.trim() || null };
      if (editing.mode === "create") return createCategory(body, editing.parent?.id ?? null);
      const target = editing.target;
      return updateTaxonomy(target.kind, target.row.id, { ...body, expected_version: target.row.version });
    },
    onSuccess: () => {
      refresh();
      toast.success(editing.mode === "create" ? `${name.trim()} added` : `${name.trim()} saved`);
      onClose();
    },
    onError: (error) => {
      const fields = fieldErrors(error);
      if (error instanceof ProblemError && ["category_exists", "subcategory_exists", "name_taken"].includes(error.code)) {
        fields.name = "This name is in use here, or was used before. Choose a different name.";
      }
      setErrors(fields);
      setConflict(conflictFromError(error) !== null && !fields.name);
      if (Object.keys(fields).length === 0 && conflictFromError(error) === null) {
        toast.error("That did not save", { description: error instanceof ProblemError ? (error.detail ?? error.title) : "Check your connection, then try again." });
      }
    },
  });

  const submit = () => {
    if (!name.trim()) {
      setErrors({ name: "Give it a name." });
      return;
    }
    save.mutate();
  };
  const title =
    editing.mode === "create" ? (editing.parent ? `Add a subcategory to ${editing.parent.name}` : "Add a category") : `Edit ${editing.target.row.name}`;

  return (
    <Modal
      isOpen
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={title}
      description={editing.mode === "edit" ? "A rename keeps the old name as an alias, so imports that still use it land in the right place." : undefined}
      actions={
        <>
          <Button variant="ghost" onPress={onClose} isDisabled={save.isPending}>
            Cancel
          </Button>
          <Button onPress={submit} loading={save.isPending}>
            {editing.mode === "create" ? (editing.parent ? "Add subcategory" : "Add category") : "Save changes"}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-5">
        {conflict ? (
          <Banner tone="amber" title="Someone else changed this while you were editing.">
            Close this, check the latest version, then make your change again.
          </Banner>
        ) : null}
        <TextField
          label="Name"
          isRequired
          autoFocus
          value={name}
          onChange={(value) => {
            setName(value);
            setErrors((current) => ({ ...current, name: "" }));
          }}
          error={errors.name || undefined}
        />
        <IntegerField label="Position in the catalogue" value={order} onChange={setOrder} minValue={0} help="Lower numbers come first." error={errors.display_order || undefined} />
        <Textarea label="Description" optional rows={2} value={description} onChange={setDescription} error={errors.description || undefined} />
        <Switch label="Active" description="Switched off, it is hidden from pickers. Products already in it stay there." isSelected={active} onChange={setActive} />
      </div>
    </Modal>
  );
}

function DeleteDialog({ target, categories, onClose }: { target: Target; categories: readonly CategoryRead[]; onClose: () => void }) {
  const refresh = useCatalogueRefresh();
  const refs = useTaxonomyReferences(target.kind, target.row.id);
  const [categoryId, setCategoryId] = useState<string | null>(target.kind === "subcategory" ? target.parent.id : null);
  const [subcategoryId, setSubcategoryId] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const plan = refs.data ? deletePlan(refs.data) : null;

  const remove = useMutation({
    mutationFn: () =>
      deleteTaxonomy(target.kind, target.row.id, {
        expected_version: target.row.version,
        ...(plan?.needsTarget ? { reassign_to: { category_id: categoryId, subcategory_id: subcategoryId }, expected_reference_counts: plan.counts } : {}),
      }),
    onSuccess: () => {
      refresh();
      toast.success(`${target.row.name} deleted`);
      onClose();
    },
    onError: (error) => setProblem(error instanceof ProblemError ? (error.detail ?? error.title) : "Check your connection, then try again."),
  });

  const targets = categories.filter((category) => category.is_active && (target.kind === "subcategory" || category.id !== target.row.id));
  const subs = categories.find((category) => category.id === categoryId)?.subcategories.filter((sub) => sub.effective_active && sub.id !== target.row.id) ?? [];
  const blocked = !plan || plan.blocked || (plan.needsTarget && !categoryId);
  const kindWord = target.kind === "category" ? "category" : "subcategory";

  return (
    <Modal
      isOpen
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={`Delete ${target.row.name}`}
      description={`This removes the ${kindWord} for good. Switch it off instead if you only want it out of pickers.`}
      actions={
        <>
          <Button variant="ghost" onPress={onClose} isDisabled={remove.isPending}>
            Keep it
          </Button>
          <Button variant="danger" onPress={() => remove.mutate()} loading={remove.isPending} isDisabled={blocked}>
            {plan?.needsTarget ? `Move and delete ${kindWord}` : `Delete ${kindWord}`}
          </Button>
        </>
      }
    >
      {refs.isPending ? (
        <SkeletonText lines={3} />
      ) : refs.isError || !refs.data ? (
        <ErrorBlock error={refs.error} what="What still uses it" onRetry={() => void refs.refetch()} />
      ) : (
        <div className="flex flex-col gap-5">
          {problem ? (
            <Banner tone="ember" title="It was not deleted.">
              {problem}
            </Banner>
          ) : null}
          {refs.data.total > 0 ? (
            <>
              <div className="flex flex-col gap-2">
                <p className="t-label m-0 text-ink">Still in use by</p>
                <KeyValue
                  rows
                  items={refs.data.references.map((reference) => ({
                    label: reference.reassignable ? reference.label : `${reference.label} (move or delete these yourself first)`,
                    value: <span className="lk-tnum">{reference.count}</span>,
                  }))}
                />
              </div>
              {plan?.blocked ? (
                <Banner tone="amber" title="Some of these cannot be moved for you.">
                  Move or delete them yourself, then come back to delete this {kindWord}.
                </Banner>
              ) : (
                <>
                  <Select
                    label="Move them to"
                    isRequired
                    placeholder="Choose a category"
                    options={targets.map((category) => ({ value: category.id, label: category.name }))}
                    value={categoryId}
                    onChange={(value) => {
                      setCategoryId(value);
                      setSubcategoryId(null);
                    }}
                  />
                  <Select
                    label="Subcategory"
                    optional
                    options={[{ value: NONE, label: "No subcategory" }, ...subs.map((sub) => ({ value: sub.id, label: sub.name }))]}
                    value={subcategoryId ?? NONE}
                    onChange={(value) => setSubcategoryId(value === NONE ? null : value)}
                    isDisabled={!categoryId}
                  />
                </>
              )}
            </>
          ) : (
            <p className="t-body m-0 text-ink-2">Nothing uses it. It can be deleted safely.</p>
          )}
          {refs.data.aliases.length > 0 ? <p className="t-caption m-0 text-ink-3">Earlier names: {refs.data.aliases.join(", ")}</p> : null}
        </div>
      )}
    </Modal>
  );
}

function pageRange(category: CategoryRead): string | null {
  const start = category.source_catalog_page_start;
  const end = category.source_catalog_page_end;
  if (!start) return null;
  return end && end !== start ? `Catalogue pages ${start} to ${end}` : `Catalogue page ${start}`;
}

function CategoryPanel({
  category,
  index,
  count,
  canManage,
  reordering,
  onMove,
  onEdit,
  onAdd,
  onDelete,
  onEditSub,
  onDeleteSub,
}: {
  category: CategoryRead;
  index: number;
  count: number;
  canManage: boolean;
  reordering: boolean;
  onMove: (delta: -1 | 1) => void;
  onEdit: () => void;
  onAdd: () => void;
  onDelete: () => void;
  onEditSub: (sub: SubcategoryRead) => void;
  onDeleteSub: (sub: SubcategoryRead) => void;
}) {
  const { zone } = useSession();
  const actions: MenuItem[] = [
    { id: "edit", label: "Edit category", icon: "edit", onAction: onEdit },
    { id: "add", label: "Add a subcategory", icon: "plus", onAction: onAdd },
    { id: "sep", separator: true },
    { id: "delete", label: "Delete category", icon: "trash", tone: "danger", onAction: onDelete },
  ];
  const pages = pageRange(category);
  return (
    <GlassPanel as="li" padding="none" className="rise-plain" style={riseStyle(index)}>
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3 px-5 py-5 md:px-6">
        <div className="flex min-w-0 items-start gap-4">
          <span className="t-label lk-tnum flex size-9 flex-none items-center justify-center rounded-pill bg-sand-soft text-ink-2" aria-hidden="true">
            {index + 1}
          </span>
          <div className="flex min-w-0 flex-col gap-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="t-h3 m-0">{category.name}</h2>
              {category.is_active ? null : (
                <Badge size="sm" icon="eyeOff">
                  Switched off
                </Badge>
              )}
            </div>
            <p className="t-body-sm m-0 text-ink-2">
              <TextLink href={productsHref(category.id)}>
                {formatCount(category.product_count, zone.locale)} {category.product_count === 1 ? "product" : "products"}
              </TextLink>
              {pages ? ` · ${pages}` : ""}
            </p>
            {category.description ? <p className="t-body-sm m-0 max-w-[60ch] text-ink-3">{category.description}</p> : null}
          </div>
        </div>
        {canManage ? (
          <div className="flex flex-none items-center gap-1">
            <IconButton icon="chevronUp" label={`Move ${category.name} up`} variant="ghost" size="sm" isDisabled={index === 0 || reordering} onPress={() => onMove(-1)} />
            <IconButton icon="chevronDown" label={`Move ${category.name} down`} variant="ghost" size="sm" isDisabled={index === count - 1 || reordering} onPress={() => onMove(1)} />
            <Menu label={`Actions for ${category.name}`} items={actions} placement="bottom end" trigger={<IconButton icon="more" label={`Actions for ${category.name}`} variant="ghost" size="sm" />} />
          </div>
        ) : null}
      </div>
      {category.subcategories.length > 0 ? (
        <ul className="hairline-top m-0 list-none p-0">
          {category.subcategories.map((sub) => (
            <li key={sub.id} className="hairline-top flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-3 pl-[4.25rem] pr-5 first:border-t-0 md:pl-[4.75rem] md:pr-6">
              <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
                <span className="t-body text-ink">{sub.name}</span>
                {sub.effective_active ? null : (
                  <Badge size="sm" icon="eyeOff">
                    {sub.is_active ? "Hidden with its category" : "Switched off"}
                  </Badge>
                )}
                {sub.description ? <span className="t-body-sm text-ink-3">{sub.description}</span> : null}
              </div>
              <div className="flex flex-none items-center gap-3">
                <TextLink href={productsHref(category.id, sub.id)} className="t-body-sm lk-tnum">
                  {formatCount(sub.product_count, zone.locale)} {sub.product_count === 1 ? "product" : "products"}
                </TextLink>
                {canManage ? (
                  <Menu
                    label={`Actions for ${sub.name}`}
                    placement="bottom end"
                    items={[
                      { id: "edit", label: "Edit subcategory", icon: "edit", onAction: () => onEditSub(sub) },
                      { id: "sep", separator: true },
                      { id: "delete", label: "Delete subcategory", icon: "trash", tone: "danger", onAction: () => onDeleteSub(sub) },
                    ]}
                    trigger={<IconButton icon="more" label={`Actions for ${sub.name}`} variant="ghost" size="sm" />}
                  />
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      ) : null}
    </GlassPanel>
  );
}

export function Taxonomy() {
  const { permissionKeys, zone } = useSession();
  const canManage = permissionKeys.has(TAXONOMY_MANAGE);
  const allowed = canManage || permissionKeys.has(PRODUCTS_READ);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [deleting, setDeleting] = useState<Target | null>(null);
  const tree = useCategories(true, allowed);
  const reorder = useReorderTaxonomy();

  const move = (ids: string[], id: string, delta: -1 | 1) =>
    reorder.mutate(
      { ids: moved(ids, id, delta), parent: null },
      { onError: () => toast.error("The new order was not saved", { description: "Check your connection, then move it again." }) },
    );

  return (
    <Page>
      <PageHeader
        breadcrumb={[{ label: "Catalogue", href: "/products" }]}
        title="Taxonomy"
        lead="How the catalogue is organised: categories in catalogue order, each with its subcategories."
        actions={
          allowed && canManage ? (
            <Button iconLeft="plus" onPress={() => setEditing({ mode: "create", parent: null })}>
              Add category
            </Button>
          ) : undefined
        }
      />
      {!allowed ? (
        <NotPermitted what="Taxonomy" icon="layers" />
      ) : (
        <QueryView
          query={tree}
          what="Taxonomy"
          loading={
            <GlassPanel padding="none">
              <SkeletonRows rows={6} columns={3} />
            </GlassPanel>
          }
          isEmpty={(categories) => categories.length === 0}
          empty={
            <GlassPanel>
              <EmptyState
                icon="layers"
                title="Add your first category"
                text="Categories are the chapters of the catalogue. Every product belongs to one."
                actions={
                  canManage ? (
                    <Button iconLeft="plus" onPress={() => setEditing({ mode: "create", parent: null })}>
                      Add category
                    </Button>
                  ) : undefined
                }
              />
            </GlassPanel>
          }
        >
          {(categories) => {
            const ids = categories.map((category) => category.id);
            const subcategories = categories.reduce((sum, category) => sum + category.subcategories.length, 0);
            const products = categories.reduce((sum, category) => sum + category.product_count, 0);
            const off = categories.filter((category) => !category.is_active).length + categories.reduce((sum, category) => sum + category.subcategories.filter((sub) => !sub.is_active).length, 0);
            return (
              <Split
                main={
                  <ol className="stack m-0 list-none p-0">
                    {categories.map((category, index) => (
                      <CategoryPanel
                        key={category.id}
                        category={category}
                        index={index}
                        count={categories.length}
                        canManage={canManage}
                        reordering={reorder.isPending}
                        onMove={(delta) => move(ids, category.id, delta)}
                        onEdit={() => setEditing({ mode: "edit", target: { kind: "category", row: category } })}
                        onAdd={() => setEditing({ mode: "create", parent: category })}
                        onDelete={() => setDeleting({ kind: "category", row: category })}
                        onEditSub={(sub) => setEditing({ mode: "edit", target: { kind: "subcategory", row: sub, parent: category } })}
                        onDeleteSub={(sub) => setDeleting({ kind: "subcategory", row: sub, parent: category })}
                      />
                    ))}
                  </ol>
                }
                aside={
                  <>
                    <GlassPanel padding="lg" title="At a glance" titleAs="h2">
                      <KeyValue
                        rows
                        items={[
                          { label: "Categories", value: <span className="lk-tnum">{formatCount(categories.length, zone.locale)}</span> },
                          { label: "Subcategories", value: <span className="lk-tnum">{formatCount(subcategories, zone.locale)}</span> },
                          { label: "Products filed", value: <span className="lk-tnum">{formatCount(products, zone.locale)}</span> },
                          { label: "Switched off", value: <span className="lk-tnum">{formatCount(off, zone.locale)}</span> },
                        ]}
                      />
                    </GlassPanel>
                    <GlassPanel variant="outline" padding="lg" title="How this works" titleAs="h2">
                      <ul className="t-body-sm m-0 flex list-none flex-col gap-3 p-0 text-ink-2">
                        <li>The order here is the order of the catalogue and of every category picker.</li>
                        <li>A rename keeps the old name as an alias, so imports that still use it land in the right place.</li>
                        <li>Switching an entry off hides it from pickers. Products already filed in it stay where they are.</li>
                        <li>A delete first shows what still uses the entry and moves it to the place you choose.</li>
                      </ul>
                    </GlassPanel>
                  </>
                }
              />
            );
          }}
        </QueryView>
      )}
      {editing ? <EditDialog key={editing.mode === "edit" ? editing.target.row.id : `new-${editing.parent?.id ?? "root"}`} editing={editing} onClose={() => setEditing(null)} /> : null}
      {deleting && tree.data ? <DeleteDialog key={deleting.row.id} target={deleting} categories={tree.data} onClose={() => setDeleting(null)} /> : null}
    </Page>
  );
}
