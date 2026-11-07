// Small line-icon set (24x24, stroke). Decorative by default: aria-hidden.
const P: Record<string, string> = {
  home: "M3 11.5 12 4l9 7.5M5.5 9.5V20h5v-6h3v6h5V9.5",
  courses: "M4 5.5A1.5 1.5 0 0 1 5.5 4H20v14H5.5A1.5 1.5 0 0 0 4 19.5v-14ZM4 19.5A1.5 1.5 0 0 0 5.5 21H20M8 8h8M8 11.5h6",
  coverage: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
  metrics: "M4 20V10M10 20V4M16 20v-7M22 20H2",
  review: "M9 11.5 11.5 14 16 9M5 3.5h14v17H5z",
  materials: "M3 7.5 12 3l9 4.5-9 4.5-9-4.5ZM3 12l9 4.5 9-4.5M3 16.5 12 21l9-4.5",
  drafts: "M4 20h4L19.5 8.5a2.1 2.1 0 0 0-3-3L5 17v3ZM14.5 7.5l3 3",
  builder: "M8 4h8v3H8zM6 5.5H4V21h16V5.5h-2M8 12h8M8 16h5",
  grading: "M3 12.5 8.5 18 21 5.5",
  lms: "M4 6h16v10H4zM2 20h20M9 16v4M15 16v4",
  lock: "M6 11h12v9H6zM8.5 11V8a3.5 3.5 0 0 1 7 0v3",
  upload: "M12 16V4M7 9l5-5 5 5M4 16v4h16v-4",
  menu: "M4 6h16M4 12h16M4 18h16",
  chevron: "M9 6l6 6-6 6",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM4 21c0-4 3.6-6.5 8-6.5s8 2.5 8 6.5",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM12 11v6M12 7.5v.5",
  check: "M5 12.5 10 17.5 19 7",
  file: "M6 3h8l4 4v14H6zM14 3v4h4",
};

export default function Icon({ name, size = 18, className }: { name: keyof typeof P | string; size?: number; className?: string }) {
  return (
    <svg className={`ico ${className ?? ""}`} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d={P[name] ?? P.file} />
    </svg>
  );
}
