#ifndef BASIC_SO2_H
#define BASIC_SO2_H

int so2_function(int y);
void so2_init();

// Export data symbol
extern volatile int so2_data_symbol;
int so2_plt_function(int) __attribute__((visibility("default")));

#endif