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
  },
});

export const {
  openUpdateMemoryDialog,
  closeUpdateMemoryDialog,
  setLocale,
} = uiSlice.actions;

export default uiSlice.reducer;