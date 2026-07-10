import { useState, useCallback, useEffect, useRef } from 'react';
import axios from 'axios';
import { Memory, Client, Category } from '@/components/types';
import { useDispatch, useSelector } from 'react-redux';
import { AppDispatch, RootState } from '@/store/store';
import { setAccessLogs, setMemoriesSuccess, setSelectedMemory, setRelatedMemories } from '@/store/memoriesSlice';
import { getApiBaseUrl } from '@/lib/api-url';
import { getErrorMessage } from '@/lib/errors';

const CACHE_TTL_MS = 30_000;

// Define the new simplified memory type
export interface SimpleMemory {
  id: string;
  text: string;
  created_at: string;
  state: string;
  categories: string[];
  app_name: string;
  valid_from?: string;
  valid_until?: string;
}

// Define the shape of the API response item
interface ApiMemoryItem {
  id: string;
  content: string;
  created_at: string;
  state: string;
  app_id: string;
  categories: string[];
  metadata_?: Record<string, unknown>;
  app_name: string;
}

// Define the shape of the API response
interface ApiResponse {
  items: ApiMemoryItem[];
  total: number;
  page: number;
  size: number;
  pages: number;
}

interface AccessLogEntry {
  id: string;
  app_name: string;
  accessed_at: string;
}

interface AccessLogResponse {
  total: number;
  page: number;
  page_size: number;
  logs: AccessLogEntry[];
}

interface RelatedMemoryItem {
  id: string;
  content: string;
  created_at: number;
  state: string;
  app_id: string;
  app_name: string;
  categories: string[];
  metadata_: Record<string, any>;
}

interface RelatedMemoriesResponse {
  items: RelatedMemoryItem[];
  total: number;
  page: number;
  size: number;
  pages: number;
}

interface UseMemoriesApiReturn {
  fetchMemories: (
    query?: string,
    page?: number,
    size?: number,
    filters?: {
      apps?: string[];
      categories?: string[];
      sortColumn?: string;
      sortDirection?: 'asc' | 'desc';
      showArchived?: boolean;
      dateFrom?: string;
      dateTo?: string;
    },
    forceRefresh?: boolean
  ) => Promise<{ memories: Memory[]; total: number; pages: number }>;
  fetchMemoryById: (memoryId: string) => Promise<void>;
  fetchAccessLogs: (memoryId: string, page?: number, pageSize?: number) => Promise<void>;
  fetchRelatedMemories: (memoryId: string) => Promise<void>;
  createMemory: (text: string) => Promise<void>;
  deleteMemories: (memoryIds: string[]) => Promise<void>;
  updateMemory: (memoryId: string, content: string) => Promise<void>;
  updateMemoryState: (memoryIds: string[], state: string) => Promise<void>;
  updateValidityRange: (memoryId: string, validFrom: string, validUntil: string) => Promise<void>;
  isLoading: boolean;
  error: string | null;
  hasUpdates: number;
  memories: Memory[];
  selectedMemory: SimpleMemory | null;
}

export const useMemoriesApi = (): UseMemoriesApiReturn => {
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [hasUpdates, setHasUpdates] = useState<number>(0);
  const dispatch = useDispatch<AppDispatch>();
  const user_id = useSelector((state: RootState) => state.profile.userId);
  const memories = useSelector((state: RootState) => state.memories.memories);
  const selectedMemory = useSelector((state: RootState) => state.memories.selectedMemory);
  const lastFetchedAt = useSelector((state: RootState) => state.memories.lastFetchedAt);
  const memoriesRef = useRef(memories);
  const lastFetchedAtRef = useRef(lastFetchedAt);

  useEffect(() => {
    memoriesRef.current = memories;
  }, [memories]);

  useEffect(() => {
    lastFetchedAtRef.current = lastFetchedAt;
  }, [lastFetchedAt]);

  const fetchMemories = useCallback(async (
    query?: string,
    page: number = 1,
    size: number = 10,
    filters?: {
      apps?: string[];
      categories?: string[];
      sortColumn?: string;
      sortDirection?: 'asc' | 'desc';
      showArchived?: boolean;
      dateFrom?: string;
      dateTo?: string;
    },
    forceRefresh: boolean = false
  ): Promise<{ memories: Memory[], total: number, pages: number }> => {
    // Skip fetch if cached data is fresh and this is a plain first-page load
    const isDefaultLoad =
      !query &&
      page === 1 &&
      !filters?.apps?.length &&
      !filters?.categories?.length &&
      !filters?.sortColumn &&
      !filters?.sortDirection &&
      filters?.showArchived === undefined &&
      !filters?.dateFrom &&
      !filters?.dateTo;
    const cachedMemories = memoriesRef.current;
    const cachedAt = lastFetchedAtRef.current;
    if (!forceRefresh && isDefaultLoad && cachedAt && Date.now() - cachedAt < CACHE_TTL_MS && cachedMemories.length > 0) {
      return { memories: cachedMemories, total: cachedMemories.length, pages: 1 };
    }
    setIsLoading(true);
    setError(null);
    try {
      const response = await axios.post<ApiResponse>(
        `${getApiBaseUrl()}/api/v1/memories/filter`,
        {
          user_id: user_id,
          page: page,
          size: size,
          search_query: query,
          app_ids: filters?.apps,
          category_ids: filters?.categories,
          sort_column: filters?.sortColumn?.toLowerCase(),
          sort_direction: filters?.sortDirection,
          show_archived: filters?.showArchived,
          date_from: filters?.dateFrom || undefined,
          date_to: filters?.dateTo || undefined,
        }
      );

      const adaptedMemories: Memory[] = response.data.items.map((item: ApiMemoryItem) => ({
        id: item.id,
        memory: item.content,
        created_at: new Date(item.created_at).getTime(),
        state: item.state as "active" | "paused" | "archived" | "deleted",
        metadata: item.metadata_ ?? {},
        categories: item.categories as Category[],
        client: 'api',
        app_name: item.app_name
      }));
      setIsLoading(false);
      dispatch(setMemoriesSuccess(adaptedMemories));
      return {
        memories: adaptedMemories,
        total: response.data.total,
        pages: response.data.pages
      };
    } catch (err: unknown) {
      const errorMessage = getErrorMessage(err, 'Failed to fetch memories');
      setError(errorMessage);
      setIsLoading(false);
      throw new Error(errorMessage);
    }
  }, [dispatch, user_id]);

  const createMemory = async (text: string): Promise<void> => {
    try {
      const memoryData = {
        user_id: user_id,
        text: text,
        infer: false,
        app: "memorycore",
      }
      await axios.post<ApiMemoryItem>(`${getApiBaseUrl()}/api/v1/memories/`, memoryData);
    } catch (err: unknown) {
      const errorMessage = getErrorMessage(err, 'Failed to create memory');
      setError(errorMessage);
      setIsLoading(false);
      throw new Error(errorMessage);
    }
  };

  const deleteMemories = async (memory_ids: string[]) => {
    try {
      await axios.delete(`${getApiBaseUrl()}/api/v1/memories/`, {
        data: { memory_ids, user_id }
      });
      dispatch(setMemoriesSuccess(memories.filter((memory: Memory) => !memory_ids.includes(memory.id))));
    } catch (err: unknown) {
      const errorMessage = getErrorMessage(err, 'Failed to delete memories');
      setError(errorMessage);
      setIsLoading(false);
      throw new Error(errorMessage);
    }
  };

  const fetchMemoryById = async (memoryId: string): Promise<void> => {
    if (memoryId === "") {
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      const response = await axios.get<SimpleMemory>(
        `${getApiBaseUrl()}/api/v1/memories/${memoryId}?user_id=${user_id}`
      );
      setIsLoading(false);
      dispatch(setSelectedMemory(response.data));
    } catch (err: unknown) {
      const errorMessage = getErrorMessage(err, 'Failed to fetch memory');
      setError(errorMessage);
      setIsLoading(false);
      throw new Error(errorMessage);
    }
  };

  const fetchAccessLogs = async (memoryId: string, page: number = 1, pageSize: number = 10): Promise<void> => {
    if (memoryId === "") {
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      const response = await axios.get<AccessLogResponse>(
        `${getApiBaseUrl()}/api/v1/memories/${memoryId}/access-log?page=${page}&page_size=${pageSize}`
      );
      setIsLoading(false);
      dispatch(setAccessLogs(response.data.logs));
    } catch (err: unknown) {
      const errorMessage = getErrorMessage(err, 'Failed to fetch access logs');
      setError(errorMessage);
      setIsLoading(false);
      throw new Error(errorMessage);
    }
  };

  const fetchRelatedMemories = async (memoryId: string): Promise<void> => {
    if (memoryId === "") {
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      const response = await axios.get<RelatedMemoriesResponse>(
        `${getApiBaseUrl()}/api/v1/memories/${memoryId}/related?user_id=${user_id}`
      );

      const adaptedMemories: Memory[] = response.data.items.map((item: RelatedMemoryItem) => ({
        id: item.id,
        memory: item.content,
        created_at: item.created_at,
        state: item.state as "active" | "paused" | "archived" | "deleted",
        metadata: item.metadata_,
        categories: item.categories as Category[],
        client: 'api',
        app_name: item.app_name
      }));

      setIsLoading(false);
      dispatch(setRelatedMemories(adaptedMemories));
    } catch (err: unknown) {
      const errorMessage = getErrorMessage(err, 'Failed to fetch related memories');
      setError(errorMessage);
      setIsLoading(false);
      throw new Error(errorMessage);
    }
  };

  const updateMemory = async (memoryId: string, content: string): Promise<void> => {
    if (memoryId === "") {
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      await axios.put(`${getApiBaseUrl()}/api/v1/memories/${memoryId}`, {
        memory_id: memoryId,
        memory_content: content,
        user_id: user_id
      });
      setIsLoading(false);
      setHasUpdates(hasUpdates + 1);
    } catch (err: unknown) {
      const errorMessage = getErrorMessage(err, 'Failed to update memory');
      setError(errorMessage);
      setIsLoading(false);
      throw new Error(errorMessage);
    }
  };

  const updateMemoryState = async (memoryIds: string[], state: string): Promise<void> => {
    if (memoryIds.length === 0) {
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      await axios.post(`${getApiBaseUrl()}/api/v1/memories/actions/pause`, {
        memory_ids: memoryIds,
        all_for_app: true,
        state: state,
        user_id: user_id
      });
      dispatch(setMemoriesSuccess(memories.map((memory: Memory) => {
        if (memoryIds.includes(memory.id)) {
          return { ...memory, state: state as "active" | "paused" | "archived" | "deleted" };
        }
        return memory;
      })));

      // If archive, delete the memory
      if (state === "archived") {
        dispatch(setMemoriesSuccess(memories.filter((memory: Memory) => !memoryIds.includes(memory.id))));
      }

      // if selected memory, update it
      if (selectedMemory?.id && memoryIds.includes(selectedMemory.id)) {
        dispatch(setSelectedMemory({ ...selectedMemory, state: state as "active" | "paused" | "archived" | "deleted" }));
      }

      setIsLoading(false);
      setHasUpdates(hasUpdates + 1);
    } catch (err: unknown) {
      const errorMessage = getErrorMessage(err, 'Failed to update memory state');
      setError(errorMessage);
      setIsLoading(false);
      throw new Error(errorMessage);
    }
  };

  const updateValidityRange = async (memoryId: string, validFrom: string, validUntil: string): Promise<void> => {
    if (memoryId === "") return;
    setIsLoading(true);
    setError(null);
    try {
      const body: Record<string, string> = {};
      if (validFrom) body.valid_from = validFrom;
      if (validUntil) body.valid_until = validUntil;
      await axios.patch(`${getApiBaseUrl()}/memories/${memoryId}`, body);
      if (selectedMemory?.id === memoryId) {
        dispatch(setSelectedMemory({ ...selectedMemory, valid_from: validFrom, valid_until: validUntil }));
      }
      setIsLoading(false);
      setHasUpdates(hasUpdates + 1);
    } catch (err: unknown) {
      const errorMessage = getErrorMessage(err, 'Failed to update validity range');
      setError(errorMessage);
      setIsLoading(false);
      throw new Error(errorMessage);
    }
  };

  return {
    fetchMemories,
    fetchMemoryById,
    fetchAccessLogs,
    fetchRelatedMemories,
    createMemory,
    deleteMemories,
    updateMemory,
    updateMemoryState,
    updateValidityRange,
    isLoading,
    error,
    hasUpdates,
    memories,
    selectedMemory
  };
};
