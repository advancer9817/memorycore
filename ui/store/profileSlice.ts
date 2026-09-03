import { createSlice, PayloadAction } from '@reduxjs/toolkit';

interface ProfileState {
  userId: string;
  totalMemories: number;
  totalApps: number;
  status: 'idle' | 'loading' | 'succeeded' | 'failed';
  error: string | null;
  apps: any[];
  lastFetchedAt: number | null;
}

const initialState: ProfileState = {
  userId: process.env.NEXT_PUBLIC_USER_ID || 'user',
  totalMemories: 0,
  totalApps: 0,
  status: 'idle',
  error: null,
  apps: [],
  lastFetchedAt: null,
};

const profileSlice = createSlice({
  name: 'profile',
  initialState,
  reducers: {
    setUserId: (state, action: PayloadAction<string>) => {
      state.userId = action.payload;
    },
    setProfileLoading: (state) => {
      state.status = 'loading';
      state.error = null;
    },
    setProfileError: (state, action: PayloadAction<string>) => {
      state.status = 'failed';
      state.error = action.payload;
    },
    resetProfileState: (state) => {
      state.status = 'idle';
      state.error = null;
      state.userId = process.env.NEXT_PUBLIC_USER_ID || 'user';
      state.lastFetchedAt = null;
      state.totalMemories = 0;
      state.totalApps = 0;
      state.apps = [];
    },
    setTotalMemories: (state, action: PayloadAction<number>) => {
      state.totalMemories = action.payload;
      state.lastFetchedAt = Date.now();
    },
    setTotalApps: (state, action: PayloadAction<number>) => {
      state.totalApps = action.payload;
    },
    setApps: (state, action: PayloadAction<any[]>) => {
      state.apps = action.payload;
    }
  },
});

export const {
  setUserId,
  setProfileLoading,
  setProfileError,
  resetProfileState,
  setTotalMemories,
  setTotalApps,
  setApps
} = profileSlice.actions;

export default profileSlice.reducer;