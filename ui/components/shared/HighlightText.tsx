import React from "react";

interface HighlightTextProps {
  text: string;
  query: string;
  className?: string;
}

export function HighlightText({ text, query, className = "" }: HighlightTextProps) {
  if (!query || !query.trim() || !text) {
    return <span className={className}>{text}</span>;
  }

  const terms = query
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));

  if (terms.length === 0) {
    return <span className={className}>{text}</span>;
  }

  const regex = new RegExp(`(${terms.join("|")})`, "gi");
  const parts = text.split(regex);

  return (
    <span className={className}>
      {parts.map((part, i) =>
        regex.test(part) ? (
          <mark key={i} className="bg-amber-400/25 text-amber-300 rounded px-0.5 font-medium">
            {part}
          </mark>
        ) : (
          part
        )
      )}
    </span>
  );
}
