import React from 'react';

// TypeScript with JSX test file covering all TSX features

// 1. Basic component with props
interface BasicProps {
  title: string;
  count?: number;
}

const BasicComponent: React.FC<BasicProps> = ({ title, count = 0 }) => (
  <div>
    <h1>{title}</h1>
    <p>Count: {count}</p>
  </div>
);

// 2. Component with state and event handlers
const Counter: React.FC = () => {
  const [count, setCount] = React.useState<number>(0);

  const increment = () => setCount(c => c + 1);
  const decrement = () => setCount(c => c - 1);

  return (
    <div>
      <button onClick={decrement}>-</button>
      <span>{count}</span>
      <button onClick={increment}>+</button>
    </div>
  );
};

// 3. Component with children
const Container: React.FC<{ className?: string }> = ({ className, children }) => (
  <div className={className}>{children}</div>
);

// 4. Component with generic props
interface ListProps<T> {
  items: T[];
  renderItem: (item: T) => React.ReactNode;
}

function List<T>({ items, renderItem }: ListProps<T>) {
  return <ul>{items.map((item, i) => <li key={i}>{renderItem(item)}</li>)}</ul>;
}

// 5. Higher-order component
function withLogger<T>(Component: React.ComponentType<T>) {
  return (props: T) => {
    console.log('Component rendered:', Component.name);
    return <Component {...props} />;
  };
}

const LoggedBasic = withLogger(BasicComponent);

// 6. Context example
const ThemeContext = React.createContext<'light' | 'dark'>('light');

const ThemedButton: React.FC = () => {
  const theme = React.useContext(ThemeContext);
  return <button className={`btn-${theme}`}>Themed Button</button>;
};

// 7. Fragment and conditional rendering
const ConditionalRender: React.FC<{ show: boolean }> = ({ show }) => (
  <>
    {show ? (
      <div>Visible content</div>
    ) : (
      <div hidden>Hidden content</div>
    )}
  </>
);

// 8. Type assertions
const ValueDisplay: React.FC<{ value: unknown }> = ({ value }) => (
  <div>
    {(value as string)?.toUpperCase?.() || 'Not a string'}
  </div>
);

// 9. Component using all features
const App: React.FC = () => {
  const [theme, setTheme] = React.useState<'light' | 'dark'>('light');
  const numbers = [1, 2, 3];
  const strings = ['a', 'b', 'c'];

  return (
    <ThemeContext.Provider value={theme}>
      <Container className="app-container">
        <LoggedBasic title="TSX Test" />
        <Counter />
        
        <List items={numbers} renderItem={n => <span>Number: {n}</span>} />
        <List items={strings} renderItem={s => <span>String: {s}</span>} />
        
        <ThemedButton />
        <button onClick={() => setTheme(t => t === 'light' ? 'dark' : 'light')}>
          Toggle Theme
        </button>
        
        <ConditionalRender show={true} />
        <ValueDisplay value="test" />
        <ValueDisplay value={42} />
      </Container>
    </ThemeContext.Provider>
  );
};

export default App;