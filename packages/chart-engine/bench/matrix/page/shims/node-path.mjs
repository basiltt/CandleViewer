export function dirname(p) {
  return String(p).replace(/[\\/][^\\/]*$/, "") || "/";
}
export function join(...parts) {
  return parts.join("/");
}
