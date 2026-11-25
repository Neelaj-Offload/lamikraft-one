"use client";

import { useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Dialog as RacDialog, Heading, Modal as RacModal, ModalOverlay } from "react-aria-components";
import { cx } from "@/lib/cx";
import { Button, IconButton } from "./button";
import { Icon } from "./icon";

/**
 * Overlays trap focus, close on Escape and return focus to whatever opened them (React Aria).
 * They enter over `--duration-slow` and leave faster; under 640px a modal is a bottom sheet and a
 * drawer a full-height sheet. State is controlled: the caller holds `isOpen`.
 */

interface OverlayState {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
}

interface FrameProps extends OverlayState {
  title: ReactNode;
  description?: ReactNode;
  size: "sm" | "md" | "lg";
  role: "dialog" | "alertdialog";
  isDismissable: boolean;
  /** Blocks Escape too, while a confirmation is in flight. */
  locked?: boolean;
  showClose: boolean;
  className?: string;
  /** Everything under the heading; receives `close`. */
  children: (close: () => void) => ReactNode;
}

function ModalFrame({
  isOpen,
  onOpenChange,
  title,
  description,
  size,
  role,
  isDismissable,
  locked = false,
  showClose,
  className,
  children,
}: FrameProps) {
  const descriptionId = useId();
  return (
    <ModalOverlay
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      isDismissable={isDismissable && !locked}
      isKeyboardDismissDisabled={locked}
      className="lk-overlay"
    >
      <RacModal className={cx("lk-modal", size !== "md" && `lk-modal-${size}`, className)}>
        <RacDialog role={role} aria-describedby={description ? descriptionId : undefined} className="lk-modal-dialog">
          {({ close }) => (
            <>
              {showClose ? (
                <IconButton icon="x" label="Close" variant="ghost" size="sm" className="lk-modal-close" onPress={close} />
              ) : null}
              <Heading slot="title" level={2} className="lk-modal-title">
                {title}
              </Heading>
              {description ? (
                <p id={descriptionId} className="lk-modal-desc">
                  {description}
                </p>
              ) : null}
              {children(close)}
            </>
          )}
        </RacDialog>
      </RacModal>
    </ModalOverlay>
  );
}

export interface ModalProps extends OverlayState {
  title: ReactNode;
  /** One or two sentences under the title, read out as the dialog's description. */
  description?: ReactNode;
  size?: "sm" | "md" | "lg";
  /** The action row, pinned under the scrolling body: cancel first, the main action last. */
  actions?: ReactNode;
  /** Click outside to close (default true). Escape always closes. */
  isDismissable?: boolean;
  className?: string;
  children?: ReactNode;
}

/** A centred dialog for a focused task; the body scrolls, the actions stay in view. */
export function Modal({ title, description, size = "md", actions, isDismissable = true, className, children, ...state }: ModalProps) {
  return (
    <ModalFrame
      {...state}
      title={title}
      description={description}
      size={size}
      role="dialog"
      isDismissable={isDismissable}
      showClose
      className={className}
    >
      {() => (
        <div className="lk-modal-main">
          {children ? <div className="lk-modal-text lk-modal-body">{children}</div> : null}
          {actions ? <div className="lk-modal-actions">{actions}</div> : null}
        </div>
      )}
    </ModalFrame>
  );
}

export interface DrawerProps extends OverlayState {
  title: ReactNode;
  description?: ReactNode;
  /** 480px (default) or 640px; always full screen on phones. */
  width?: "md" | "lg";
  /** Pinned under the scrolling body, for the drawer's actions. */
  footer?: ReactNode;
  isDismissable?: boolean;
  className?: string;
  children?: ReactNode;
}

/** A side sheet for detail or editing in context, without leaving the list behind it. */
export function Drawer({
  isOpen,
  onOpenChange,
  title,
  description,
  width = "md",
  footer,
  isDismissable = true,
  className,
  children,
}: DrawerProps) {
  const descriptionId = useId();
  return (
    <ModalOverlay isOpen={isOpen} onOpenChange={onOpenChange} isDismissable={isDismissable} className="lk-overlay lk-overlay-drawer">
      <RacModal className={cx("lk-drawer", width === "lg" && "lk-drawer-lg", className)}>
        <RacDialog aria-describedby={description ? descriptionId : undefined} className="lk-drawer-dialog">
          {({ close }) => (
            <>
              <header className="lk-drawer-head">
                <div>
                  <Heading slot="title" level={2} className="lk-drawer-title">
                    {title}
                  </Heading>
                  {description ? (
                    <p id={descriptionId} className="lk-drawer-desc">
                      {description}
                    </p>
                  ) : null}
                </div>
                <IconButton icon="x" label="Close" variant="ghost" onPress={close} />
              </header>
              <div className="lk-drawer-body">{children}</div>
              {footer ? <footer className="lk-drawer-foot">{footer}</footer> : null}
            </>
          )}
        </RacDialog>
      </RacModal>
    </ModalOverlay>
  );
}

/**
 * Runs a confirmation. A handler that returns a promise keeps the dialog open, with the spinner,
 * until it settles: resolved closes it, rejected leaves it open for another try (the caller
 * reports why). A handler that returns nothing closes the dialog at once, unless the caller
 * passes `loading` and so owns both the spinner and the closing.
 */
function useConfirmation(loading: boolean | undefined, onOpenChange: (open: boolean) => void) {
  const [pending, setPending] = useState(false);
  const busy = pending || loading === true;
  const run = async (action: () => void | Promise<void>) => {
    if (busy) return;
    const result = action();
    if (result instanceof Promise) {
      setPending(true);
      try {
        await result;
        onOpenChange(false);
      } catch {
        // Stays open so the person can retry; the caller's own error handling says what failed.
      } finally {
        setPending(false);
      }
    } else if (loading === undefined) {
      onOpenChange(false);
    }
  };
  return { busy, run };
}

interface ConfirmBase extends OverlayState {
  title: ReactNode;
  description?: ReactNode;
  /** Names the action with its verb: "Delete quotation", never "OK" or "Yes". */
  confirmLabel: string;
  cancelLabel?: string;
  /** danger: the ember button, and Cancel takes the initial focus. */
  tone?: "default" | "danger";
  /** The caller's own in-flight state; see `onConfirm`. */
  loading?: boolean;
}

export interface ConfirmDialogProps extends ConfirmBase {
  /** Return a promise to hold the dialog open until the work settles. */
  onConfirm: () => void | Promise<void>;
}

/** Asks before something that is hard to undo. Only its buttons or Escape close it. */
export function ConfirmDialog({
  isOpen,
  onOpenChange,
  title,
  description,
  confirmLabel,
  cancelLabel = "Cancel",
  tone = "default",
  loading,
  onConfirm,
}: ConfirmDialogProps) {
  const { busy, run } = useConfirmation(loading, onOpenChange);
  const danger = tone === "danger";
  return (
    <ModalFrame
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      title={title}
      description={description}
      size="sm"
      role="alertdialog"
      isDismissable={false}
      locked={busy}
      showClose={false}
    >
      {(close) => (
        <div className="lk-modal-actions">
          <Button variant="ghost" onPress={close} isDisabled={busy} autoFocus={danger}>
            {cancelLabel}
          </Button>
          <Button variant={danger ? "danger" : "primary"} loading={busy} autoFocus={!danger} onPress={() => void run(onConfirm)}>
            {confirmLabel}
          </Button>
        </div>
      )}
    </ModalFrame>
  );
}

export interface ReasonDialogProps extends ConfirmBase {
  /** Receives the trimmed reason (at least 3 characters). */
  onConfirm: (reason: string) => void | Promise<void>;
  reasonLabel?: string;
  /** What a useful reason looks like, or who will read it. */
  reasonHelp?: ReactNode;
}

const REASON_MIN = 3;

interface ReasonFormProps
  extends Pick<ReasonDialogProps, "confirmLabel" | "cancelLabel" | "tone" | "onConfirm" | "reasonLabel" | "reasonHelp"> {
  close: () => void;
  busy: boolean;
  run: (action: () => void | Promise<void>) => Promise<void>;
}

/** Lives inside the open dialog, so the text and the error reset every time it opens. */
function ReasonForm({
  confirmLabel,
  cancelLabel = "Cancel",
  tone = "default",
  onConfirm,
  reasonLabel = "Reason",
  reasonHelp,
  close,
  busy,
  run,
}: ReasonFormProps) {
  const [reason, setReason] = useState("");
  const [attempted, setAttempted] = useState(false);
  const fieldId = useId();
  const noteId = useId();
  const field = useRef<HTMLTextAreaElement>(null);
  const trimmed = reason.trim();
  const valid = trimmed.length >= REASON_MIN;
  const error = attempted && !valid ? (trimmed.length === 0 ? "Give a reason." : `Use at least ${REASON_MIN} characters.`) : null;

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!valid) {
      setAttempted(true);
      field.current?.focus();
      return;
    }
    void run(() => onConfirm(trimmed));
  };

  return (
    <form className="lk-modal-main" onSubmit={submit} noValidate>
      <div className="lk-modal-text lk-modal-body">
        <div className="lk-field lk-reason">
          <label className="lk-field-label" htmlFor={fieldId}>
            <span>{reasonLabel}</span>
          </label>
          <div className={cx("lk-input", "lk-textarea", error && "lk-input-invalid", busy && "lk-input-disabled")}>
            <textarea
              id={fieldId}
              ref={field}
              rows={3}
              required
              autoFocus
              disabled={busy}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              aria-invalid={error ? true : undefined}
              aria-describedby={error || reasonHelp ? noteId : undefined}
            />
          </div>
          <div className="lk-reason-note">
            {error ? (
              <div id={noteId} className="lk-field-error" role="alert">
                <Icon name="alert" size={14} />
                {error}
              </div>
            ) : reasonHelp ? (
              <div id={noteId} className="lk-field-help">
                {reasonHelp}
              </div>
            ) : null}
          </div>
        </div>
      </div>
      <div className="lk-modal-actions">
        <Button variant="ghost" onPress={close} isDisabled={busy}>
          {cancelLabel}
        </Button>
        <Button type="submit" variant={tone === "danger" ? "danger" : "primary"} loading={busy}>
          {confirmLabel}
        </Button>
      </div>
    </form>
  );
}

/** A confirmation that must be explained (reject, cancel, override): the reason is recorded. */
export function ReasonDialog({ isOpen, onOpenChange, title, description, loading, ...form }: ReasonDialogProps) {
  const { busy, run } = useConfirmation(loading, onOpenChange);
  return (
    <ModalFrame
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      title={title}
      description={description}
      size="md"
      role="dialog"
      isDismissable={false}
      locked={busy}
      showClose={false}
    >
      {(close) => <ReasonForm {...form} close={close} busy={busy} run={run} />}
    </ModalFrame>
  );
}
