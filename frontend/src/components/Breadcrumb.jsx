import React from "react";
import { Link } from "react-router-dom";

export default function Breadcrumb({ current, moduleId }) {
  return (
    <nav aria-label="Breadcrumb" className="flex items-center gap-2 text-[11px] font-mono uppercase tracking-widest">
      <Link
        to="/"
        data-testid="breadcrumb-home"
        className="text-zinc-500 hover:text-zinc-200"
      >
        Home
      </Link>
      <span className="text-zinc-600">/</span>
      <Link
        to="/modules"
        data-testid="breadcrumb-modules"
        className="text-zinc-500 hover:text-zinc-200"
      >
        Modules
      </Link>
      <span className="text-zinc-600">/</span>
      <span className="text-zinc-100" data-testid="breadcrumb-current">
        {moduleId ? `${moduleId} · ${current}` : current}
      </span>
    </nav>
  );
}
