import axios from "axios";

interface ApiErrorPayload {
  detail?: string;
  error?: { message?: string };
  message?: string;
}

export function getErrorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError<ApiErrorPayload>(error)) {
    return error.response?.data?.detail
      ?? error.response?.data?.error?.message
      ?? error.response?.data?.message
      ?? error.message
      ?? fallback;
  }
  return error instanceof Error ? error.message : fallback;
}
