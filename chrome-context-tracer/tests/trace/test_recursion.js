// test_recursion.js - A simple recursive function for tracing.

function recursiveCountdown(n) {
    // The tracer should step into this function multiple times.
    console.log('Countdown:', n);
    if (n <= 0) {
        console.log('Reached base case.');
        return;
    }
    recursiveCountdown(n - 1);
    // The tracer should show execution returning here after the recursive call.
    console.log('Returning from countdown:', n);
}

module.exports = {
    recursiveCountdown,
};