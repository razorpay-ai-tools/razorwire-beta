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
    // The Python backend and its virtualenv are not JS/TS source. The render
    // pipeline installs Playwright into backend/.venv, whose bundled Node driver
    // would otherwise flood `npm run lint` with thousands of vendored-file issues.
    "backend/**",
  ]),
]);

export default eslintConfig;
