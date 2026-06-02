import { useState } from 'react';
import axios from 'axios';
import { useDispatch } from 'react-redux';
import { AppDispatch } from '@/store/store';
import {
  setConfigLoading,
  setConfigSuccess,
  setConfigError,
  updateLLMProvider,
  updateEmbedderProvider,
  updateLLMBackendConfig,
  updateMemoryCoreConfig,
  LLMProvider,
  EmbedderProvider,
  LLMBackendConfig,
  MemoryCoreConfig,
} from '@/store/configSlice';
import { getApiBaseUrl } from '@/lib/api-url';

interface UseConfigApiReturn {
  fetchConfig: () => Promise<void>;
  saveConfig: (config: { settings?: MemoryCoreConfig; llm?: LLMBackendConfig }) => Promise<void>;
  saveLLMConfig: (llmConfig: LLMProvider) => Promise<void>;
  saveEmbedderConfig: (embedderConfig: EmbedderProvider) => Promise<void>;
  resetConfig: () => Promise<void>;
  isLoading: boolean;
  error: string | null;
}

export const useConfig = (): UseConfigApiReturn => {
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const dispatch = useDispatch<AppDispatch>();

  const fetchConfig = async () => {
    setIsLoading(true);
    dispatch(setConfigLoading());
    try {
      const response = await axios.get(`${getApiBaseUrl()}/api/v1/config`);
      dispatch(setConfigSuccess(response.data));
      setIsLoading(false);
    } catch (err: any) {
      const errorMessage = err.response?.data?.detail || err.message || 'Failed to fetch configuration';
      dispatch(setConfigError(errorMessage));
      setError(errorMessage);
      setIsLoading(false);
      throw new Error(errorMessage);
    }
  };

  const saveConfig = async (config: { settings?: MemoryCoreConfig; llm?: LLMBackendConfig }) => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await axios.put(`${getApiBaseUrl()}/api/v1/config`, config);
      dispatch(setConfigSuccess(response.data));
      setIsLoading(false);
      return response.data;
    } catch (err: any) {
      const errorMessage = err.response?.data?.detail || err.message || 'Failed to save configuration';
      dispatch(setConfigError(errorMessage));
      setError(errorMessage);
      setIsLoading(false);
      throw new Error(errorMessage);
    }
  };

  const resetConfig = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await axios.post(`${getApiBaseUrl()}/api/v1/config/reset`);
      dispatch(setConfigSuccess(response.data));
      setIsLoading(false);
      return response.data;
    } catch (err: any) {
      const errorMessage = err.response?.data?.detail || err.message || 'Failed to reset configuration';
      dispatch(setConfigError(errorMessage));
      setError(errorMessage);
      setIsLoading(false);
      throw new Error(errorMessage);
    }
  };

  const saveLLMConfig = async (llmConfig: LLMProvider) => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await axios.put(`${getApiBaseUrl()}/api/v1/config/llm/extraction`, llmConfig);
      dispatch(updateLLMProvider(response.data));
      setIsLoading(false);
      return response.data;
    } catch (err: any) {
      const errorMessage = err.response?.data?.detail || err.message || 'Failed to save LLM configuration';
      setError(errorMessage);
      setIsLoading(false);
      throw new Error(errorMessage);
    }
  };

  const saveEmbedderConfig = async (embedderConfig: EmbedderProvider) => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await axios.put(`${getApiBaseUrl()}/api/v1/config/llm/embedding`, embedderConfig);
      dispatch(updateEmbedderProvider(response.data));
      setIsLoading(false);
      return response.data;
    } catch (err: any) {
      const errorMessage = err.response?.data?.detail || err.message || 'Failed to save Embedder configuration';
      setError(errorMessage);
      setIsLoading(false);
      throw new Error(errorMessage);
    }
  };

  return {
    fetchConfig,
    saveConfig,
    saveLLMConfig,
    saveEmbedderConfig,
    resetConfig,
    isLoading,
    error,
  };
};
