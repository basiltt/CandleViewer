import type { StorybookConfig } from "@storybook/react-vite";

// Storybook 8 config (E02-T03 scaffold). The a11y addon is the gate surface
// referenced by CONSTITUTION.md §9 #9 until real screens exist (E05).
const config: StorybookConfig = {
  stories: ["../src/**/*.stories.@(ts|tsx)"],
  addons: ["@storybook/addon-essentials", "@storybook/addon-a11y"],
  framework: {
    name: "@storybook/react-vite",
    options: {},
  },
  core: {
    disableTelemetry: true,
  },
};

export default config;
