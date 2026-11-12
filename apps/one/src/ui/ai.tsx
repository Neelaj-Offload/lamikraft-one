"use client";

import { useRef, useState, type KeyboardEvent } from "react";
import { cx } from "@/lib/cx";
import { IconButton } from "./button";
import { Icon } from "./icon";

/** The aurora and the orb belong to the assistant only; nothing else in the product uses them. */

export interface AuroraProps {
  /** A fainter wash, for behind text. */
  quiet?: boolean;
  className?: string;
}

/** The drifting colour field behind assistant surfaces. Decorative; still under reduced motion. */
export function Aurora({ quiet = false, className }: AuroraProps) {
  return (
    <div className={cx("lk-aurora", quiet && "lk-aurora-quiet", className)} aria-hidden="true">
      <span />
      <span />
      <span />
      <span />
      <span />
    </div>
  );
}

export type OrbState = "idle" | "listening" | "thinking";

export interface OrbProps {
  size?: "sm" | "md" | "lg" | "xl";
  state?: OrbState;
  /** The assistant's name for assistive technology; the state is appended. */
  label?: string;
  className?: string;
}

/** The assistant's presence: it breathes when idle, rings when listening, quickens when thinking. */
export function Orb({ size = "md", state = "idle", label = "Lamikraft assistant", className }: OrbProps) {
  return (
    <span className={cx("lk-orb-wrap", className)} role="img" aria-label={state === "idle" ? label : `${label}, ${state}`}>
      {state === "listening" ? (
        <>
          <span className="lk-orb-ring" />
          <span className="lk-orb-ring" />
        </>
      ) : null}
      <span className={cx("lk-orb", `lk-orb-${size}`, state !== "idle" && `lk-orb-${state}`)} />
    </span>
  );
}

export interface ComposerProps {
  placeholder?: string;
  /** Names the text box for assistive technology. */
  label?: string;
  /** Starter prompts shown as chips; choosing one fills the box. */
  suggestions?: string[];
  /** Controlled text. Leave out (with `defaultValue`) to let the composer keep its own. */
  value?: string;
  defaultValue?: string;
  onChange?: (text: string) => void;
  /** Called with the trimmed text on Enter or Send; the box is then cleared. */
  onSend?: (text: string) => void;
  /** Nothing can be typed or sent. */
  disabled?: boolean;
  /** A reply is on its way: the orb thinks and sending waits; typing the next message still works. */
  busy?: boolean;
  /** Renders the Attach button. */
  onAttach?: () => void;
  /** Renders the Voice button. */
  onVoice?: () => void;
  /** Shows the orb listening (voice capture is running). */
  listening?: boolean;
  className?: string;
}

/**
 * The assistant's message box. Enter sends, Shift+Enter starts a new line. Attach and Voice are
 * only rendered when they are wired up.
 */
export function Composer({
  placeholder = "Ask Lamikraft anything…",
  label = "Message",
  suggestions,
  value,
  defaultValue = "",
  onChange,
  onSend,
  disabled = false,
  busy = false,
  onAttach,
  onVoice,
  listening = false,
  className,
}: ComposerProps) {
  const [internal, setInternal] = useState(defaultValue);
  const text = value ?? internal;
  const box = useRef<HTMLTextAreaElement>(null);
  const canSend = !disabled && !busy && text.trim().length > 0;

  const update = (next: string) => {
    setInternal(next);
    onChange?.(next);
  };
  const send = () => {
    if (!canSend) return;
    onSend?.(text.trim());
    update("");
  };
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter while an input method is composing confirms the composition, it does not send.
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    send();
  };

  return (
    <div className={cx("lk-composer", disabled && "lk-composer-disabled", className)}>
      <div className="lk-composer-inner">
        <Aurora />
        {suggestions && suggestions.length > 0 ? (
          <div className="lk-composer-chips">
            {suggestions.map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                className="lk-composer-chip"
                disabled={disabled}
                onClick={() => {
                  update(suggestion);
                  box.current?.focus();
                }}
              >
                <Icon name="sparkles" size={13} />
                {suggestion}
              </button>
            ))}
          </div>
        ) : null}
        <div className="lk-composer-row">
          <Orb size="sm" state={busy ? "thinking" : listening ? "listening" : "idle"} />
          <textarea
            ref={box}
            value={text}
            placeholder={placeholder}
            rows={2}
            aria-label={label}
            disabled={disabled}
            enterKeyHint="send"
            onChange={(event) => update(event.target.value)}
            onKeyDown={onKeyDown}
          />
        </div>
        <div className="lk-composer-foot">
          {onAttach ? <IconButton icon="paperclip" label="Attach" variant="ghost" size="sm" isDisabled={disabled} onPress={onAttach} /> : null}
          {onVoice ? <IconButton icon="mic" label="Voice" variant="ghost" size="sm" isDisabled={disabled} onPress={onVoice} /> : null}
          <span className="lk-spacer" />
          <span className="lk-composer-hint">
            <kbd>↵</kbd> to send
          </span>
          <IconButton icon="send" label="Send" variant="inverse" isDisabled={!canSend} onPress={send} />
        </div>
      </div>
    </div>
  );
}
