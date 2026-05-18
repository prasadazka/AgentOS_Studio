export interface Agent {
  name: string;
  model: string;
  temperature: number;
  tools: string[];
  system_prompt: string;
  is_default: boolean;
  max_iterations?: number;
  enable_memory?: boolean;
}

export interface ToolParameter {
  type: string; // "string" | "integer" | "number" | "boolean" | "array" | "object"
  items?: { type: string }; // for array types
}

export interface ToolSchema {
  name: string;
  description: string;
  category: string;
  version: string;
  parameters: {
    type: "object";
    properties: Record<string, ToolParameter>;
    required: string[];
  };
}

export interface Tool {
  name: string;
  description: string;
  category: string;
  version: string;
  requires_auth: boolean;
  tags: string[];
}

export interface ApprovalRequest {
  token: string;
  rowCount: string;
  tableCount: string;
  status: "pending" | "approved" | "denied";
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "tool";
  content: string;
  toolCalls?: ToolCall[];
  isStreaming?: boolean;
  latencyMs?: number;
  timestamp: Date;
  approvalRequest?: ApprovalRequest;
}

export interface ToolCall {
  name: string;
  args: Record<string, unknown>;
  result?: string;
  status: "running" | "done" | "error";
}

export interface Stats {
  total_agents: number;
  total_tools: number;
  total_categories: number;
  total_projects: number;
  default_agents: number;
  custom_agents: number;
}

export interface Project {
  id: string;
  name: string;
  description: string;
  agent_name: string;
  created_at: string;
  updated_at: string;
  file_count?: number;
  session_count?: number;
}

export interface ProjectFile {
  id: string;
  project_id: string;
  filename: string;
  file_type: string;
  file_size: number;
  status: "processing" | "ready" | "error";
  uploaded_at: string;
}

export interface ChatSession {
  id: string;
  project_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface DiskFile {
  id: string | null;
  filename: string;
  filepath: string;
  relative_path: string;
  file_type: string;
  file_size: number;
  status: string;
  source: "uploaded" | "generated";
}

// --- Workflows ---

export type WorkflowNodeType =
  | "start"
  | "end"
  | "agent"
  | "tool"
  | "condition"
  | "approval";

export interface WorkflowInputField {
  name: string;
  label: string;
  type: "text" | "textarea" | "number" | "select" | "file";
  required?: boolean;
  defaultValue?: string;
  placeholder?: string;
  options?: string[]; // for select type
}

export interface WorkflowNodeData {
  type: WorkflowNodeType;
  label: string;
  agentName?: string;
  // Agent overrides (editable per-node)
  agentModel?: string;
  agentTemperature?: number;
  agentSystemPrompt?: string;
  agentTools?: string[];
  toolName?: string;
  toolArgs?: Record<string, unknown>;
  expression?: string;
  approvalPrompt?: string;
  approvalTimeout?: number;
  autoApprove?: boolean;
  // Start node input fields (like n8n Form Trigger)
  inputFields?: WorkflowInputField[];
  [key: string]: unknown;
}

export interface WorkflowTemplate {
  id: string;
  name: string;
  description: string;
  category: string;
  icon: string;
  tags: string[];
  node_count: number;
}

export interface Workflow {
  id: string;
  name: string;
  description: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  graph_json: { nodes: any[]; edges: any[] };
  status: string;
  created_at: string;
  updated_at: string;
}

export interface WorkflowRun {
  id: string;
  workflow_id: string;
  input_text: string;
  status: "pending" | "running" | "paused" | "completed" | "error";
  node_states: Record<string, RunNodeState>;
  hitl_node_id?: string;
  hitl_request?: {
    type: string;
    prompt: string;
    node_id: string;
    context?: Record<string, unknown>;
  };
  hitl_response?: {
    action: string;
    value?: string;
    comment?: string;
  };
  output: string;
  error?: string;
  started_at: string;
  finished_at?: string;
}

export interface RunNodeState {
  status: "pending" | "running" | "completed" | "error";
  output?: string;
  error?: string;
  finished_at?: string;
}

export interface DebugEvent {
  type: "debug";
  phase: "compile" | "execute" | "summary";
  event: string;
  node_id?: string;
  label?: string;
  data: Record<string, unknown>;
  timestamp?: number; // added on frontend
}
