// test_class_async.js - Demonstrates classes and async/await.

class ModernClass {
    constructor(name) {
        this.name = name;
    }

    greet() {
        // Simple method call
        console.log(`Hello from ${this.name}!`);
    }

    async asyncOperation() {
        // The tracer should step over the await line
        console.log('Starting async operation...');
        await new Promise(resolve => setTimeout(resolve, 100));
        console.log('...async operation finished.');
        return 42;
    }
}

module.exports = {
    ModernClass,
};