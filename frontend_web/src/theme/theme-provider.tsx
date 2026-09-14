'use client';

import { createContext, useContext, useLayoutEffect, useMemo } from 'react';

export type Theme = 'light' | 'dark';
export type UserTheme = Theme | 'system';

interface ThemeContextType {
  theme: Theme;
  userTheme: UserTheme;
}

const ThemeContext = createContext<ThemeContextType>({
  theme: 'dark',
  userTheme: 'dark',
});

export const useTheme = () => useContext(ThemeContext);

export const ThemeProvider = ({
  children,
}: {
  children: React.ReactNode | ((props: { theme: Theme }) => React.ReactNode);
}) => {
  const theme: Theme = 'dark';
  const userTheme: UserTheme = 'dark';

  useLayoutEffect(() => {
    document.documentElement.classList.add('dark');
  }, []);

  const value = useMemo(() => ({ theme, userTheme }), []);

  return (
    <ThemeContext.Provider value={value}>
      {typeof children === 'function' ? children({ theme }) : children}
    </ThemeContext.Provider>
  );
};
