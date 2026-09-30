// Fixtures for cv-electron-openexternal-unchecked.
declare const shell: { openExternal(url: string): Promise<void> };
declare function isExternalLinkAllowed(url: string): boolean;

export function guarded(url: string): void {
  if (isExternalLinkAllowed(url) && url.length > 0) {
    void shell.openExternal(url); // ok: cv-electron-openexternal-unchecked
  }
}

export function unguarded(url: string): void {
  void shell.openExternal(url); // ruleid: cv-electron-openexternal-unchecked
}

export function guardedByWrongCheck(url: string): void {
  if (url.startsWith("https:")) {
    void shell.openExternal(url); // ruleid: cv-electron-openexternal-unchecked
  }
}
