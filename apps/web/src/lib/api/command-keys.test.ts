import { describe, expect, it } from "vitest";
import { commandPrefix, commandSignature, createCommandKeys } from "./command-keys";
import { NetworkError, ProblemError } from "./errors";

function counter() {
  let n = 0;
  return () => `key-${++n}`;
}

const problem = (status: number, code = "x") => new ProblemError({ code, title: "t", status, detail: null, request_id: null });

describe("command Idempotency-Keys (api-conventions §6, frontend_verification §5)", () => {
  const approve = commandSignature("issue-1", "approve", 3, "fp-1");

  it("reuses the key and payload when the person retries after a network failure", () => {
    const keys = createCommandKeys(counter());
    const first = keys.attempt(approve, () => ({ until: "2026-10-12T05:00:00Z" }));
    keys.settle(approve, new NetworkError(new TypeError("offline")));
    const retry = keys.attempt(approve, () => ({ until: "2026-10-12T06:00:00Z" }));
    expect(retry.key).toBe(first.key);
    expect(retry.payload).toEqual({ until: "2026-10-12T05:00:00Z" });
  });

  it("reuses the key after a gateway error, whose outcome is unknown", () => {
    const keys = createCommandKeys(counter());
    const first = keys.attempt(approve, () => null);
    keys.settle(approve, problem(504));
    expect(keys.attempt(approve, () => null).key).toBe(first.key);
  });

  it("mints a new key after success, after a definitive answer, for a changed command, or after cancel", () => {
    const keys = createCommandKeys(counter());
    const first = keys.attempt(approve, () => null);
    keys.settle(approve);
    const afterSuccess = keys.attempt(approve, () => null);
    expect(afterSuccess.key).not.toBe(first.key);
    keys.settle(approve, problem(409, "item_changed"));
    const afterConflict = keys.attempt(approve, () => null);
    expect(afterConflict.key).not.toBe(afterSuccess.key);

    keys.settle(approve, new NetworkError(new TypeError("offline")));
    const changed = keys.attempt(commandSignature("issue-1", "approve", 4, "fp-2"), () => null);
    expect(changed.key).not.toBe(afterConflict.key);

    keys.discard(commandPrefix("issue-1", "approve"));
    expect(keys.attempt(approve, () => null).key).not.toBe(afterConflict.key);
  });

  it("discards only the commands under the prefix", () => {
    const keys = createCommandKeys(counter());
    const other = commandSignature("issue-10", "approve", 3, "fp-1");
    const a = keys.attempt(approve, () => null);
    const b = keys.attempt(other, () => null);
    keys.settle(approve, new NetworkError(new TypeError("offline")));
    keys.settle(other, new NetworkError(new TypeError("offline")));
    keys.discard(commandPrefix("issue-1", "approve"));
    expect(keys.attempt(approve, () => null).key).not.toBe(a.key);
    expect(keys.attempt(other, () => null).key).toBe(b.key);
  });
});
