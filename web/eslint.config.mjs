import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Vendored AI Elements components (shadcn registry copies). We use them as shipped and do not
    // lint upstream code; our own components in src/components/app are fully linted.
    "src/components/ai-elements/**",
    "src/components/ui/**",
  ]),
]);

export default eslintConfig;
