import { useState, useSyncExternalStore } from "react";
import { KEYMAP, type KeymapCommand } from "./keymap";
import { applyRebind } from "./audit";
import { getBindings, resetBindings, setBindings, subscribeBindings } from "./profile";
import { importProfile, normaliseBinding, validateBinding, type BindingProblem } from "./validate";

const MODS = ["Ctrl", "Alt", "Shift"] as const;

/** SCR-113 hotkey editor: typed/select capture, conflict + reserved refusal, audited rebinding. */
export function HotkeyEditor(): JSX.Element {
  const bindings = useSyncExternalStore(subscribeBindings, getBindings);
  const [problem, setProblem] = useState<{ cmd: KeymapCommand; p: BindingProblem } | null>(null);
  const [report, setReport] = useState<readonly string[]>([]);

  function tryBind(cmd: KeymapCommand, raw: string, ack = false): void {
    const p = validateBinding(cmd.id, raw, bindings, undefined, { acknowledgedUnsafe: ack });
    if (p) return setProblem({ cmd, p });
    setProblem(null);
    setBindings(applyRebind(bindings, cmd.id, normaliseBinding(raw) ?? raw, ack));
  }

  function onImport(text: string): void {
    let parsed: Record<string, string>;
    try {
      parsed = JSON.parse(text) as Record<string, string>;
    } catch {
      return setReport(["Import failed: not valid JSON"]);
    }
    const r = importProfile(parsed);
    for (const [id, b] of r.applied) {
      if (bindings.get(id) !== b) setBindings(applyRebind(getBindings(), id, b));
    }
    setReport(r.rejected.map((x) => `${x.commandId} -> ${x.binding}: ${x.problem.reason}`));
  }

  return (
    <section aria-labelledby="hk-h" data-keymap-context="Settings">
      <h2 id="hk-h">Hotkeys</h2>
      {problem ? (
        <div role="alert">
          <p>
            {problem.cmd.label}: {problem.p.reason}
            {problem.p.kind === "conflict" ? " - reassign it or choose another key." : ""}
          </p>
          {problem.p.kind === "unsafe-destructive" ? (
            <button type="button" onClick={() => tryBind(problem.cmd, pending(problem.cmd), true)}>
              I understand, bind anyway
            </button>
          ) : null}
        </div>
      ) : null}
      <table>
        <caption>Current key bindings by context</caption>
        <thead>
          <tr>
            <th scope="col">Context</th>
            <th scope="col">Command</th>
            <th scope="col">Binding</th>
            <th scope="col">Change</th>
          </tr>
        </thead>
        <tbody>
          {KEYMAP.map((c) => (
            <Row
              key={c.id}
              cmd={c}
              binding={bindings.get(c.id) ?? c.defaultBinding}
              onBind={tryBind}
            />
          ))}
        </tbody>
      </table>
      <button type="button" onClick={resetBindings}>
        Reset all
      </button>
      <label>
        Import keymap (JSON)
        <textarea
          aria-label="Import keymap JSON"
          onBlur={(e) => e.target.value && onImport(e.target.value)}
        />
      </label>
      {report.length ? (
        <ul aria-label="Import report">
          {report.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

const pendingMap = new Map<string, string>();
const pending = (c: KeymapCommand): string => pendingMap.get(c.id) ?? c.defaultBinding;

function Row(props: {
  cmd: KeymapCommand;
  binding: string;
  onBind: (c: KeymapCommand, raw: string, ack?: boolean) => void;
}): JSX.Element {
  const { cmd, binding, onBind } = props;
  const [mods, setMods] = useState<readonly string[]>([]);
  const [key, setKey] = useState("");
  const raw = [...MODS.filter((m) => mods.includes(m)), key].join("+");
  return (
    <tr>
      <td>{cmd.context}</td>
      <th scope="row">{cmd.label}</th>
      <td>
        <kbd>{binding}</kbd>
      </td>
      <td>
        {MODS.map((m) => (
          <label key={m}>
            <input
              type="checkbox"
              aria-label={`${m} for ${cmd.label}`}
              checked={mods.includes(m)}
              onChange={(e) =>
                setMods(e.target.checked ? [...mods, m] : mods.filter((x) => x !== m))
              }
            />
            {m}
          </label>
        ))}
        <input
          aria-label={`Key for ${cmd.label}`}
          value={key}
          onChange={(e) => setKey(e.target.value)}
          size={6}
        />
        <button
          type="button"
          disabled={!key}
          onClick={() => {
            pendingMap.set(cmd.id, raw);
            onBind(cmd, raw);
          }}
        >
          Save
        </button>
      </td>
    </tr>
  );
}
