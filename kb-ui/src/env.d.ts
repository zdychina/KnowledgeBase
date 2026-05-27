/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_MINING_API_BASE: string
  readonly VITE_SERVING_API_BASE: string
  readonly VITE_LLM_API_BASE: string
  readonly VITE_CONTROL_PLANE_API_BASE: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
