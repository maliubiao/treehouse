class TestClass {
    
    // Existing methods
    public void simpleMethod() {}
    
    private String methodWithParameters(int a, boolean b) {
        return b ? String.valueOf(a) : "false";
    }
    
    protected <T> List<T> genericMethod(Set<T> input) {
        return new ArrayList<>(input);
    }
    
    // New test cases
    @Deprecated
    public void deprecatedAnnotationMethod() {
        System.out.println("Deprecated method");
    }

    public void varargsMethod(String... args) {
        for (int i = 0; i < args.length; i++) {
            System.out.println(args[i]);
        }
    }

    public <T extends Comparable<T>> T boundedGenericMethod(T first, T second) {
        return first.compareTo(second) > 0 ? first : second;
    }

    public static synchronized void staticSynchronizedMethod() {
        synchronized(TestClass.class) {
            System.out.println("Double synchronization");
        }
    }

    public int[] arrayReturnTypeMethod() {
        return new int[]{1, 2, 3};
    }

    public void complexThrows() throws 
        IOException, 
        ArrayIndexOutOfBoundsException, 
        SecurityException {
        throw new IOException("Multiple exceptions");
    }

    @SuppressWarnings("unchecked")
    public final <@NonNull T> void typeAnnotationMethod(T param) {
        List<String> list = (List<String>) new ArrayList();
    }

    public void lambdaParameterMethod(Runnable r) {
        new Thread(() -> {
            r.run();
            System.out.println("Nested lambda");
        }).start();
    }

    public strictfp double calculateStrict() {
        return 1.0 / 3.0;
    }

    public void tryWithResourcesMethod() throws Exception {
        try (AutoCloseable ac = () -> {}) {
            System.out.println("Try-with-resources");
        }
    }

    public <T> void nestedGenericMethod(Set<Map<String, List<T>>> complexParam) {
        class LocalClass<T> {
            public void localClassMethod(T t) {}
        }
        new LocalClass<T>().localClassMethod(null);
    }

    public TestClass chainableMethod() {
        return this;
    }

    public void methodWithAnonymousClass() {
        new Object() {
            public void anonymousMethod() {
                System.out.println("Anonymous class method");
            }
        }.anonymousMethod();
    }

    /* Multi-line
       comment method */
    public void commentedMethod(
        int /*
              weird comment placement
            */ parameter
    ) {
        // empty method
    }
}

@FunctionalInterface
interface TestInterface {
    void functionalMethod();
    
    default void interfaceDefaultMethod() {
        System.out.println("Java 8 default method");
    }
    
    static void interfaceStaticMethod() {
        throw new UnsupportedOperationException();
    }
}

enum TestEnum {
    FIRST {
        public void enumAnonymousMethod() {
            System.out.println("Specialized enum method");
        }
    };
    
    public abstract void enumAnonymousMethod();
}

@interface CustomAnnotation {
    String value() default "";
    Class<?> type() default Object.class;
}
