import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// Same aliases as tsconfig.json: `~` is this app, `@` the shared data layer in apps/web (read-only).
export default defineConfig({
  resolve: {
    alias: {
      "~": fileURLToPath(new URL("./src", import.meta.url)),
      "@": fileURLToPath(new URL("../web/src", import.meta.url)),
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.{ts,tsx}"],
    restoreMocks: true,
    unstubGlobals: true,
  },
});
