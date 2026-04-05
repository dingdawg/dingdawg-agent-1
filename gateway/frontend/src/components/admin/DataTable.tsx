"use client";

/**
 * DataTable — sortable, paginated, searchable data table for admin views.
 *
 * Features:
 *   - Column definitions with header, accessor key, and sortable flag
 *   - Client-side sort (toggle asc/desc per column)
 *   - Search input filters across all string values
 *   - Pagination controls (prev/next + page indicator)
 *   - Horizontal scroll on mobile
 *   - Dark theme matching Command Center design system
 */

import { useState, useMemo } from "react";
import { cn } from "@/lib/utils";

export interface ColumnDef<T> {
  header: string;
  accessor: keyof T;
  sortable?: boolean;
  render?: (value: T[keyof T], row: T) => React.ReactNode;
  className?: string;
}

interface DataTableProps<T extends object> {
  columns: ColumnDef<T>[];
  data: T[];
  pageSize?: number;
  searchable?: boolean;
  searchPlaceholder?: string;
  emptyMessage?: string;
  isLoading?: boolean;
  className?: string;
}

type SortDir = "asc" | "desc" | null;

function SortIcon({ dir }: { dir: SortDir }) {
  return (
    <span className="ml-1 inline-flex flex-col gap-px opacity-60">
      <span className={cn("block w-0 h-0 border-l-[4px] border-r-[4px] border-b-[5px] border-l-transparent border-r-transparent", dir === "asc" ? "border-b-[var(--gold-400)]" : "border-b-gray-500")} />
      <span className={cn("block w-0 h-0 border-l-[4px] border-r-[4px] border-t-[5px] border-l-transparent border-r-transparent", dir === "desc" ? "border-t-[var(--gold-400)]" : "border-t-gray-500")} />
    </span>
  );
}

export default function DataTable<T extends object>({
  columns,
  data,
  pageSize = 10,
  searchable = true,
  searchPlaceholder = "Search...",
  emptyMessage = "No data found.",
  isLoading = false,
  className,
}: DataTableProps<T>) {
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<keyof T | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>(null);
  const [page, setPage] = useState(1);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return data;
    return data.filter((row) =>
      Object.values(row).some((v) =>
        String(v ?? "").toLowerCase().includes(q)
      )
    );
  }, [data, query]);

  const sorted = useMemo(() => {
    if (!sortKey || !sortDir) return filtered;
    return [...filtered].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      const aStr = String(av ?? "");
      const bStr = String(bv ?? "");
      const cmp = aStr.localeCompare(bStr, undefined, { numeric: true });
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [filtered, sortKey, sortDir]);

  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const pageSlice = sorted.slice((safePage - 1) * pageSize, safePage * pageSize);

  function handleSort(col: ColumnDef<T>) {
    if (!col.sortable) return;
    if (sortKey !== col.accessor) {
      setSortKey(col.accessor);
      setSortDir("asc");
    } else if (sortDir === "asc") {
      setSortDir("desc");
    } else {
      setSortKey(null);
      setSortDir(null);
    }
    setPage(1);
  }

  function handleSearch(v: string) {
    setQuery(v);
    setPage(1);
  }

  const colCount = columns.length;

  return (
    <div className={cn("flex flex-col gap-3", className)}>
      {searchable && (
        <div className="flex">
          <input
            type="search"
            value={query}
            onChange={(e) => handleSearch(e.target.value)}
            placeholder={searchPlaceholder}
            className="w-full sm:w-64 bg-[#0d1926] border border-[#1a2a3d] rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-[var(--gold-400)] transition-colors"
          />
        </div>
      )}

      <div className="overflow-x-auto rounded-xl border border-[#1a2a3d]">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="border-b border-[#1a2a3d] bg-[#0a1520]">
              {columns.map((col) => (
                <th
                  key={String(col.accessor)}
                  onClick={() => handleSort(col)}
                  className={cn(
                    "px-4 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wide whitespace-nowrap select-none",
                    col.sortable && "cursor-pointer hover:text-white transition-colors",
                    col.className
                  )}
                >
                  <span className="inline-flex items-center">
                    {col.header}
                    {col.sortable && (
                      <SortIcon
                        dir={sortKey === col.accessor ? sortDir : null}
                      />
                    )}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              Array.from({ length: 4 }).map((_, i) => (
                <tr key={i} className="border-b border-[#1a2a3d]">
                  {columns.map((col) => (
                    <td key={String(col.accessor)} className="px-4 py-3">
                      <div className="h-4 bg-[#1a2a3d] rounded animate-pulse w-3/4" />
                    </td>
                  ))}
                </tr>
              ))
            ) : pageSlice.length === 0 ? (
              <tr>
                <td
                  colSpan={colCount}
                  className="px-4 py-8 text-center text-gray-500 text-sm"
                >
                  {emptyMessage}
                </td>
              </tr>
            ) : (
              pageSlice.map((row, i) => (
                <tr
                  key={i}
                  className="border-b border-[#1a2a3d] last:border-0 hover:bg-white/[0.02] transition-colors"
                >
                  {columns.map((col) => (
                    <td
                      key={String(col.accessor)}
                      className={cn("px-4 py-3 text-white", col.className)}
                    >
                      {col.render
                        ? col.render(row[col.accessor], row)
                        : String(row[col.accessor] ?? "")}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between text-xs text-gray-400">
          <span>
            {sorted.length} result{sorted.length !== 1 ? "s" : ""}
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={safePage === 1}
              className="px-3 py-1.5 rounded-lg bg-[#0d1926] border border-[#1a2a3d] disabled:opacity-40 disabled:cursor-not-allowed hover:border-[var(--gold-400)] transition-colors min-h-[36px]"
            >
              Prev
            </button>
            <span className="px-2">
              {safePage} / {totalPages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={safePage === totalPages}
              className="px-3 py-1.5 rounded-lg bg-[#0d1926] border border-[#1a2a3d] disabled:opacity-40 disabled:cursor-not-allowed hover:border-[var(--gold-400)] transition-colors min-h-[36px]"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
