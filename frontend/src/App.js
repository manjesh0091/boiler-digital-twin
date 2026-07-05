import React from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Layout from "@/components/Layout";
import BoilerDashboard from "@/pages/BoilerDashboard";
import CombustionMonitor from "@/pages/CombustionMonitor";

function App() {
  return (
    <div className="App">
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Navigate to="/pai-s01" replace />} />
            <Route path="/pai-s01" element={<BoilerDashboard />} />
            <Route path="/pai-s03" element={<CombustionMonitor />} />
            <Route path="*" element={<Navigate to="/pai-s01" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </div>
  );
}

export default App;
