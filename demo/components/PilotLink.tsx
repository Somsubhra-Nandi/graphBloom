export default function PilotLink({ className = "", label = "Request a pilot" }: { className?: string; label?: string }) {
  return (
    <a
      href="mailto:somsubhra@tautomatic.ai?subject=GraphBloom%20pilot"
      className={`inline-flex min-h-10 items-center rounded-lg border border-primary/60 px-4 text-sm font-medium text-primary transition-colors hover:bg-primary hover:text-primary-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary ${className}`}
    >
      {label}
    </a>
  );
}
