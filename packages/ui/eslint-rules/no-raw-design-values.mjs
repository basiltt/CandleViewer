// Custom ESLint rule (flat config, no plugin package needed): forbids raw
// hex colours and raw px-literal spacing/size values in `packages/ui/src/**`,
// per E05-T01's acceptance criterion "Hardcoded value is rejected" —
// components must import from the generated `build/ts/tokens.ts` instead.
//
// The token *source* files (`packages/ui/tokens/**`) are exempt by scope:
// this rule is only wired into `src/**` in `eslint.config.mjs`.

const HEX_COLOR = /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/;
const RAW_PX = /^-?\d+(\.\d+)?px$/;

/** @type {import("eslint").Rule.RuleModule} */
export const noRawDesignValues = {
  meta: {
    type: "problem",
    docs: {
      description: "Disallow raw hex colours and raw px literals; use a design token instead.",
    },
    messages: {
      hex: "Raw hex colour '{{value}}' is not allowed in packages/ui/src — import the matching token from build/ts/tokens.ts instead.",
      px: "Raw px literal '{{value}}' is not allowed in packages/ui/src — use a spacing/sizing token from build/ts/tokens.ts instead.",
    },
    schema: [],
  },
  create(context) {
    function check(node, value) {
      if (typeof value !== "string") return;
      if (HEX_COLOR.test(value)) {
        context.report({ node, messageId: "hex", data: { value } });
      } else if (RAW_PX.test(value)) {
        context.report({ node, messageId: "px", data: { value } });
      }
    }
    return {
      Literal(node) {
        check(node, node.value);
      },
      TemplateElement(node) {
        check(node, node.value.raw);
      },
    };
  },
};

export default noRawDesignValues;
