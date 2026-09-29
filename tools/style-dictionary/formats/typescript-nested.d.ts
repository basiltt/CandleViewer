interface Dictionary {
  allTokens: Array<{ name: string; value: unknown }>;
}

export default function typescriptNestedObject(args: { dictionary: Dictionary }): string;
