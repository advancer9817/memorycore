import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import { DEFAULT_LOCALE, Locale } from '@/lib/i18n/types';

interface DialogState {
  updateMemory: {
    isOpen: boolean;
    memoryId: string | null;
    memoryContent: string | null;
  };
}

interface LanguageState {
  locale: Locale;
}

interface UIState {
  dialogs: DialogState;
  language: LanguageState;
  dashboardRefreshKey: number;
  graphRefreshKey: number;
  governanceRefreshKey: number;
}

const initialState: UIState = {
  dialogs: {
    updateMemory: {
      isOpen: false,
      memoryId: null,
      memoryContent: null,
    },
  },
  language: {
    locale: DEFAULT_LOCALE,
  },
  dashboardRefreshKey: 0,
  graphRefreshKey: 0,
  governanceRefreshKey: 0,
};

const uiSlice = createSlice({
  name: 'ui',
  initialState,
  reducers: {
    openUpdateMemoryDialog: (state, action: PayloadAction<{ memoryId: string; memoryContent: string }>) => ({
      ...state,
      dialogs: {
        ...state.dialogs,
        updateMemory: {
          ...state.dialogs.updateMemory,
          isOpen: true,
          memoryId: action.payload.memoryId,
          memoryContent: action.payload.memoryContent,
        },
      },
    }),
    closeUpdateMemoryDialog: (state) => ({
      ...state,
      dialogs: {
        ...state.dialogs,
        updateMemory: {
          ...state.dialogs.updateMemory,
          isOpen: false,
          memoryId: null,
          memoryContent: null,
        },
      },
    }),
    setLocale: (state, action: PayloadAction<Locale>) => ({
      ...state,
      language: {
        ...state.language,
        locale: action.payload,
      },
    }),
    requestDashboardRefresh: (state) => ({
      ...state,
      dashboardRefreshKey: state.dashboardRefreshKey + 1,
    }),
    requestGraphRefresh: (state) => ({
      ...state,
      graphRefreshKey: state.graphRefreshKey + 1,
    }),
    requestGovernanceRefresh: (state) => ({
      ...state,
      governanceRefreshKey: state.governanceRefreshKey + 1,
    }),
  },
});

export const {
  openUpdateMemoryDialog,
  closeUpdateMemoryDialog,
  setLocale,
  requestDashboardRefresh,
  requestGraphRefresh,
  requestGovernanceRefresh,
} = uiSlice.actions;

export default uiSlice.reducer;