import { createSlice } from '@reduxjs/toolkit';

export const historySlice = createSlice({
  name: 'history',
  initialState: {
    items: JSON.parse(localStorage.getItem('executionHistory')) || []
  },
  reducers: {
    addHistoryItem: (state, action) => {
      state.items = [action.payload, ...state.items].slice(0, 20);
      localStorage.setItem('executionHistory', JSON.stringify(state.items));
    },
    clearHistory: (state) => {
      state.items = [];
      localStorage.removeItem('executionHistory');
    }
  }
});

export const { addHistoryItem, clearHistory } = historySlice.actions;
export default historySlice.reducer;