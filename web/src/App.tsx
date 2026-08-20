import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppLayout } from "./AppLayout";
import { ChatPage } from "./pages/ChatPage";
import { MemoriesPage } from "./pages/MemoriesPage";
import { ExportsPage } from "./pages/ExportsPage";
import { DataOpsPage } from "./pages/DataOpsPage";
import { MetricsPage } from "./pages/MetricsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { AlertsPage } from "./pages/AlertsPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/" element={<ChatPage />} />
          <Route path="/memories" element={<MemoriesPage />} />
          <Route path="/exports" element={<ExportsPage />} />
          <Route path="/metrics" element={<MetricsPage />} />
          <Route path="/data-ops" element={<DataOpsPage />} />
          <Route path="/alerts" element={<AlertsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
