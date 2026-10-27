/**
 * Field-level three-way merge for 409 `version_conflict` (frontend_verification §11).
 *
 * Inputs: `base` (the version the user started from), `mine` (the user's dirty fields only)
 * and `theirs` (the `current` representation from the 409). Rules:
 * - changed only by them: adopted, and reported so the UI can say so;
 * - changed only by me: kept;
 * - changed by both to the same value: not a conflict;
 * - changed by both to different values: a conflict the user resolves (mine, theirs or edit).
 * Nothing is overwritten silently, and the result always needs an explicit save against
 * `current_version`.
 */

export type FieldValue = unknown;
export type Fields = Readonly<Record<string, FieldValue>>;

export interface FieldConflict {
  field: string;
  base: FieldValue;
  mine: FieldValue;
  theirs: FieldValue;
}

export interface MergeResult {
  /** Fields to show in the form after the merge (theirs + kept edits; conflicts keep mine until resolved). */
  merged: Record<string, FieldValue>;
  /** The edits to send on the next save: my changes plus resolved conflicts. */
  dirty: Record<string, FieldValue>;
  /** Fields changed by someone else and adopted. */
  adopted: string[];
  conflicts: FieldConflict[];
}

/** Structural equality for JSON-like field values (strings for money, arrays, plain objects). */
export function sameValue(a: FieldValue, b: FieldValue): boolean {
  if (Object.is(a, b)) return true;
  if (typeof a !== "object" || typeof b !== "object" || a === null || b === null) return false;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((item, index) => sameValue(item, b[index]));
  }
  const ka = Object.keys(a as object).sort();
  const kb = Object.keys(b as object).sort();
  return (
    ka.length === kb.length &&
    ka.every((key, index) => key === kb[index] && sameValue((a as Record<string, unknown>)[key], (b as Record<string, unknown>)[key]))
  );
}

export function threeWayMerge(base: Fields, mine: Fields, theirs: Fields): MergeResult {
  const merged: Record<string, FieldValue> = { ...theirs };
  const dirty: Record<string, FieldValue> = {};
  const adopted: string[] = [];
  const conflicts: FieldConflict[] = [];

  const fields = new Set([...Object.keys(base), ...Object.keys(theirs)]);
  for (const field of Object.keys(mine)) fields.add(field);

  for (const field of [...fields].sort()) {
    const iChanged = Object.prototype.hasOwnProperty.call(mine, field) && !sameValue(mine[field], base[field]);
    const theyChanged = !sameValue(theirs[field], base[field]);

    if (iChanged && theyChanged) {
      if (sameValue(mine[field], theirs[field])) continue; // converged: nothing to send
      conflicts.push({ field, base: base[field], mine: mine[field], theirs: theirs[field] });
      merged[field] = mine[field];
      dirty[field] = mine[field];
    } else if (iChanged) {
      merged[field] = mine[field];
      dirty[field] = mine[field];
    } else if (theyChanged) {
      adopted.push(field);
    }
  }
  return { merged, dirty, adopted, conflicts };
}

/** Applies the user's choice for each conflict; unresolved conflicts keep the user's value. */
export function resolveConflicts(
  result: MergeResult,
  choices: Readonly<Record<string, { use: "mine" } | { use: "theirs" } | { use: "value"; value: FieldValue }>>,
): MergeResult {
  const merged = { ...result.merged };
  const dirty = { ...result.dirty };
  const remaining: FieldConflict[] = [];
  for (const conflict of result.conflicts) {
    const choice = choices[conflict.field];
    if (!choice) {
      remaining.push(conflict);
      continue;
    }
    if (choice.use === "theirs") {
      merged[conflict.field] = conflict.theirs;
      delete dirty[conflict.field];
    } else {
      const value = choice.use === "mine" ? conflict.mine : choice.value;
      merged[conflict.field] = value;
      dirty[conflict.field] = value;
    }
  }
  return { merged, dirty, adopted: result.adopted, conflicts: remaining };
}
