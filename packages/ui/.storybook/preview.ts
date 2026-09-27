import type { Preview } from "@storybook/react";

// Zero serious/critical a11y violations is the bar (CONSTITUTION §9 #9).
const preview: Preview = {
  parameters: {
    a11y: {
      test: "error",
    },
    controls: {
      matchers: {
        color: /(background|color)$/i,
        date: /Date$/i,
      },
    },
  },
};

export default preview;
