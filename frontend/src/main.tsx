import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { AuthProvider } from "./state";
import { ToastProvider } from "./ui";
import { LangProvider } from "./i18n";
import "./styles.css";

// Since 1.3 the main address shows the public website and EHMS lives under /staff. Old staff links such as
// http://hotel/#/reservations keep working: they are sent on to /staff#/reservations.
{
  const { pathname, hash, search } = window.location;
  const publicHash = /^#\/(book|survey)\//.test(hash);
  if (!pathname.startsWith("/staff") && pathname !== "/payment-return" && hash.startsWith("#/") && !publicHash) {
    window.location.replace("/staff" + search + hash);
  }
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <LangProvider>
    <ToastProvider>
      <AuthProvider>
        <App />
      </AuthProvider>
    </ToastProvider>
    </LangProvider>
  </React.StrictMode>
);
