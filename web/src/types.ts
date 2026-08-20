export type MessageBlock = {
  type: string;
  content?: string;
  columns?: string[];
  rows?: unknown[][];
  metric_code?: string;
  value?: number;
  unit?: string;
  name?: string;
  url?: string;
  kind?: string;
  title?: string;
  id?: string;
  question?: string;
  options?: string[];
  actions?: string[];
};

export type ResponseMeta = {
  data_as_of: string;
  shops: string[];
  channels: string[];
  model: string;
  trace_id: string;
};

export type AgentResponse = {
  session_id: string;
  run_id: string;
  status: string;
  blocks: MessageBlock[];
  meta: ResponseMeta | null;
};

export type Session = {
  session_id: string;
  title: string;
  status: string;
  shop_id: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
};

export type SessionDetail = Session & {
  messages: Array<{
    role: string;
    content: string;
    blocks: MessageBlock[];
    run_id?: string | null;
    created_at: string;
  }>;
};

export type MemoryItem = {
  id: string;
  topic: string;
  conclusion: string;
  time_range: string;
  shop_ids: string[];
  metrics: string[];
  importance: number;
  data_as_of: string;
  created_at: string;
  trusted: boolean;
};

export type ExportItem = {
  id: string;
  name: string;
  status: string;
  created_at: string;
  expires_at: string;
  download_url: string;
};

export type MetricDef = {
  metric_code: string;
  name: string;
  aliases: string[];
  formula: string;
  grain: string;
  latency: string;
  channels: string[];
  common_misuse: string;
  version: string;
};

export type Me = {
  tenant_id: string;
  user_id: string;
  shop_ids: string[];
  roles: string[];
  is_owner: boolean;
};
