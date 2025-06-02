import { createSlice } from '@reduxjs/toolkit';

export const themeSlice = createSlice({
  name: 'theme',
  initialState: {
    mode: localStorage.getItem('themeMode') || 'light'
  },
  reducers: {
    toggleTheme: (state) => {
      state.mode = state.mode === 'light' ? 'dark' : 'light';
      localStorage.setItem('themeMode', state.mode);
    }
  }
});

export const { toggleTheme } = themeSlice.actions;
export default themeSlice.reducer;