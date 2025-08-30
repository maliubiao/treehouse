// test_main.js - Entry point for line tracing test
const path = require('node:path'); // Test blacklisting of node internal modules
const { formatMessage } = require('./test_utils.js'); // Test blacklisting a specific file
const { recursiveCountdown } = require('./test_recursion.js');
const { ModernClass } = require('./test_class_async.js');

console.log('--- Starting complex JS test for line tracer ---');

let globalVar = 100;

function mainTraceFunction(param1, param2) {
    console.log('Inside mainTraceFunction');
    let localVar = param1 + param2;

    // Simple for loop
    let loopSum = 0;
    for (let i = 0; i < 5; i++) {
        loopSum += i;
    }
    console.log('Loop sum:', loopSum);

    // Call a blacklisted utility function
    const formatted = formatMessage('hello tracer');
    console.log('Formatted message (from blacklisted file):', formatted);

    // Call a recursive function
    recursiveCountdown(3);

    const modern = new ModernClass('Tracer');
    modern.greet();
    
    globalVar += localVar;
    
    console.log('About to trigger the debugger for line tracing...');
    debugger; // <<<< TRACE STARTS HERE
    
    // This part of the code will be traced line-by-line
    let afterDebuggerVar = 'step 1';
    console.log(afterDebuggerVar);
    afterDebuggerVar = 'step 2';
    const finalResult = path.join('a', 'b', 'c'); // Another call to a blacklisted module
    console.log('Path join result:', finalResult);

    // Call an async function
    modern.asyncOperation().then(() => {
        console.log('Async operation completed after tracing function finished.');
    });

    return 'Trace completed';
}


mainTraceFunction(5, 10);

console.log('--- Test script finished ---');
