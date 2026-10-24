interface BrandMarkProps {
  size?: number;
  title?: string;
}

/** Urumi brand mark: a "U" that reads as a sprouting leaf. */
export function BrandMark({ size = 20, title }: BrandMarkProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
    >
      {title ? <title>{title}</title> : null}
      <path
        d="M9.5 7.5v10.2a6.5 6.5 0 0 0 13 0V7.5"
        stroke="#ffffff"
        strokeWidth="2.6"
        strokeLinecap="round"
      />
      <path
        d="M22.6 5.1c2.8.6 4.8 2.9 5.1 5.7-2.8.2-5.2-1.8-5.1-5.7Z"
        fill="#9CD3B7"
      />
    </svg>
  );
}
