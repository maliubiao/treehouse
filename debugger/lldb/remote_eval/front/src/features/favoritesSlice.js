import { createSlice } from '@reduxjs/toolkit';

export const favoritesSlice = createSlice({
  name: 'favorites',
  initialState: {
    items: JSON.parse(localStorage.getItem('favorites')) || []
  },
  reducers: {
    addFavorite: (state, action) => {
      state.items = [action.payload, ...state.items];
      localStorage.setItem('favorites', JSON.stringify(state.items));
    },
    removeFavorite: (state, action) => {
      state.items = state.items.filter(item => item.id !== action.payload);
      localStorage.setItem('favorites', JSON.stringify(state.items));
    }
  }
});

export const { addFavorite, removeFavorite } = favoritesSlice.actions;
export default favoritesSlice.reducer;