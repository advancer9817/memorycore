"use client";

import { useEffect, useMemo, useState } from "react";
import { ChevronDown, Filter, Search, SortAsc, SortDesc } from "lucide-react";
import { useDispatch, useSelector } from "react-redux";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuGroup,
} from "@/components/ui/dropdown-menu";
import { RootState } from "@/store/store";
import { useAppsApi } from "@/hooks/useAppsApi";
import { useFiltersApi } from "@/hooks/useFiltersApi";
import {
  setSelectedApps,
  setSelectedCategories,
  clearFilters,
} from "@/store/filtersSlice";
import { useMemoriesApi } from "@/hooks/useMemoriesApi";
import { useI18n } from "@/hooks/useI18n";
import { MemoryFilterDialog } from "./MemoryFilterDialog";

export default function FilterComponent() {
  const dispatch = useDispatch();
  const { fetchApps } = useAppsApi();
  const { fetchCategories, updateSort } = useFiltersApi();
  const { fetchMemories } = useMemoriesApi();
  const { messages } = useI18n();
  const t = messages.memories;
  const [isOpen, setIsOpen] = useState(false);
  const [tempSelectedApps, setTempSelectedApps] = useState<string[]>([]);
  const [tempSelectedCategories, setTempSelectedCategories] = useState<
    string[]
  >([]);
  const [showArchived, setShowArchived] = useState(false);
  const [categoryQuery, setCategoryQuery] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const columns = useMemo(
    () => [
      { label: t.columnMemory, value: "memory" },
      { label: t.columnAppName, value: "app_name" },
      { label: t.columnCreatedOn, value: "created_at" },
    ],
    [t]
  );

  const apps = useSelector((state: RootState) => state.apps.apps);
  const categories = useSelector(
    (state: RootState) => state.filters.categories.items
  );
  const filters = useSelector((state: RootState) => state.filters.apps);
  const normalizedCategoryQuery = categoryQuery.trim().toLowerCase();
  const filteredCategories = useMemo(
    () =>
      normalizedCategoryQuery
        ? categories.filter((category) =>
            category.name.toLowerCase().includes(normalizedCategoryQuery)
          )
        : categories,
    [categories, normalizedCategoryQuery]
  );

  useEffect(() => {
    fetchApps();
    fetchCategories();
  }, [fetchApps, fetchCategories]);

  useEffect(() => {
    if (isOpen) {
      setTempSelectedApps(filters.selectedApps);
      setTempSelectedCategories(filters.selectedCategories);
      setShowArchived(filters.showArchived || false);
      setDateFrom(filters.dateFrom || "");
      setDateTo(filters.dateTo || "");
    }
  }, [isOpen, filters]);

  useEffect(() => {
    handleClearFilters();
  }, []);

  const toggleAppFilter = (app: string) => {
    setTempSelectedApps((prev) =>
      prev.includes(app) ? prev.filter((a) => a !== app) : [...prev, app]
    );
  };

  const toggleCategoryFilter = (category: string) => {
    setTempSelectedCategories((prev) =>
      prev.includes(category)
        ? prev.filter((c) => c !== category)
        : [...prev, category]
    );
  };

  const toggleAllApps = (checked: boolean) => {
    setTempSelectedApps(checked ? apps.map((app) => app.id) : []);
  };

  const toggleVisibleCategories = (checked: boolean) => {
    const visibleNames = filteredCategories.map((category) => category.name);
    setTempSelectedCategories((current) => {
      if (!checked) {
        return current.filter((category) => !visibleNames.includes(category));
      }

      return Array.from(new Set([...current, ...visibleNames]));
    });
  };

  const handleClearFilters = async () => {
    setTempSelectedApps([]);
    setTempSelectedCategories([]);
    setShowArchived(false);
    setDateFrom("");
    setDateTo("");
    dispatch(clearFilters());
    await fetchMemories();
  };

  const handleApplyFilters = async () => {
    try {
      const selectedCategoryIds = categories
        .filter((cat) => tempSelectedCategories.includes(cat.name))
        .map((cat) => cat.id);

      const selectedAppIds = apps
        .filter((app) => tempSelectedApps.includes(app.id))
        .map((app) => app.id);

      dispatch(setSelectedApps(tempSelectedApps));
      dispatch(setSelectedCategories(tempSelectedCategories));
      dispatch({ type: "filters/setShowArchived", payload: showArchived });

      await fetchMemories(undefined, 1, 10, {
        apps: selectedAppIds,
        categories: selectedCategoryIds,
        sortColumn: filters.sortColumn,
        sortDirection: filters.sortDirection,
        showArchived: showArchived,
        dateFrom: dateFrom || undefined,
        dateTo: dateTo || undefined,
      });
      setIsOpen(false);
    } catch {
      // filter errors are non-fatal — silently ignored
    }
  };

  const handleDialogChange = (open: boolean) => {
    setIsOpen(open);
    if (!open) {
      setTempSelectedApps(filters.selectedApps);
      setTempSelectedCategories(filters.selectedCategories);
      setShowArchived(filters.showArchived || false);
    }
  };

  const setSorting = async (column: string) => {
    const newDirection =
      filters.sortColumn === column && filters.sortDirection === "asc"
        ? "desc"
        : "asc";
    updateSort(column, newDirection);

    const selectedCategoryIds = categories
      .filter((cat) => tempSelectedCategories.includes(cat.name))
      .map((cat) => cat.id);

    const selectedAppIds = apps
      .filter((app) => tempSelectedApps.includes(app.id))
      .map((app) => app.id);

    try {
      await fetchMemories(undefined, 1, 10, {
        apps: selectedAppIds,
        categories: selectedCategoryIds,
        sortColumn: column,
        sortDirection: newDirection,
      });
    } catch {
      // sort errors are non-fatal — silently ignored
    }
  };

  const hasActiveFilters =
    filters.selectedApps.length > 0 ||
    filters.selectedCategories.length > 0 ||
    filters.showArchived ||
    !!dateFrom ||
    !!dateTo;

  const hasTempFilters =
    tempSelectedApps.length > 0 ||
    tempSelectedCategories.length > 0 ||
    showArchived ||
    !!dateFrom ||
    !!dateTo;

  return (
    <div className="flex items-center gap-2">

      <MemoryFilterDialog
        isOpen={isOpen} handleDialogChange={handleDialogChange}
        hasActiveFilters={hasActiveFilters} hasTempFilters={hasTempFilters}
        filters={filters} apps={apps} categories={categories} filteredCategories={filteredCategories}
        tempSelectedApps={tempSelectedApps} tempSelectedCategories={tempSelectedCategories}
        showArchived={showArchived} categoryQuery={categoryQuery} dateFrom={dateFrom} dateTo={dateTo}
        setCategoryQuery={setCategoryQuery} setShowArchived={setShowArchived}
        setDateFrom={setDateFrom} setDateTo={setDateTo}
        toggleAllApps={toggleAllApps} toggleAppFilter={toggleAppFilter}
        toggleVisibleCategories={toggleVisibleCategories} toggleCategoryFilter={toggleCategoryFilter}
        handleClearFilters={handleClearFilters} handleApplyFilters={handleApplyFilters} t={t}
      />

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="outline"
            className="h-9 px-4 border-zinc-700/50 bg-zinc-900 hover:bg-zinc-800"
          >
            {filters.sortDirection === "asc" ? (
              <SortAsc className="h-4 w-4" />
            ) : (
              <SortDesc className="h-4 w-4" />
            )}
            {t.sortPrefix} {columns.find((c) => c.value === filters.sortColumn)?.label}
            <ChevronDown className="h-4 w-4 ml-2" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent className="w-56 bg-zinc-900 border-zinc-800 text-zinc-100">
          <DropdownMenuLabel>{t.sortBy}</DropdownMenuLabel>
          <DropdownMenuSeparator className="bg-zinc-800" />
          <DropdownMenuGroup>
            {columns.map((column) => (
              <DropdownMenuItem
                key={column.value}
                onClick={() => setSorting(column.value)}
                className="cursor-pointer flex justify-between items-center"
              >
                {column.label}
                {filters.sortColumn === column.value &&
                  (filters.sortDirection === "asc" ? (
                    <SortAsc className="h-4 w-4 text-primary" />
                  ) : (
                    <SortDesc className="h-4 w-4 text-primary" />
                  ))}
              </DropdownMenuItem>
            ))}
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
