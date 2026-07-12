import * as React from 'react';

import { cn } from '@/lib/utils';

const Card = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn(
      'rounded-md border border-border/70 bg-card text-card-foreground shadow-sm',
      className
    )}
    {...props}
  />
));
Card.displayName = 'Card';

type CardDensity = 'default' | 'compact' | 'tight' | 'none';

const cardHeaderDensityClasses: Record<CardDensity, string> = {
  default: 'p-page',
  compact: 'px-5 py-4',
  tight: 'px-3 py-2.5',
  none: 'p-0',
};

type CardHeaderProps = React.HTMLAttributes<HTMLDivElement> & {
  density?: CardDensity;
  divided?: boolean;
};

const CardHeader = React.forwardRef<
  HTMLDivElement,
  CardHeaderProps
>(({ className, density = 'default', divided = false, ...props }, ref) => (
  <div
    ref={ref}
    className={cn(
      'flex flex-col space-y-1.5',
      cardHeaderDensityClasses[density],
      divided && 'border-b border-border/70 bg-card',
      className
    )}
    {...props}
  />
));
CardHeader.displayName = 'CardHeader';

const CardTitle = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLHeadingElement>
>(({ className, ...props }, ref) => (
  <h3
    ref={ref}
    className={cn(
      'text-lg font-semibold leading-none tracking-tight',
      className
    )}
    {...props}
  />
));
CardTitle.displayName = 'CardTitle';

const CardDescription = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className, ...props }, ref) => (
  <p
    ref={ref}
    className={cn('text-sm text-muted-foreground', className)}
    {...props}
  />
));
CardDescription.displayName = 'CardDescription';

const CardContent = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement> & { density?: CardDensity }
>(({ className, density = 'default', ...props }, ref) => (
  <div
    ref={ref}
    className={cn(
      density === 'default' && 'p-page pt-0',
      density === 'compact' && 'px-5 pb-5',
      density === 'tight' && 'px-3 pb-3',
      density === 'none' && 'p-0',
      className
    )}
    {...props}
  />
));
CardContent.displayName = 'CardContent';

const CardFooter = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn('flex items-center p-page pt-0', className)}
    {...props}
  />
));
CardFooter.displayName = 'CardFooter';

export {
  Card,
  CardHeader,
  CardFooter,
  CardTitle,
  CardDescription,
  CardContent,
};
