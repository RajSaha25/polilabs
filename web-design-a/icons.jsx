/* global React */
// Polilabs — icon glyphs. All inline SVG, 14px default. Stroke 1.5.

const Icon = ({ name, size = 14, className = "i", strokeWidth = 1.5, ...rest }) => {
  const s = size;
  const sw = strokeWidth;
  const common = {
    width: s, height: s, viewBox: "0 0 24 24",
    fill: "none", stroke: "currentColor",
    strokeWidth: sw, strokeLinecap: "round", strokeLinejoin: "round",
    className, ...rest
  };
  switch (name) {
    case "search":
      return (
        <svg {...common}>
          <circle cx="11" cy="11" r="6.5" />
          <path d="M16 16l4 4" />
        </svg>
      );
    case "arrow-right":
      return (
        <svg {...common}>
          <path d="M5 12h14" />
          <path d="M13 6l6 6-6 6" />
        </svg>
      );
    case "arrow-up":
      return (
        <svg {...common}>
          <path d="M12 19V5" />
          <path d="M6 11l6-6 6 6" />
        </svg>
      );
    case "chevron-left":
      return <svg {...common}><path d="M14 6l-6 6 6 6" /></svg>;
    case "chevron-right":
      return <svg {...common}><path d="M10 6l6 6-6 6" /></svg>;
    case "chevron-down":
      return <svg {...common}><path d="M6 9l6 6 6-6" /></svg>;
    case "check":
      return <svg {...common}><path d="M5 12l4 4 10-10" /></svg>;
    case "link":
      return (
        <svg {...common}>
          <path d="M10 14a4 4 0 005.66 0l3-3a4 4 0 10-5.66-5.66l-1 1" />
          <path d="M14 10a4 4 0 00-5.66 0l-3 3a4 4 0 105.66 5.66l1-1" />
        </svg>
      );
    case "anchor":
      return (
        <svg {...common}>
          <path d="M9 7h6v2a3 3 0 11-6 0V7z" />
          <path d="M12 11v9" />
          <path d="M5 17a7 7 0 007 3 7 7 0 007-3" />
        </svg>
      );
    case "doc":
      return (
        <svg {...common}>
          <path d="M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8l-5-5z" />
          <path d="M14 3v5h5" />
          <path d="M9 13h6M9 17h4" />
        </svg>
      );
    case "filter":
      return (
        <svg {...common}>
          <path d="M3 5h18" />
          <path d="M6 12h12" />
          <path d="M10 19h4" />
        </svg>
      );
    case "scope":
      return (
        <svg {...common}>
          <rect x="3" y="4" width="18" height="16" rx="2" />
          <path d="M3 9h18" />
          <path d="M9 4v5" />
        </svg>
      );
    case "sparkle":
      return (
        <svg {...common}>
          <path d="M12 3l1.6 4.4L18 9l-4.4 1.6L12 15l-1.6-4.4L6 9l4.4-1.6L12 3z" />
          <path d="M19 16l.6 1.6L21 18l-1.4.4L19 20l-.6-1.6L17 18l1.4-.4L19 16z" />
        </svg>
      );
    case "diff":
      return (
        <svg {...common}>
          <path d="M8 4v16" />
          <path d="M16 4v16" />
          <path d="M4 8l4-4 4 4" />
          <path d="M20 16l-4 4-4-4" />
        </svg>
      );
    case "list-tree":
      return (
        <svg {...common}>
          <path d="M5 5h14" />
          <path d="M9 12h10" />
          <path d="M13 19h6" />
        </svg>
      );
    case "quote":
      return (
        <svg {...common}>
          <path d="M7 8h3v3a3 3 0 01-3 3" />
          <path d="M14 8h3v3a3 3 0 01-3 3" />
        </svg>
      );
    case "shield":
      return (
        <svg {...common}>
          <path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z" />
        </svg>
      );
    case "x":
      return <svg {...common}><path d="M6 6l12 12M18 6L6 18" /></svg>;
    case "info":
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="9" />
          <path d="M12 11v5" />
          <circle cx="12" cy="8" r="0.5" fill="currentColor" />
        </svg>
      );
    case "swap":
      return (
        <svg {...common}>
          <path d="M3 8h14" />
          <path d="M13 4l4 4-4 4" />
          <path d="M21 16H7" />
          <path d="M11 12l-4 4 4 4" />
        </svg>
      );
    case "scales":
      return (
        <svg {...common}>
          <path d="M12 3v18" />
          <path d="M5 21h14" />
          <path d="M5 8l3 7H2l3-7z" />
          <path d="M19 8l3 7h-6l3-7z" />
          <path d="M5 8h14" />
        </svg>
      );
    default:
      return null;
  }
};

window.Icon = Icon;
