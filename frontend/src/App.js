import React from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import ModuleLayout from "@/components/Layout";
import Landing from "@/pages/Landing";
import ModuleSelect from "@/pages/ModuleSelect";
import BoilerDashboard from "@/pages/BoilerDashboard";
import CombustionMonitor from "@/pages/CombustionMonitor";

function App() {
  return (
    <div className="App">
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/modules" element={<ModuleSelect />} />
          <Route path="/modules/pai-s01" element={<ModuleLayout />}>
            <Route index element={<BoilerDashboard />} />
          </Route>
          <Route path="/modules/pai-s03" element={<ModuleLayout />}>
            <Route index element={<CombustionMonitor />} />
          </Route>
          {/* Legacy deep-links */}
          <Route path="/pai-s01" element={<Navigate to="/modules/pai-s01" replace />} />
          <Route path="/pai-s03" element={<Navigate to="/modules/pai-s03" replace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </div>
  );
}

export default App;
