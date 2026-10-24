export interface User {
  id: number;
  email: string;
  display_name: string;
  is_active: boolean;
  roles: string[];
  /** Effective permission patterns resolved from the user's roles. */
  permissions: string[];
  created_at: string;
}

export interface Server {
  server_id: string;
  name: string;
  description: string | null;
  transport: string;
  url: string | null;
  health_url: string | null;
  enabled: boolean;
  status: string;
  has_credential: boolean;
  credential_type: string;
  tool_count: number;
  last_error: string | null;
  last_checked_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Tool {
  name: string;
  server_id: string;
  upstream_tool: string;
  description: string | null;
  input_schema: Record<string, unknown>;
  permitted: boolean;
}

export interface ApiKey {
  id: number;
  name: string;
  prefix: string;
  active: boolean;
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
}

export interface AuditEntry {
  id: number;
  created_at: string;
  user_email: string | null;
  user_id: number | null;
  server_id: string;
  public_tool_name: string | null;
  upstream_tool_name: string | null;
  status: string;
  error_code: string | null;
  latency_ms: number | null;
  auth_method: string | null;
}

export interface AuditPage {
  items: AuditEntry[];
  page: number;
  per_page: number;
  total: number;
  has_more: boolean;
}

export interface Overview {
  upstreams_enabled: number;
  upstreams_total: number;
  tools_total: number;
  tools_permitted: number;
  servers: Server[];
  recent_activity: AuditEntry[];
}

export interface AgentTool {
  name: string;
  description: string | null;
}

export interface AgentConfig {
  model: string;
  tracing_enabled: boolean;
  max_iterations: number;
  max_tool_calls: number;
  max_history_messages: number;
  business_timezone: string;
}

export interface ToolCall {
  tool: string;
  status: string;
  latency_ms: number;
}

export interface ChatResponse {
  conversation_id: number;
  reply: string;
  tool_calls: ToolCall[];
  iterations: number;
  truncated: boolean;
  truncated_reason: string | null;
  model_error: string | null;
}

export interface Conversation {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ConversationMessage {
  id: number;
  role: string;
  content: string;
  tool_summary: ToolCall[] | null;
  created_at: string;
}


export interface DemoPersona {
  id: string;
  role: string;
  email: string;
  display_name: string;
  title: string;
  summary: string;
  capabilities: string[];
}

export interface DemoConfig {
  enabled: boolean;
  personas: DemoPersona[];
  deployment: string;
}
