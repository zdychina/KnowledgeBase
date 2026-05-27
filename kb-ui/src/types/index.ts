export interface DomainConfig {
  miningApi: string
  servingApi: string
  llmApi: string
  active: boolean
}

export type DomainMap = Record<string, DomainConfig>

export interface ControlPlaneCapability {
  domain_id: string
  service_name: 'mining' | 'serving' | 'llm' | 'ui'
  enabled: boolean
  rollout_state: string
  notes?: string | null
}

export interface ControlPlaneServiceInstance {
  instance_id: string
  service_name: 'mining' | 'serving' | 'llm' | 'ui'
  display_name: string
  base_url: string
  healthcheck_url?: string | null
  environment: string
  enabled: boolean
  metadata_json?: Record<string, unknown>
}

export interface ControlPlaneServiceBinding {
  domain_id: string
  service_name: 'mining' | 'serving' | 'llm' | 'ui'
  instance_id: string
  binding_mode: 'shared' | 'exclusive'
  priority: number
  notes?: string | null
}

export interface ControlPlaneDatabaseBinding {
  binding_id: string
  domain_id: string
  usage_type: 'asset_core' | 'mining_runtime' | 'llm_runtime' | 'shared'
  secret_ref: string
  driver: string
  database_name?: string | null
  schema_name?: string | null
  readonly: boolean
  notes?: string | null
}

export interface ControlPlaneRuntimeOverride {
  override_id: string
  domain_id: string
  service_name: 'mining' | 'serving' | 'llm' | 'ui'
  config_scope: string
  config_json: Record<string, unknown>
  version_tag?: string | null
}

export interface ControlPlaneDomainSummary {
  domain_id: string
  display_name: string
  enabled: boolean
  default_channel: string
  scenario_pack_ref: string
  description?: string | null
  owner_team?: string | null
  metadata_json?: Record<string, unknown>
  created_at: string
  updated_at: string
  capabilities: ControlPlaneCapability[]
}

export interface ControlPlaneDomainDetail extends ControlPlaneDomainSummary {
  service_bindings: ControlPlaneServiceBinding[]
  database_bindings: ControlPlaneDatabaseBinding[]
  overrides: ControlPlaneRuntimeOverride[]
}

export interface ControlPlaneObservationPayload {
  domain: string
  runtime_mode: string
  knowledge_mining: Record<string, unknown>
  agent_serving_java: Record<string, unknown>
  llm_service: Record<string, unknown>
  kb_ui: Record<string, unknown>
  scenario_pack_exists: boolean
}

export interface ControlPlaneDiffItem {
  field: string
  control_plane_value: unknown
  observed_value: unknown
  status: 'match' | 'mismatch'
}

export interface ControlPlaneRuntimePayload {
  domain: string
  display_name: string
  enabled: boolean
  default_channel: string
  scenario_pack: { ref: string; version: string }
  capabilities: Record<string, boolean>
  service_bindings: Record<string, {
    instance_id: string
    binding_mode: string
    priority: number
    base_url?: string | null
    healthcheck_url?: string | null
  }>
  database_bindings: Record<string, {
    binding_id: string
    secret_ref: string
    driver: string
    database_name?: string | null
    schema_name?: string | null
    readonly: boolean
  }>
  overrides: Record<string, Record<string, Record<string, unknown>>>
  control_plane_mode: string
}

export interface ControlPlaneAuditLog {
  audit_id: string
  actor: string
  action: string
  resource_type: string
  resource_id: string
  before_json?: unknown
  after_json?: unknown
  created_at: string
}

export interface HealthStatus {
  status: string
  message?: string
  timestamp?: string
  version?: string
}

// ─── Knowledge Stats ───

export interface KnowledgeStats {
  documents: number
  snapshots: number
  segments: number
  relations: number
  retrieval_units: number
  embeddings: number
  builds: number
  releases: number
  retrieval_units_by_type?: Record<string, number>
  active_release?: string
}

// ─── Mining Run ───

export interface MiningRun {
  id: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  input_path?: string
  domain?: string
  started_at?: string
  finished_at?: string
  total_documents: number
  committed_count: number
  failed_count: number
  skipped_count: number
  new_count: number
  updated_count: number
  build_id?: string
  error_message?: string
  config?: Record<string, unknown>
}

export interface MiningRunStage {
  id: string
  stage: string
  status: string
  created_at: string
  duration_ms?: number | null
  output_summary?: string | null
  error_message?: string | null
  run_document_id?: string | null
}

export interface MiningRunDocument {
  id?: string
  document_id: string
  document_name: string
  document_key?: string
  status: 'pending' | 'processing' | 'committed' | 'failed' | 'skipped'
  action: 'new' | 'updated' | 'unchanged'
  error_message?: string
  error_summary?: string
  current_stage?: string | null
  duration_ms?: number | null
  started_at?: string
  finished_at?: string
  document_snapshot_id?: string | null
  stage?: string
}

// ─── Knowledge Assets ───

export interface KnowledgeDocument {
  id: string
  document_key: string
  document_name: string
  document_type: string
  metadata_json?: Record<string, unknown>
  created_at: string
}

export interface KnowledgeSegment {
  id: string
  segment_key: string
  segment_index: number
  block_type: string
  semantic_role: string
  section_title?: string
  raw_text: string
  token_count: number
}

export interface KnowledgeUnit {
  id: string
  unit_key: string
  unit_type: 'raw_text' | 'contextual_text' | 'summary' | 'generated_question' | 'entity_card'
  target_type: string
  title: string
  text: string
  weight: number
  block_type?: string
  semantic_role?: string
  created_at?: string
}

export interface KnowledgeRelation {
  id: string
  document_snapshot_id: string
  source_segment_id: string
  target_segment_id: string
  relation_type: string
  weight: number
  confidence: number
  distance: number
  source_text?: string
  target_text?: string
}

// ─── Search / Serving ───

export interface SearchResult {
  items: SearchContextItem[]
  relations: SearchContextRelation[]
  sources: SearchSourceRef[]
  evidence_groups?: SearchEvidenceGroup[]
  issues?: SearchIssue[]
  suggestions?: string[]
  debug?: SearchDebug
}

export interface SearchContextItem {
  id: string
  kind: string
  role: 'seed' | 'context' | 'support'
  text: string
  score: number
  title: string
  blockType: string
  semanticRole: string
  sourceId: string | null
  relationToSeed?: string | null
  routeSources?: string[]
  scoreChain?: Record<string, unknown>
  evidenceRole: string
  citation?: {
    raw_segment_ids?: string[]
    section?: string
    document_snapshot_id?: string
  }
  metadata?: Record<string, unknown>
}

export interface SearchContextRelation {
  id: string
  fromId: string
  toId: string
  relationType: string
  distance?: number
}

export interface SearchSourceRef {
  id: string
  documentKey: string
  title: string
  relativePath?: string
  metadata?: Record<string, unknown>
}

export interface SearchEvidenceGroup {
  documentSnapshotId: string
  itemIds: string[]
  relationIds: string[]
}

export interface SearchIssue {
  severity: string
  message: string
}

export interface SearchDebug {
  understanding?: {
    original_query: string
    intent: string
    source: string
    keywords: string[]
    entities_count: number
  }
  route_plan?: {
    routes_count: number
    fusion_method: string
    rerank_method: string
  }
  scope?: {
    release_id: string
    snapshot_count: number
  }
  trace?: {
    request_id: string
    total_duration_ms: number
    stages: SearchDebugStage[]
  }
  candidate_count?: number
  fusion_method?: string
  query_embedding_dim?: number
}

export interface SearchDebugStage {
  name: string
  duration_ms: number
  summary?: string
  input?: string
  output?: string
  error?: string | null
}

// ─── LLM Service ───

export interface LlmTaskStats {
  tasks_by_status: Record<string, number>
  tasks_by_type?: Record<string, number>
  succeeded_attempts: number
  total_tokens: number
  avg_latency_ms: number
  services?: string[]
  domains?: string[]
  stages?: string[]
}

export interface LlmTask {
  id: string
  task_type: 'chat' | 'embedding' | 'rerank'
  caller_service?: string
  knowledge_domain?: string
  pipeline_stage?: string
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'dead_letter' | 'cancelled'
  priority: number
  attempt_count: number
  max_attempts: number
  created_at: string
  started_at?: string
  finished_at?: string
  idempotency_key?: string
  error_message?: string
  total_tokens?: number
  latency_ms?: number
  metadata?: Record<string, unknown>
}

export interface LlmTaskDetail extends LlmTask {
  prompt_tokens?: number
  completion_tokens?: number
  total_tokens?: number
  latency_ms?: number
  raw_response?: Record<string, unknown>
  parsed_output?: Record<string, unknown>
}

// ─── Upload Config ───

export interface UploadConfig {
  max_file_size: number
  max_archive_size: number
  max_files_per_request: number
  max_file_size_mb: number
  max_archive_size_mb: number
  accepted_extensions: string[]
  archive_extensions: string[]
}

export interface UploadResult {
  upload_batch_id: string
  domain: string
  file_count: number
  files: string[]
  storage_path: string
  extracted_archives: Array<{
    archive: string
    error: string | null
    file_count: number
    files: string[]
  }>
}

// ─── Paginated Response ───

export interface PaginatedResponse<T> {
  total: number
  limit: number
  offset: number
  items: T[]
}
