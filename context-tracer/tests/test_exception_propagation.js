/**
 * Test script for JavaScript exception propagation and Node.js debugger behavior.
 * This script creates a deep call stack with local and global variables,
 * throws and catches exceptions at certain depths, and ends with an uncaught exception.
 */

// Global variable
let globalVar = "I am a global variable";

/**
 * Recursive function to simulate deep call stack and exception propagation.
 * @param {number} depth - Current recursion depth.
 * @param {number} maxDepth - Maximum recursion depth before throwing uncaught exception.
 */
function recursiveFunction(depth, maxDepth) {
    // Local variable
    let localVar = `Depth: ${depth}, globalVar: ${globalVar}`;
    console.log(localVar);

    // Check if max depth is reached
    if (depth >= maxDepth) {
        throw new Error("Uncaught exception at max depth");
    }

    try {
        // At depth 3, throw an exception that will be caught locally
        if (depth === 3) {
            throw new Error("Exception at depth 3");
        }
        // Recursive call to increase stack depth
        recursiveFunction(depth + 1, maxDepth);
    } catch (error) {
        console.log(`Caught at depth ${depth}: ${error.message}`);
        // Re-throw the exception to propagate it up the call stack
        throw error;
    }
}

// Start the recursion from depth 0 without top-level try-catch
// This ensures the exception remains uncaught at the top level
recursiveFunction(0, 10);