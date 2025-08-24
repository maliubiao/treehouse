import { createSlice } from '@reduxjs/toolkit';

export const codeSlice = createSlice({
  name: 'code',
  initialState: {
    content: '',
    output: '',
    isExecuting: false,
    error: null
  },
  reducers: {
    setCode: (state, action) => {
      state.content = action.payload;
    },
    setOutput: (state, action) => {
      state.output = action.payload;
      state.error = null;
    },
    setError: (state, action) => {
      state.error = action.payload;
      state.output = '';
    },
    setExecuting: (state, action) => {
      state.isExecuting = action.payload;
    }
  }
});

export const { setCode, setOutput, setError, setExecuting } = codeSlice.actions;
export default codeSlice.reducer;