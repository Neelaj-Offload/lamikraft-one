/** The product mark; `labelClassName` hides the name visually in the 64 px icon rail. */
export function Wordmark({ labelClassName }: { labelClassName?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-[17px] font-bold tracking-tight text-ink">
      <span aria-hidden="true" className="size-2.5 shrink-0 rounded-xs bg-sand" />
      <span className={labelClassName}>Lamikraft One</span>
    </span>
  );
}
