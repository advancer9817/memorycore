import { createSlice, PayloadAction } from '@reduxjs/toolkit';

export interface LLMConfig {
  model: string;
  temperature: number;
  max_tokens: number;
  api_key?: string;
  ollama_base_url?: string;
}

export interface LLMProvider {
  provider: string;
  config: LLMConfig;
}

export interface EmbedderConfig {
  model: string;
  api_key?: string;
  ollama_base_url?: string;
}

export interface EmbedderProvider {
  provider: string;
  config: EmbedderConfig;
}

export interface LLMBackendConfig {
  llm?: LLMProvider;
  embedder?: EmbedderProvider;
}

export interface MemoryCoreConfig {
  custom_instructions?: string | null;
}

export interface RuleCuratorConfig {
  decay_step?: number;
  decay_interval_days?: number;
  decay_min_confidence?: number;
  candidate_ttl_episodic_days?: number;
  candidate_ttl_precious_days?: number;
  candidate_ttl_default_days?: number;
  stale_days_episodic?: number;
  archive_days_episodic?: number;
  stale_days_default?: number;
  archive_days_default?: number;
  contradicted_archive_days?: number;
  never_accessed_candidate_days?: number;
  promote_importance_threshold?: number;
  promote_injected_threshold?: number;
  precious_types?: string[];
  stale_importance_threshold?: number;
  stale_feedback_threshold?: number;
  precious_stale_feedback?: number;
  precious_stale_importance?: number;
  revival_window_days?: number;
  revival_effectiveness_min?: number;
  revival_feedback_min?: number;
  skill_promote_importance?: number;
  skill_promote_feedback_min?: number;
}

export interface LlmCuratorConfig {
  sim_threshold?: number;
  batch_size?: number;
  importance_limit?: number;
  split_content_threshold?: number;
  review_cooldown_seconds?: number;
  reviewed_ids_max_age_seconds?: number;
}

export interface GovernanceConfig {
  review_confidence_threshold?: number;
  high_importance_threshold?: number;
  auto_approve_confidence?: number;
  auto_approve_low_risk_confidence?: number;
  precious_types?: string[];
  manual_only_actions?: string[];
  merge_actions?: string[];
}

export interface ExtractionStrategyConfig {
  min_importance?: number;
  default_confidence?: number;
  default_importance?: number;
  chinese_detection_ratio?: number;
  skip_threshold?: number;
  update_threshold?: number;
  link_threshold?: number;
  context_sample_length?: number;
  context_memory_limit?: number;
  dedup_search_limit?: number;
  max_related_ids?: number;
  default_memory_type?: string;
  default_status?: string;
  default_decay_policy?: string;
  title_max_length?: number;
  default_scope?: string;
}

export interface StrategyConfig {
  rule_curator?: RuleCuratorConfig;
  llm_curator?: LlmCuratorConfig;
  governance?: GovernanceConfig;
  extraction_strategy?: ExtractionStrategyConfig;
}

export interface ConfigState {
  settings: MemoryCoreConfig;
  llm: LLMBackendConfig;
  strategy: StrategyConfig;
  status: 'idle' | 'loading' | 'succeeded' | 'failed';
  error: string | null;
}

const initialState: ConfigState = {
  settings: {
    custom_instructions: null,
  },
  llm: {
    llm: {
      provider: 'openai',
      config: {
        model: 'gpt-4o-mini',
        temperature: 0.1,
        max_tokens: 2000,
        api_key: 'env:OPENAI_API_KEY',
      },
    },
    embedder: {
      provider: 'openai',
      config: {
        model: 'text-embedding-3-small',
        api_key: 'env:OPENAI_API_KEY',
      },
    },
  },
  strategy: {},
  status: 'idle',
  error: null,
};

const configSlice = createSlice({
  name: 'config',
  initialState,
  reducers: {
    setConfigLoading: (state) => {
      state.status = 'loading';
      state.error = null;
    },
    setConfigSuccess: (state, action: PayloadAction<{ settings?: MemoryCoreConfig; llm?: LLMBackendConfig; strategy?: StrategyConfig }>) => {
      if (action.payload.settings) {
        state.settings = action.payload.settings;
      }
      if (action.payload.llm) {
        state.llm = action.payload.llm;
      }
      if (action.payload.strategy) {
        state.strategy = action.payload.strategy;
      }
      state.status = 'succeeded';
      state.error = null;
    },
    setConfigError: (state, action: PayloadAction<string>) => {
      state.status = 'failed';
      state.error = action.payload;
    },
    updateMemoryCoreConfig: (state, action: PayloadAction<MemoryCoreConfig>) => {
      state.settings = action.payload;
    },
    updateLLMProvider: (state, action: PayloadAction<LLMProvider>) => {
      state.llm.llm = action.payload;
    },
    updateEmbedderProvider: (state, action: PayloadAction<EmbedderProvider>) => {
      state.llm.embedder = action.payload;
    },
    updateLLMBackendConfig: (state, action: PayloadAction<LLMBackendConfig>) => {
      state.llm = action.payload;
    },
    updateStrategy: (state, action: PayloadAction<StrategyConfig>) => {
      state.strategy = action.payload;
    },
  },
});

export const {
  setConfigLoading,
  setConfigSuccess,
  setConfigError,
  updateMemoryCoreConfig,
  updateLLMProvider,
  updateEmbedderProvider,
  updateLLMBackendConfig,
  updateStrategy,
} = configSlice.actions;

export default configSlice.reducer;
