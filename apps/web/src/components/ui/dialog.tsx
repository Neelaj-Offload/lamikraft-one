"use client";

import type { ReactNode } from "react";
import {
  Dialog as RacDialog,
  DialogTrigger,
  Heading,
  Modal,
  ModalOverlay,
  type ModalOverlayProps,
} from "react-aria-components";
import { cx } from "@/lib/cx";
import { IconButton } from "./button";
import { CloseIcon } from "./icons";

export { DialogTrigger };

/**
 * Overlays trap focus, close on Escape and return focus to their trigger (React Aria).
 * Motion follows docs/architecture/motion-system.md §2: 180 ms fade/scale for dialogs,
 * 220 ms slide for drawers and sheets, 150-160 ms exits; reduced motion makes them instant.
 * The scrim is a flat tint (`--lk-scrim`), never a blur.
 */

const overlayClasses =
  "fixed inset-0 z-50 flex bg-scrim entering:animate-overlay-in exiting:animate-overlay-out";

interface OverlayChromeProps {
  title: string;
  /** One line under the title, linked as the dialog's description. */
  description?: ReactNode;
  children: ReactNode | ((close: () => void) => ReactNode);
  /** Footer actions; receive `close` so a Cancel button can dismiss the overlay. */
  footer?: (close: () => void) => ReactNode;
  /** Shown next to the title; defaults to a Close button. */
  hideCloseButton?: boolean;
}

function Chrome({ title, description, children, footer, hideCloseButton, close }: OverlayChromeProps & { close: () => void }) {
  return (
    <>
      <header className="flex items-start justify-between gap-4 border-b px-5 py-4">
        <div className="flex min-w-0 flex-col gap-1">
          <Heading slot="title" className="text-lg font-bold tracking-tight text-ink">
            {title}
          </Heading>
          {description ? <p className="text-sm text-ink-muted">{description}</p> : null}
        </div>
        {hideCloseButton ? null : (
          <IconButton label="Close" onPress={close} className="-me-2 -mt-1">
            <CloseIcon size={18} />
          </IconButton>
        )}
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{typeof children === "function" ? children(close) : children}</div>
      {footer ? <footer className="flex flex-wrap justify-end gap-2 border-t px-5 py-3">{footer(close)}</footer> : null}
    </>
  );
}

export type DialogProps = OverlayChromeProps &
  Pick<ModalOverlayProps, "isOpen" | "onOpenChange" | "isDismissable" | "isKeyboardDismissDisabled"> & {
    /** alertdialog for destructive confirmations. */
    role?: "dialog" | "alertdialog";
    size?: "sm" | "md" | "lg";
  };

/** Centred modal dialog; a full-width bottom sheet on phones. */
export function Dialog({ role = "dialog", size = "md", isDismissable = true, ...props }: DialogProps) {
  return (
    <ModalOverlay
      isOpen={props.isOpen}
      onOpenChange={props.onOpenChange}
      isDismissable={role === "alertdialog" ? false : isDismissable}
      isKeyboardDismissDisabled={props.isKeyboardDismissDisabled}
      className={cx(overlayClasses, "items-end justify-center md:items-center md:p-6")}
    >
      <Modal
        className={cx(
          "flex max-h-[min(90dvh,760px)] w-full flex-col overflow-hidden rounded-t-xl border bg-surface shadow-lg outline-none md:rounded-xl",
          size === "sm" && "md:max-w-md",
          size === "md" && "md:max-w-lg",
          size === "lg" && "md:max-w-2xl",
          "entering:animate-sheet-in exiting:animate-sheet-out md:entering:animate-pop-in md:exiting:animate-pop-out",
        )}
      >
        <RacDialog role={role} className="flex min-h-0 flex-1 flex-col outline-none">
          {({ close }) => <Chrome {...props} close={close} />}
        </RacDialog>
      </Modal>
    </ModalOverlay>
  );
}

export type DrawerProps = OverlayChromeProps &
  Pick<ModalOverlayProps, "isOpen" | "onOpenChange" | "isDismissable"> & {
    /** 480 (default) to 640 px wide; full screen on phones. */
    width?: "md" | "lg";
  };

/** Contextual side drawer anchored to the inline end (frontend_verification §13). */
export function Drawer({ width = "md", isDismissable = true, ...props }: DrawerProps) {
  return (
    <ModalOverlay
      isOpen={props.isOpen}
      onOpenChange={props.onOpenChange}
      isDismissable={isDismissable}
      className={cx(overlayClasses, "justify-end")}
    >
      <Modal
        className={cx(
          "flex h-dvh w-full flex-col border-s bg-surface shadow-lg outline-none",
          width === "md" ? "md:max-w-[480px]" : "md:max-w-[640px]",
          "entering:animate-drawer-in exiting:animate-drawer-out",
        )}
      >
        <RacDialog className="flex min-h-0 flex-1 flex-col outline-none">
          {({ close }) => <Chrome {...props} close={close} />}
        </RacDialog>
      </Modal>
    </ModalOverlay>
  );
}
