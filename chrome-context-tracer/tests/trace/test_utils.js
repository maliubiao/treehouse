// test_utils.js - This file should be blacklisted by the tracer.

function formatMessage(message) {
    // The tracer should step OVER this function call, not into it.
    const upperMessage = message.toUpperCase();
    return `[Formatted]: ${upperMessage}`;
}

module.exports = {
    formatMessage,
};