"use client";

import { useId, useState, type FormEvent } from "react";
import { Button as RacButton, Form } from "react-aria-components";
import { Button } from "@/components/ui/button";
import { MicIcon, SendIcon } from "@/components/ui/icons";
import { TextArea } from "@/components/ui/text-field";
import { cx } from "@/lib/cx";
import { briefingMessages as m } from "@/messages/briefing";

export interface VoiceControl {
  onPressStart: () => void;
  onPressEnd: () => void;
  isRecording: boolean;
}

export interface CommandBarProps {
  /** Sends the typed request; omitted while the assistant is not available. */
  onSubmit?: (text: string) => void | Promise<void>;
  /** Why the bar is unavailable (shown and used as the disabled controls' description). */
  unavailableReason?: string;
  /**
   * Push-to-talk. Rendered only when the session's voice capability is on and a recorder
   * is wired; never a dead button.
   */
  voice?: VoiceControl | null;
  isPending?: boolean;
}

/** Compact text (and, when enabled, voice) command bar under the greeting. */
export function CommandBar({ onSubmit, unavailableReason = m.command.unavailable, voice, isPending = false }: CommandBarProps) {
  const [text, setText] = useState("");
  const hintId = useId();
  const available = Boolean(onSubmit);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const value = text.trim();
    if (!onSubmit || !value || isPending) return;
    await onSubmit(value);
    setText("");
  };

  return (
    // On phones the composer dock supplies the surface and border; the card chrome starts at md.
    <Form onSubmit={submit} className="flex flex-col gap-2 md:rounded-lg md:border md:bg-surface md:p-4 md:shadow-sm">
      <div className="flex items-end gap-2">
        <TextArea
          label={m.command.label}
          placeholder={m.command.placeholder}
          rows={1}
          value={text}
          onChange={setText}
          isDisabled={!available}
          aria-describedby={available ? undefined : hintId}
          className="flex-1"
        />
        {voice ? (
          <RacButton
            aria-label={m.command.pushToTalk}
            aria-pressed={voice.isRecording}
            onPressStart={voice.onPressStart}
            onPressEnd={voice.onPressEnd}
            className={cx(
              "flex size-11 shrink-0 items-center justify-center rounded-md bg-forest text-on-forest outline-none hover:bg-forest-strong",
              voice.isRecording && "bg-forest-strong",
            )}
          >
            <MicIcon />
          </RacButton>
        ) : null}
        {available ? (
          <Button type="submit" variant="primary" isPending={isPending} icon={<SendIcon size={18} />}>
            {m.command.send}
          </Button>
        ) : (
          <Button type="submit" variant="primary" isDisabled disabledReason={unavailableReason} icon={<SendIcon size={18} />}>
            {m.command.send}
          </Button>
        )}
      </div>
      {available ? null : (
        <p id={hintId} className="text-xs text-ink-muted md:text-sm">
          {unavailableReason}
        </p>
      )}
    </Form>
  );
}
