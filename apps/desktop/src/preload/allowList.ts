/**
 * Explicit IPC channel allow-list. Empty at E02-T04 (Do NOT: no business
 * logic here). Adding a channel later means editing this array, which is
 * code-owned by the security engineer (trust boundary B4, 20-architecture.md
 * §2.2). `buildAllowedChannels` rejects any channel not present here so a
 * caller can never widen the surface implicitly.
 */
export const ALLOWED_IPC_CHANNELS: readonly string[] = [];

export function isChannelAllowed(
  channel: string,
  allowedChannels: readonly string[] = ALLOWED_IPC_CHANNELS,
): boolean {
  return allowedChannels.includes(channel);
}

/**
 * Builds the frozen record of invoke functions exposed as `window.cv`.
 * Throws if a requested channel is not on the allow-list — there is no
 * fallback path that silently permits an unlisted channel.
 */
export function buildAllowList(
  channels: readonly string[],
  invoke: (channel: string, ...args: unknown[]) => Promise<unknown>,
  allowedChannels: readonly string[] = ALLOWED_IPC_CHANNELS,
): Readonly<Record<string, (...args: unknown[]) => Promise<unknown>>> {
  const built: Record<string, (...args: unknown[]) => Promise<unknown>> = {};
  for (const channel of channels) {
    if (!isChannelAllowed(channel, allowedChannels)) {
      throw new Error(`IPC channel "${channel}" is not on the allow-list`);
    }
    built[channel] = (...args: unknown[]) => invoke(channel, ...args);
  }
  return Object.freeze(built);
}
