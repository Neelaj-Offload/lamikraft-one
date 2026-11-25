"use client";

import { useId, useState, type ReactNode } from "react";
import { Button as RacButton, DropZone, FileTrigger, Text } from "react-aria-components";
import { cx } from "@/lib/cx";
import { useZone } from "@/lib/session/context";
import { FieldShell, hasError } from "./field";
import { Icon } from "./icon";

export interface FileFieldProps {
  label: string;
  optional?: boolean;
  /** Accepted types: MIME types (`"application/pdf"`, `"image/*"`) or extensions (`".xlsx"`). */
  accept?: string[];
  multiple?: boolean;
  /** Largest file allowed, in bytes. */
  maxBytes?: number;
  /** Called with the full list of chosen files each time it changes (also after a removal). */
  onSelect: (files: File[]) => void;
  help?: ReactNode;
  error?: ReactNode;
  isDisabled?: boolean;
  className?: string;
}

/** `482 KB`, `1.2 MB`: sizes in the units people see in their file manager. */
function formatBytes(bytes: number, locale: string): string {
  const units = ["bytes", "KB", "MB", "GB"] as const;
  let amount = bytes;
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) {
    amount /= 1024;
    unit += 1;
  }
  const digits = unit === 0 || amount >= 100 ? 0 : 1;
  return `${new Intl.NumberFormat(locale, { maximumFractionDigits: digits }).format(amount)} ${units[unit] ?? "bytes"}`;
}

function matchesAccept(file: File, accept: readonly string[] | undefined): boolean {
  if (!accept || accept.length === 0) return true;
  const name = file.name.toLowerCase();
  return accept.some((entry) => {
    const rule = entry.trim().toLowerCase();
    if (rule.startsWith(".")) return name.endsWith(rule);
    if (rule.endsWith("/*")) return file.type.toLowerCase().startsWith(rule.slice(0, -1));
    return file.type.toLowerCase() === rule;
  });
}

/** `[".pdf", "image/*"]` to "PDF or image": the accepted types in words. */
function describeAccept(accept: readonly string[]): string {
  const words = accept.map((entry) => {
    const rule = entry.trim();
    if (rule.startsWith(".")) return rule.slice(1).toUpperCase();
    if (rule.endsWith("/*")) return rule.slice(0, -2);
    return (rule.split("/")[1] ?? rule).toUpperCase();
  });
  const unique = [...new Set(words)];
  if (unique.length <= 1) return unique[0] ?? "";
  return `${unique.slice(0, -1).join(", ")} or ${unique[unique.length - 1]}`;
}

const sameFile = (a: File, b: File) => a.name === b.name && a.size === b.size && a.lastModified === b.lastModified;

/**
 * Choose files with the button or by dropping them on the zone. Files of the wrong type or over
 * the size limit are refused with a message that names the file and the rule.
 */
export function FileField({
  label,
  optional,
  accept,
  multiple = false,
  maxBytes,
  onSelect,
  help,
  error,
  isDisabled,
  className,
}: FileFieldProps) {
  const { locale } = useZone();
  const labelId = useId();
  const messageId = useId();
  const [files, setFiles] = useState<File[]>([]);
  const [problem, setProblem] = useState<string | null>(null);

  const publish = (next: File[]) => {
    setFiles(next);
    onSelect(next);
  };

  const add = (incoming: File[]) => {
    if (incoming.length === 0) return;
    const offered = multiple ? incoming : incoming.slice(0, 1);
    const wrongType = offered.find((file) => !matchesAccept(file, accept));
    const tooLarge = maxBytes === undefined ? undefined : offered.find((file) => file.size > maxBytes);
    if (wrongType && accept) {
      setProblem(`${wrongType.name} is not an accepted type. Choose a ${describeAccept(accept)} file.`);
    } else if (tooLarge && maxBytes !== undefined) {
      setProblem(
        `${tooLarge.name} is ${formatBytes(tooLarge.size, locale)}. Choose a file of ${formatBytes(maxBytes, locale)} or less.`,
      );
    } else {
      setProblem(null);
    }
    const accepted = offered.filter(
      (file) => matchesAccept(file, accept) && (maxBytes === undefined || file.size <= maxBytes),
    );
    if (accepted.length === 0) return;
    if (!multiple) {
      publish(accepted);
      return;
    }
    const fresh = accepted.filter((file) => !files.some((existing) => sameFile(existing, file)));
    if (fresh.length > 0) publish([...files, ...fresh]);
  };

  const remove = (index: number) => {
    setProblem(null);
    publish(files.filter((_, position) => position !== index));
  };

  const message = problem ?? error;
  const invalid = hasError(message);
  const limits = [
    accept && accept.length > 0 ? describeAccept(accept) : null,
    maxBytes !== undefined ? `up to ${formatBytes(maxBytes, locale)}` : null,
  ].filter(Boolean);

  return (
    <FieldShell label={label} optional={optional} help={help} error={message} labelId={labelId} messageId={messageId} className={className}>
      <div role="group" aria-labelledby={labelId} aria-describedby={invalid || help ? messageId : undefined} className="lk-stack">
        <DropZone
          isDisabled={isDisabled}
          className={cx("lk-dropzone", invalid && "lk-dropzone-invalid")}
          onDrop={(event) => {
            void Promise.all(event.items.filter((item) => item.kind === "file").map((item) => item.getFile())).then(add);
          }}
        >
          <span className="lk-dropzone-art" aria-hidden="true">
            <Icon name="upload" size={20} />
          </span>
          <Text slot="label">{multiple ? "Drop files here, or choose them" : "Drop a file here, or choose one"}</Text>
          <FileTrigger
            acceptedFileTypes={accept}
            allowsMultiple={multiple}
            onSelect={(list) => add(list ? Array.from(list) : [])}
          >
            <RacButton isDisabled={isDisabled} className="lk-btn lk-btn-secondary lk-btn-sm">
              {multiple ? "Choose files" : files.length > 0 ? "Replace file" : "Choose file"}
            </RacButton>
          </FileTrigger>
          {limits.length > 0 ? <span className="lk-dropzone-hint">{limits.join(", ")}</span> : null}
        </DropZone>
        {files.length > 0 ? (
          <ul className="lk-file-list" aria-label={`Chosen for ${label}`}>
            {files.map((file, index) => (
              <li key={`${file.name}-${file.size}-${file.lastModified}`} className="lk-file">
                <Icon name="file" size={16} />
                <span className="lk-file-name">{file.name}</span>
                <span className="lk-file-size">{formatBytes(file.size, locale)}</span>
                <RacButton
                  className="lk-file-remove"
                  aria-label={`Remove ${file.name}`}
                  isDisabled={isDisabled}
                  onPress={() => remove(index)}
                >
                  <Icon name="x" size={16} />
                </RacButton>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </FieldShell>
  );
}
