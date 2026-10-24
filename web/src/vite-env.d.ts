/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of a live Sentinel API ("/" for same origin). Unset: the bundled demo data. */
  readonly VITE_SENTINEL_API?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
