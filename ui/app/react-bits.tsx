"use client";

import type { ElementType, ReactNode } from "react";

/**
 * A small, dependency-free adaptation of React Bits Split Text.
 * React Bits source: https://reactbits.dev/text-animations/split-text
 *
 * The official component uses GSAP. This project has no animation dependency and only needs a
 * word-level entrance for the page heading, so the same stagger/reveal pattern is implemented with
 * CSS. `prefers-reduced-motion` disables it in globals.css.
 */
export function SplitText({
  text,
  as: Tag = "h1",
  className = "",
  delay = 55,
}: {
  text: string;
  as?: ElementType;
  className?: string;
  delay?: number;
}) {
  const words = text.trim().split(/\s+/).filter(Boolean);
  return (
    <Tag className={`react-bits-split ${className}`} aria-label={text}>
      {words.map((word, index) => (
        <span
          key={`${word}-${index}`}
          aria-hidden="true"
          className="react-bits-word"
          style={{ animationDelay: `${index * delay}ms` }}
        >
          {word}
          {index < words.length - 1 ? "\u00A0" : ""}
        </span>
      ))}
    </Tag>
  );
}

/**
 * A dependency-free adaptation of React Bits Fade Content.
 * React Bits source: https://reactbits.dev/animations/fade-content
 *
 * Content stays fully visible when scroll-driven animations are unsupported, when JavaScript is
 * unavailable, or when the visitor prefers reduced motion.
 */
export function FadeContent({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={`react-bits-fade ${className}`}>{children}</div>;
}
