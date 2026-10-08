import { createHmac } from "node:crypto";

// RFC 6238 TOTP (SHA-1, 6 digits, 30 s) for the E09-Q02 fixture secret. Test-only; never a real secret.
export const FIXTURE_TOTP_SECRET_BASE32 = "JBSWY3DPEHPK3PXP";
export const TOTP_STEP_S = 30;

function base32Decode(input: string): Buffer {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const ch of input.replace(/=+$/u, "").toUpperCase()) {
    const idx = alphabet.indexOf(ch);
    if (idx < 0) throw new Error(`invalid base32 character: ${ch}`);
    bits += idx.toString(2).padStart(5, "0");
  }
  const bytes: number[] = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) bytes.push(parseInt(bits.slice(i, i + 8), 2));
  return Buffer.from(bytes);
}

/** RFC 6238 code for `secret` at `atMs` (epoch ms), offset by whole `stepOffset` steps. */
export function totp(secretBase32: string, atMs: number, stepOffset = 0): string {
  const counter = Math.floor(atMs / 1000 / TOTP_STEP_S) + stepOffset;
  const msg = Buffer.alloc(8);
  msg.writeBigUInt64BE(BigInt(counter));
  const mac = createHmac("sha1", base32Decode(secretBase32)).update(msg).digest();
  const off = (mac[mac.length - 1] ?? 0) & 0x0f;
  const bin =
    (((mac[off] ?? 0) & 0x7f) << 24) |
    (((mac[off + 1] ?? 0) & 0xff) << 16) |
    (((mac[off + 2] ?? 0) & 0xff) << 8) |
    ((mac[off + 3] ?? 0) & 0xff);
  return String(bin % 1_000_000).padStart(6, "0");
}
