export function hexToRgba(hex: string): [number, number, number, number];
export function isEngineToken(name: string): boolean;

interface Dictionary {
  allTokens: Array<{ name: string; value: unknown }>;
}

export default function jsonFlatRgba(args: { dictionary: Dictionary }): string;
