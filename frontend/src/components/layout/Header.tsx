"use client";

import { Search } from "lucide-react";

export default function Header({ title }: { title?: string }) {
  return (
    <header className="h-14 bg-white border-b border-[var(--border-light)] flex items-center justify-between px-6">
      <h1 className="text-lg font-semibold text-gray-900">
        {title || "Dashboard"}
      </h1>

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
        <input
          type="text"
          placeholder="Search..."
          className="pl-9 pr-4 py-2 text-sm bg-gray-50 border border-[var(--border-light)] rounded-lg w-64 focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500 transition-colors"
        />
      </div>
    </header>
  );
}
