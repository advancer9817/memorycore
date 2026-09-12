import { useState, useCallback, useEffect, useRef } from 'react';
import axios from 'axios';
import { getErrorMessage } from '@/lib/errors';
import { useDispatch, useSelector } from 'react-redux';
import { AppDispatch, RootState } from '@/store/store';
import {
  App,
  AppDetails,
  AppMemory,
  AccessedMemory,
  setAppsSuccess,
  setAppsError,
  setAppsLoading,
  setSelectedAppLoading,
  setSelectedAppDetails,
  setCreatedMemoriesLoading,
  setCreatedMemoriesSuccess,
  setCreatedMemoriesError,
  setAccessedMemoriesLoading,
  setAccessedMemoriesSuccess,
  setAccessedMemoriesError,
  setSelectedAppError,
} from '@/store/appsSlice';
import { getApiBaseUrl } from '@/lib/api-url';

interface ApiResponse {
  total: number;
  page: number;
  page_size: number;
  apps: App[];
}

interface MemoriesResponse {
  total: number;
  page: number;
  page_size: number;
  memories: AppMemory[];
}

interface AccessedMemoriesResponse {
  total: number;
  page: number;
  page_size: number;
  memories: AccessedMemory[];
}

interface FetchAppsParams {
  name?: string;
  is_active?: boolean;
  sort_by?: 'name' | 'memories' | 'memories_accessed' | 'last_activity' | 'status';
  sort_direction?: 'asc' | 'desc';
  page?: number;
  page_size?: number;
  forceRefresh?: boolean;
}

interface UseAppsApiReturn {
  fetchApps: (params?: FetchAppsParams) => Promise<{ apps: App[], total: number }>;
  fetchAppDetails: (appId: string) => Promise<void>;
  fetchAppMemories: (appId: string, page?: number, pageSize?: number) => Promise<void>;
  fetchAppAccessedMemories: (appId: string, page?: number, pageSize?: number) => Promise<void>;
  updateAppDetails: (appId: string, details: { is_active?: boolean; display_name?: string; description?: string }) => Promise<any>;
  deleteApp: (appId: string) => Promise<{ archived_count: number }>;
  isLoading: boolean;
  error: string | null;
}

export const useAppsApi = (): UseAppsApiReturn => {
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const dispatch = useDispatch<AppDispatch>();
  const user_id = useSelector((state: RootState) => state.profile.userId);
  const lastFetchedAt = useSelector((state: RootState) => state.apps.lastFetchedAt);
  const cachedApps = useSelector((state: RootState) => state.apps.apps);
  const lastFetchedAtRef = useRef(lastFetchedAt);
  const cachedAppsRef = useRef(cachedApps);

  useEffect(() => {
    lastFetchedAtRef.current = lastFetchedAt;
  }, [lastFetchedAt]);

  useEffect(() => {
    cachedAppsRef.current = cachedApps;
  }, [cachedApps]);

  const fetchApps = useCallback(async (params: FetchAppsParams = {}): Promise<{ apps: App[], total: number }> => {
    const {
      name,
      is_active,
      sort_by = 'name',
      sort_direction = 'asc',
      page = 1,
      page_size = 10,
      forceRefresh = false,
    } = params;

    // Skip fetch if cache is fresh and no search filters applied
    const cachedAt = lastFetchedAtRef.current;
    const cached = cachedAppsRef.current;
    if (!forceRefresh && !name && is_active === undefined && page === 1 && cachedAt && Date.now() - cachedAt < 30_000 && cached.length > 0) {
      return { apps: cached, total: cached.length };
    }

    setIsLoading(true);
    dispatch(setAppsLoading());
    try {
      const queryParams = new URLSearchParams({
        page: String(page),
        page_size: String(page_size)
      });

      if (name) queryParams.append('name', name);
      if (is_active !== undefined) queryParams.append('is_active', String(is_active));
      if (sort_by) queryParams.append('sort_by', sort_by);
      if (sort_direction) queryParams.append('sort_direction', sort_direction);

      const response = await axios.get<ApiResponse>(
        `${getApiBaseUrl()}/api/v1/apps?${queryParams.toString()}`
      );

      setIsLoading(false);
      dispatch(setAppsSuccess(response.data.apps));
      return {
        apps: response.data.apps,
        total: response.data.total
      };
    } catch (err: unknown) {
      const errorMessage = getErrorMessage(err, 'Failed to fetch apps');
      setError(errorMessage);
      dispatch(setAppsError(errorMessage));
      setIsLoading(false);
      throw new Error(errorMessage);
    }
  }, [dispatch]); // refs are stable — lastFetchedAtRef/cachedAppsRef don't need to be listed

  const fetchAppDetails = useCallback(async (appId: string): Promise<void> => {
    setIsLoading(true);
    dispatch(setSelectedAppLoading());
    try {
      const response = await axios.get<AppDetails>(
        `${getApiBaseUrl()}/api/v1/apps/${appId}`
      );
      dispatch(setSelectedAppDetails(response.data));
      setIsLoading(false);
    } catch (err: unknown) {
      const errorMessage = getErrorMessage(err, 'Failed to fetch app details');
      dispatch(setSelectedAppError(errorMessage));
      setError(errorMessage);
      setIsLoading(false);
      throw new Error(errorMessage);
    }
  }, [dispatch]);

  const fetchAppMemories = useCallback(async (appId: string, page: number = 1, pageSize: number = 10): Promise<void> => {
    setIsLoading(true);
    dispatch(setCreatedMemoriesLoading());
    try {
      const response = await axios.get<MemoriesResponse>(
        `${getApiBaseUrl()}/api/v1/apps/${appId}/memories?page=${page}&page_size=${pageSize}`
      );
      dispatch(setCreatedMemoriesSuccess({
        items: response.data.memories,
        total: response.data.total,
        page: response.data.page,
      }));
      setIsLoading(false);
    } catch (err: unknown) {
      const errorMessage = getErrorMessage(err, 'Failed to fetch app memories');
      dispatch(setCreatedMemoriesError(errorMessage));
      setError(errorMessage);
      setIsLoading(false);
    }
  }, [dispatch]);

  const fetchAppAccessedMemories = useCallback(async (appId: string, page: number = 1, pageSize: number = 10): Promise<void> => {
    setIsLoading(true);
    dispatch(setAccessedMemoriesLoading());
    try {
      const response = await axios.get<AccessedMemoriesResponse>(
        `${getApiBaseUrl()}/api/v1/apps/${appId}/accessed?page=${page}&page_size=${pageSize}`
      );
      dispatch(setAccessedMemoriesSuccess({
        items: response.data.memories,
        total: response.data.total,
        page: response.data.page,
      }));
      setIsLoading(false);
    } catch (err: unknown) {
      const errorMessage = getErrorMessage(err, 'Failed to fetch accessed memories');
      dispatch(setAccessedMemoriesError(errorMessage));
      setError(errorMessage);
      setIsLoading(false);
    }
  }, [dispatch]);

  const updateAppDetails = async (
    appId: string,
    details: { is_active?: boolean; display_name?: string; description?: string }
  ) => {
    setIsLoading(true);
    try {
      const response = await axios.put(
        `${getApiBaseUrl()}/api/v1/apps/${appId}`,
        details,
        { headers: { "Content-Type": "application/json" } }
      );
      setIsLoading(false);
      return response.data;
    } catch (error) {
      setIsLoading(false);
      throw error;
    }
  };

  const deleteApp = useCallback(async (appId: string): Promise<{ archived_count: number }> => {
    setIsLoading(true);
    try {
      const response = await axios.delete<{ archived_count: number }>(
        `${getApiBaseUrl()}/api/v1/apps/${appId}`
      );
      dispatch(setAppsSuccess(
        (await axios.get<ApiResponse>(
          `${getApiBaseUrl()}/api/v1/apps?page_size=100`
        )).data.apps
      ));
      setIsLoading(false);
      return response.data;
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to delete app';
      setError(errorMessage);
      setIsLoading(false);
      throw new Error(errorMessage);
    }
  }, [dispatch]);

  return {
    fetchApps,
    fetchAppDetails,
    fetchAppMemories,
    fetchAppAccessedMemories,
    updateAppDetails,
    deleteApp,
    isLoading,
    error
  };
};
