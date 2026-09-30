/**
 * Subscription restore ordering after a reconnect (`docs/plan/23-ws-protocol.md`
 * §9.3): `system` (implicit) -> private account state -> the focused pane's
 * topics -> other panes' topics. `system` never needs re-subscribing (it is
 * auto-subscribed at `auth_ok`), so this module only orders the remaining
 * three priority buckets for whatever registers into them.
 */

export type SubscriptionPriority = "private" | "focused" | "other";

const PRIORITY_ORDER: readonly SubscriptionPriority[] = ["private", "focused", "other"];

export interface SubscriptionRequest {
  readonly topic: string;
  readonly priority: SubscriptionPriority;
}

/** Sorts pending subscription requests into the documented restore order.
 * Stable within a priority bucket (insertion order preserved). */
export function orderSubscriptionsForRestore(
  requests: readonly SubscriptionRequest[],
): readonly SubscriptionRequest[] {
  return PRIORITY_ORDER.flatMap((priority) => requests.filter((r) => r.priority === priority));
}
