"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { StatusPill } from "@/components/ui/badge";
import { PageHeader } from "@/components/ui/page-header";
import { Button, unavailableWhen } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/choice";
import { Dialog } from "@/components/ui/dialog";
import { Select } from "@/components/ui/select";
import { EmptyState, ErrorState, Loading, PermissionDenied } from "@/components/ui/states";
import { TextArea, TextField } from "@/components/ui/text-field";
import { toast } from "@/components/ui/toast";
import { ProblemError, conflictFromError } from "@/lib/api/errors";
import { invalidationMap, queryKeys } from "@/lib/api/query-keys";
import { useSession } from "@/lib/session/context";
import { productsAreaNav } from "@/features/products/product-list";
import { createCategory, deleteTaxonomy, fetchCategories, fetchReferences, fieldErrors, reorderTaxonomy, updateTaxonomy } from "./api";
import type { CategoryRead, SubcategoryRead, TaxonomyReferences } from "./types";

type Target = { kind: "category"; row: CategoryRead } | { kind: "subcategory"; row: SubcategoryRead; parent: CategoryRead };
type Editing = { mode: "create"; parent: CategoryRead | null } | { mode: "edit"; target: Target };

/** Moves an id one place up or down (the reorder call sends the whole order). */
export function moved(ids: readonly string[], id: string, delta: -1 | 1): string[] {
  const index = ids.indexOf(id);
  const to = index + delta;
  if (index < 0 || to < 0 || to >= ids.length) return [...ids];
  const out = [...ids];
  [out[index], out[to]] = [out[to]!, out[index]!];
  return out;
}

/** Whether the delete dialog must ask for a reassignment target and confirm the counts (BUG-16, LM-42). */
export function deletePlan(refs: TaxonomyReferences): { blocked: boolean; needsTarget: boolean; counts: Record<string, number> } {
  const counts = Object.fromEntries(refs.references.map((r) => [r.table, r.count]));
  return {
    blocked: refs.references.some((r) => !r.reassignable),
    needsTarget: refs.total > 0,
    counts,
  };
}

function EditDialog({ editing, onClose, onSaved, version }: { editing: Editing; onClose: () => void; onSaved: () => void; version: (t: Target) => number }) {
  const initial = editing.mode === "edit" ? editing.target.row : null;
  const [name, setName] = useState(initial?.name ?? "");
  const [order, setOrder] = useState(String(initial?.display_order ?? 0));
  const [active, setActive] = useState(initial?.is_active ?? true);
  const [description, setDescription] = useState(initial?.description ?? "");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useMutation({
    mutationFn: () => {
      const body = { name: name.trim(), display_order: Number.parseInt(order || "0", 10) || 0, is_active: active, description: description.trim() || null };
      if (editing.mode === "create") return createCategory(body, editing.parent?.id ?? null);
      const t = editing.target;
      return updateTaxonomy(t.kind, t.row.id, { ...body, expected_version: version(t) });
    },
    onSuccess: () => {
      onSaved();
      onClose();
    },
    onError: (error) => {
      const fields = fieldErrors(error);
      if (error instanceof ProblemError && ["category_exists", "subcategory_exists", "name_taken"].includes(error.code)) {
        fields.name = "This name is already used (or was used before) here";
      }
      setErrors(fields);
      if (conflictFromError(error) && !fields.name) toast.error("Changed by someone else; reload and try again");
    },
  });
  const title =
    editing.mode === "create" ? (editing.parent ? `New subcategory in ${editing.parent.name}` : "New category") : `Edit ${editing.target.row.name}`;
  return (
    <Dialog
      title={title}
      description={editing.mode === "edit" ? "Renaming keeps the old name as an alias for imports." : undefined}
      isOpen
      onOpenChange={(open) => (open ? undefined : onClose())}
      footer={(close) => (
        <>
          <Button onPress={close}>Cancel</Button>
          <Button variant="primary" onPress={() => save.mutate()} isPending={save.isPending} {...unavailableWhen((!name.trim()) ? "Enter a name" : null)}>
            Save
          </Button>
        </>
      )}
    >
      <div className="flex flex-col gap-4">
        <TextField label="Name" isRequired value={name} onChange={setName} isInvalid={Boolean(errors.name)} errorMessage={errors.name} />
        <TextField label="Display order" inputMode="numeric" value={order} onChange={setOrder} isInvalid={Boolean(errors.display_order)} errorMessage={errors.display_order} />
        <TextArea label="Description" value={description} onChange={setDescription} />
        <Checkbox isSelected={active} onChange={setActive}>
          Active (inactive entries are hidden from pickers; products keep them)
        </Checkbox>
      </div>
    </Dialog>
  );
}

function DeleteDialog({ target, categories, onClose, onDone, version }: { target: Target; categories: readonly CategoryRead[]; onClose: () => void; onDone: () => void; version: (t: Target) => number }) {
  const refs = useQuery({ queryKey: queryKeys.catalogue.references(target.kind, target.row.id), queryFn: () => fetchReferences(target.kind, target.row.id) });
  const [categoryId, setCategoryId] = useState<string | null>(target.kind === "subcategory" ? target.parent.id : null);
  const [subcategoryId, setSubcategoryId] = useState<string | null>(null);
  const remove = useMutation({
    mutationFn: () => {
      const plan = refs.data ? deletePlan(refs.data) : null;
      return deleteTaxonomy(target.kind, target.row.id, {
        expected_version: version(target),
        ...(plan?.needsTarget
          ? { reassign_to: { category_id: categoryId, subcategory_id: subcategoryId }, expected_reference_counts: plan.counts }
          : {}),
      });
    },
    onSuccess: () => {
      toast.success(`${target.row.name} deleted`);
      onDone();
      onClose();
    },
    onError: (error) => toast.error(error instanceof ProblemError ? error.detail ?? error.title : "Not deleted"),
  });
  const plan = refs.data ? deletePlan(refs.data) : null;
  const targets = categories.filter((c) => c.is_active && (target.kind === "subcategory" || c.id !== target.row.id));
  const subs = categories.find((c) => c.id === categoryId)?.subcategories.filter((s) => s.effective_active && s.id !== target.row.id) ?? [];
  return (
    <Dialog
      role="alertdialog"
      title={`Delete ${target.row.name}`}
      isOpen
      onOpenChange={(open) => (open ? undefined : onClose())}
      footer={(close) => (
        <>
          <Button onPress={close}>Cancel</Button>
          <Button
            variant="danger"
            onPress={() => remove.mutate()}
            isPending={remove.isPending}
            {...unavailableWhen((!plan || plan.blocked || (plan.needsTarget && !categoryId)) ? plan?.blocked ? "Some references cannot be moved automatically" : "Choose where the products go" : null)}
          >
            {plan?.needsTarget ? "Reassign and delete" : "Delete"}
          </Button>
        </>
      )}
    >
      {refs.isPending ? (
        <Loading label="references" />
      ) : refs.isError ? (
        <ErrorState error={refs.error} what="the references" compact backToToday={false} />
      ) : (
        <div className="flex flex-col gap-4 text-sm">
          {refs.data.total ? (
            <>
              <p>Still referenced by:</p>
              <ul className="list-disc ps-5">
                {refs.data.references.map((r) => (
                  <li key={r.table}>
                    {r.label}: <span className="tabular">{r.count}</span>
                    {r.reassignable ? "" : " (delete or move these first)"}
                  </li>
                ))}
              </ul>
              {!plan?.blocked ? (
                <>
                  <Select label="Move them to category" options={targets.map((c) => ({ id: c.id, label: c.name }))} value={categoryId} onChange={(v) => { setCategoryId(v); setSubcategoryId(null); }} />
                  <Select label="Subcategory" options={[{ id: "", label: "None" }, ...subs.map((s) => ({ id: s.id, label: s.name }))]} value={subcategoryId ?? ""} onChange={(v) => setSubcategoryId(v || null)} />
                </>
              ) : null}
            </>
          ) : (
            <p>Nothing references it. It can be deleted.</p>
          )}
          {refs.data.aliases.length ? <p className="text-ink-muted">Former names: {refs.data.aliases.join(", ")}</p> : null}
        </div>
      )}
    </Dialog>
  );
}

/** Taxonomy management (LM-40..42, UI-20/93): order, activation, safe rename, delete-or-reassign. */
export function TaxonomyManager() {
  const queryClient = useQueryClient();
  const { permissionKeys } = useSession();
  const [editing, setEditing] = useState<Editing | null>(null);
  const [deleting, setDeleting] = useState<Target | null>(null);
  const tree = useQuery({ queryKey: queryKeys.catalogue.categories(true), queryFn: ({ signal }) => fetchCategories(true, signal) });
  const refresh = () => {
    for (const key of invalidationMap["catalogue.changed"]) void queryClient.invalidateQueries({ queryKey: key });
  };
  const reorder = useMutation({
    mutationFn: ({ ids, parent }: { ids: string[]; parent: string | null }) => reorderTaxonomy(ids, parent),
    onSuccess: refresh,
    onError: () => toast.error("The order was not saved"),
  });
  const version = (t: Target) => t.row.version;
  const canManage = permissionKeys.has("catalogue.taxonomy.manage");
  if (!canManage && !permissionKeys.has("catalogue.product.read")) return <PermissionDenied area="taxonomy" />;
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Taxonomy"
        intro="Categories and subcategories in catalogue order; a rename keeps the old name as an alias."
        nav={productsAreaNav("products-taxonomy")}
        actions={
          canManage ? (
            <Button variant="primary" onPress={() => setEditing({ mode: "create", parent: null })}>
              New category
            </Button>
          ) : undefined
        }
      />
      {tree.isPending ? (
        <Loading label="taxonomy" />
      ) : tree.isError ? (
        <ErrorState error={tree.error} what="the taxonomy" onRetry={() => void tree.refetch()} />
      ) : !tree.data.length ? (
        <EmptyState title="No categories yet">Create one or import the category taxonomy.</EmptyState>
      ) : (
        <ol className="flex flex-col gap-3">
          {tree.data.map((cat) => {
            const ids = tree.data.map((c) => c.id);
            const target: Target = { kind: "category", row: cat };
            return (
              <li key={cat.id} className="rounded-md border">
                <div className="flex flex-wrap items-center gap-2 border-b px-4 py-3">
                  <span className="font-semibold">{cat.name}</span>
                  {cat.is_active ? null : <StatusPill tone="neutral">Inactive</StatusPill>}
                  <span className="text-sm text-ink-muted tabular">{cat.product_count} products</span>
                  {canManage ? (
                  <div className="ms-auto flex flex-wrap gap-1">
                      <Button size="sm" variant="quiet" onPress={() => reorder.mutate({ ids: moved(ids, cat.id, -1), parent: null })} aria-label={`Move ${cat.name} up`}>
                        Up
                      </Button>
                      <Button size="sm" variant="quiet" onPress={() => reorder.mutate({ ids: moved(ids, cat.id, 1), parent: null })} aria-label={`Move ${cat.name} down`}>
                        Down
                      </Button>
                      <Button size="sm" onPress={() => setEditing({ mode: "edit", target })}>
                        Edit
                      </Button>
                      <Button size="sm" onPress={() => setEditing({ mode: "create", parent: cat })}>
                        Add subcategory
                      </Button>
                      <Button size="sm" variant="danger" onPress={() => setDeleting(target)}>
                        Delete
                      </Button>
                    </div>
                  ) : null}
                </div>
                {cat.subcategories.length ? (
                  <ul className="divide-y">
                    {cat.subcategories.map((sub) => {
                      const subTarget: Target = { kind: "subcategory", row: sub, parent: cat };
                      return (
                        <li key={sub.id} className="flex flex-wrap items-center gap-2 px-4 py-2 ps-8 text-sm">
                          <span>{sub.name}</span>
                          {sub.effective_active ? null : <StatusPill tone="neutral">{sub.is_active ? "Hidden (category inactive)" : "Inactive"}</StatusPill>}
                          <span className="text-ink-muted tabular">{sub.product_count}</span>
                          {canManage ? (
                          <div className="ms-auto flex gap-1">
                              <Button size="sm" onPress={() => setEditing({ mode: "edit", target: subTarget })}>
                                Edit
                              </Button>
                              <Button size="sm" variant="danger" onPress={() => setDeleting(subTarget)}>
                                Delete
                              </Button>
                            </div>
                          ) : null}
                        </li>
                      );
                    })}
                  </ul>
                ) : null}
              </li>
            );
          })}
        </ol>
      )}
      {editing ? <EditDialog editing={editing} onClose={() => setEditing(null)} onSaved={refresh} version={version} /> : null}
      {deleting && tree.data ? <DeleteDialog target={deleting} categories={tree.data} onClose={() => setDeleting(null)} onDone={refresh} version={version} /> : null}
    </div>
  );
}
