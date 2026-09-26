// Shared Vitest preset. Consumers spread this into their own vitest.config
// via `defineConfig({ ...vitestPreset, test: { ...vitestPreset.test, ... } })`.
export const vitestPreset = {
  test: {
    environment: "node",
    globals: false,
    coverage: {
      provider: "v8",
      reporter: ["text", "lcov"],
      thresholds: {
        lines: 80,
        statements: 80,
        functions: 80,
        branches: 70,
      },
    },
  },
};

export default vitestPreset;
