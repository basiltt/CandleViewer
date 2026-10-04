import { useSyncExternalStore } from "react";
import { KEYMAP } from "./keymap";
import { getBindings, subscribeBindings } from "./profile";

/** SCR-013 overlay: current bindings by context as a real table; conflicts get a warning chip. */
export function Cheatsheet({ onClose }: { readonly onClose?: () => void }): JSX.Element {
  const b = useSyncExternalStore(subscribeBindings, getBindings);
  const seen = new Map<string, number>();
  for (const c of KEYMAP) {
    const k = `${c.context}|${b.get(c.id)}`;
    seen.set(k, (seen.get(k) ?? 0) + 1);
  }
  const contexts = [...new Set(KEYMAP.map((c) => c.context))];
  return (
    <div role="dialog" aria-modal="false" aria-labelledby="cs-h">
      <h2 id="cs-h">Keyboard shortcuts</h2>
      <a href="/settings/hotkeys">Customise</a>
      {onClose ? (
        <button type="button" onClick={onClose}>
          Close
        </button>
      ) : null}
      {contexts.map((ctx) => (
        <table key={ctx}>
          <caption>{ctx}</caption>
          <thead>
            <tr>
              <th scope="col">Command</th>
              <th scope="col">Binding</th>
            </tr>
          </thead>
          <tbody>
            {KEYMAP.filter((c) => c.context === ctx).map((c) => {
              const bound = b.get(c.id) ?? c.defaultBinding;
              const conflict = (seen.get(`${ctx}|${bound}`) ?? 0) > 1;
              return (
                <tr key={c.id}>
                  <th scope="row">{c.label}</th>
                  <td>
                    <kbd>{bound}</kbd>
                    {conflict ? (
                      <span role="img" aria-label="Warning: conflicting binding">
                        {" "}
                        ⚠ Conflict
                      </span>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ))}
    </div>
  );
}
