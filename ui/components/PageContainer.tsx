"use client";

import { ReactNode } from "react";
import { useSelector } from "react-redux";
import { RootState } from "@/store/store";

export function PageContainer({ children }: { children: ReactNode }) {
  const pageRefreshKey = useSelector((state: RootState) => state.ui.pageRefreshKey);

  return (
    <div key={pageRefreshKey} style={{ display: "contents" }}>
      {children}
    </div>
  );
}
