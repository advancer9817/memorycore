"use client";

import { useState, useRef, useEffect, useCallback } from "react";

export function useResizable(initial: number, min: number, max: number, direction: "right" | "left") {
  const [size, setSize] = useState(initial);
  const dragging = useRef(false);
  const startX = useRef(0);
  const startSize = useRef(initial);
  const minRef = useRef(min);
  const maxRef = useRef(max);
  const directionRef = useRef(direction);

  useEffect(() => { minRef.current = min; maxRef.current = max; directionRef.current = direction; }, [min, max, direction]);

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragging.current = true;
    startX.current = e.clientX;
    startSize.current = size;
    const onMove = (ev: MouseEvent) => {
      if (!dragging.current) return;
      const delta = directionRef.current === "right" ? ev.clientX - startX.current : startX.current - ev.clientX;
      setSize(Math.min(maxRef.current, Math.max(minRef.current, startSize.current + delta)));
    };
    const onUp = () => {
      dragging.current = false;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }, [size]);

  return { size, onMouseDown };
}
