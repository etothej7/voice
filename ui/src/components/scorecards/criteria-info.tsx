import { useEffect, useRef, useState } from 'react';
import { Info } from 'lucide-react';

import { CRITERIA } from '@/lib/scorecards';
import { cn } from '@/lib/utils';

export function CriteriaInfo({
  align = 'left',
  className,
}: {
  align?: 'left' | 'right';
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (!ref.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false);
    }
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  return (
    <div ref={ref} className={cn('relative inline-flex', className)}>
      <button
        type="button"
        aria-label="What we grade"
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
        className="inline-flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
      >
        <Info className="size-3.5" />
        What we grade
      </button>
      {open && (
        <div
          className={cn(
            'absolute top-full z-20 mt-2 w-80 rounded-md border border-border bg-popover p-4 text-left shadow-md',
            align === 'right' ? 'right-0' : 'left-0'
          )}
        >
          <dl className="space-y-3">
            {CRITERIA.map((c) => (
              <div key={c.key}>
                <dt className="text-sm font-medium text-popover-foreground">{c.label}</dt>
                <dd className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                  {c.description}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </div>
  );
}
