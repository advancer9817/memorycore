"use client";

import { ReactNode } from "react";
import { Provider } from "react-redux";
import { I18nProvider } from "@/lib/i18n/I18nProvider";
import { store } from "../store/store";

interface ProvidersProps {
  children: ReactNode;
}

export function Providers({ children }: ProvidersProps) {
  return (
    <Provider store={store}>
      <I18nProvider>{children}</I18nProvider>
    </Provider>
  );
}
