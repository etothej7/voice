import { Moon, Sun } from 'lucide-react';
import { Link, Outlet } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { useTheme } from '@/lib/theme';

export function AppLayout() {
  const { theme, toggleTheme } = useTheme();

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border/70 bg-card">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-page">
          <Link to="/" className="text-sm font-semibold tracking-tight">
            Rep Performance
          </Link>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Toggle theme"
            onClick={toggleTheme}
          >
            {theme === 'dark' ? <Sun /> : <Moon />}
          </Button>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-page py-6">
        <Outlet />
      </main>
    </div>
  );
}
