// Fixtures for cv-shell-dangerously-set-inner-html.
declare const React: { createElement(...a: unknown[]): unknown };
declare const el: HTMLElement;

export const bad = <div dangerouslySetInnerHTML={{ __html: "x" }} />; // ruleid: cv-shell-dangerously-set-inner-html
export const badProps = React.createElement("div", { dangerouslySetInnerHTML: { __html: "x" } }); // ruleid: cv-shell-dangerously-set-inner-html

export function sink(v: string): void {
  el.innerHTML = v; // ruleid: cv-shell-dangerously-set-inner-html
  el.insertAdjacentHTML("beforeend", v); // ruleid: cv-shell-dangerously-set-inner-html
}

export const good = <div>{"text is escaped"}</div>; // ok: cv-shell-dangerously-set-inner-html
export function safe(v: string): void {
  el.textContent = v; // ok: cv-shell-dangerously-set-inner-html
}
