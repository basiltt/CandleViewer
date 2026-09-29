interface Dictionary {
  allTokens: Array<{ name: string; value: unknown }>;
}

export default function jsonFlat(args: { dictionary: Dictionary }): string;
