/** Join truthy class names. Tiny replacement for the `clsx` dependency. */
export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ');
}
