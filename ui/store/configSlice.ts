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

export interface ConfigState {
  settings: MemoryCoreConfig;
  llm: LLMBackendConfig;
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
    setConfigSuccess: (state, action: PayloadAction<{ settings?: MemoryCoreConfig; llm?: LLMBackendConfig }>) => {
      if (action.payload.settings) {
        state.settings = action.payload.settings;
      }
      if (action.payload.llm) {
        state.llm = action.payload.llm;
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
} = configSlice.actions;

export default configSlice.reducer;
