"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Archive,
  ChevronDown,
  Pause,
  Play,
  Search,
  SortAsc,
  SortDesc,
} from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import debounce from "lodash/debounce";
import { useDispatch, useSelector } from "react-redux";

import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { FiTrash2Icon as FiTrash2 } from "@/components/shared/react-icons";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { RootState } from "@/store/store";
import { clearSelection } from "@/store/memoriesSlice";
import {
  clearFilters,
  setSelectedApps,
  setSelectedCategories,
} from "@/store/filtersSlice";
import { useAppsApi } from "@/hooks/useAppsApi";
import { useFiltersApi } from "@/hooks/useFiltersApi";
import { useMemoriesApi } from "@/hooks/useMemoriesApi";
import { useI18n } from "@/hooks/useI18n";
import { useToast } from "@/hooks/use-toast";
import { MemoryFilterDialog } from "./MemoryFilterDialog";

export function MemoryFilters() {
  const dispatch = useDispatch();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { messages } = useI18n();
  const { toast } = useToast();
  const t = messages.memories;

  const { fetchApps } = useAppsApi();
  const { fetchCategories, updateSort } = useFiltersApi();
  const { deleteMemories, updateMemoryState, fetchMemories } = useMemoriesApi();

  const selectedMemoryIds = useSelector(
    (state: RootState) => state.memories.selectedMemoryIds
  );
  const apps = useSelector((state: RootState) => state.apps.apps);
  const categories = useSelector(
    (state: RootState) => state.filters.categories.items
  );
  const filters = useSelector((state: RootState) => state.filters.apps);

  // 搜索框引用与状态
  const inputRef = useRef<HTMLInputElement>(null);
  const searchParamsRef = useRef(searchParams);
  searchParamsRef.current = searchParams;

  // 弹窗与临时筛选状态
  const [isOpen, setIsOpen] = useState(false);
  const [tempSelectedApps, setTempSelectedApps] = useState<string[]>([]);
  const [tempSelectedCategories, setTempSelectedCategories] = useState<string[]>([]);
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
    if (searchParams.get("search") && inputRef.current) {
      inputRef.current.value = searchParams.get("search") || "";
      inputRef.current.focus();
    }
  }, [searchParams]);

  useEffect(() => {
    if (isOpen) {
      setTempSelectedApps(filters.selectedApps);
      setTempSelectedCategories(filters.selectedCategories);
      setShowArchived(filters.showArchived || false);
      setDateFrom(filters.dateFrom || "");
      setDateTo(filters.dateTo || "");
    }
  }, [isOpen, filters]);

  const handleSearch = useMemo(
    () =>
      debounce((query: string) => {
        const params = new URLSearchParams(searchParamsRef.current.toString());
        if (query) {
          params.set("search", query);
        } else {
          params.delete("search");
        }
        params.set("page", "1");
        router.push(`/memories?${params.toString()}`);
      }, 500),
    [router]
  );

  const handleDeleteSelected = async () => {
    try {
      await deleteMemories(selectedMemoryIds);
      dispatch(clearSelection());
    } catch {
      toast({
        title: messages.common.error,
        description: messages.memories.deleteSelected,
        variant: "destructive",
      });
    }
  };

  const handleArchiveSelected = async () => {
    try {
      await updateMemoryState(selectedMemoryIds, "archived");
    } catch {
      toast({
        title: messages.common.error,
        description: messages.memories.archiveSelected,
        variant: "destructive",
      });
    }
  };

  const handlePauseSelected = async () => {
    try {
      await updateMemoryState(selectedMemoryIds, "paused");
    } catch {
      toast({
        title: messages.common.error,
        description: messages.memories.pauseSelected,
        variant: "destructive",
      });
    }
  };

  const handleResumeSelected = async () => {
    try {
      await updateMemoryState(selectedMemoryIds, "active");
    } catch {
      toast({
        title: messages.common.error,
        description: messages.memories.resumeSelected,
        variant: "destructive",
      });
    }
  };

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
      // filter errors are non-fatal
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
      // sort errors are non-fatal
    }
  };

  const hasActiveFilters =
    filters.selectedApps.length > 0 ||
    filters.selectedCategories.length > 0 ||
    filters.showArchived ||
    !!filters.dateFrom ||
    !!filters.dateTo;

  const hasTempFilters =
    tempSelectedApps.length > 0 ||
    tempSelectedCategories.length > 0 ||
    showArchived ||
    !!dateFrom ||
    !!dateTo;

  return (
    <div className="flex flex-col md:flex-row gap-4 mb-4">
      <div className="relative flex-1">
        <Search className="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
        <Input
          ref={inputRef}
          placeholder={messages.memories.searchPlaceholder}
          className="pl-8 bg-zinc-950 border-zinc-800 max-w-[500px]"
          onChange={(e) => handleSearch(e.target.value)}
        />
      </div>

      <div className="flex items-center gap-2">
        <MemoryFilterDialog
          isOpen={isOpen}
          handleDialogChange={handleDialogChange}
          hasActiveFilters={hasActiveFilters}
          hasTempFilters={hasTempFilters}
          filters={filters}
          apps={apps}
          categories={categories}
          filteredCategories={filteredCategories}
          tempSelectedApps={tempSelectedApps}
          tempSelectedCategories={tempSelectedCategories}
          showArchived={showArchived}
          categoryQuery={categoryQuery}
          dateFrom={dateFrom}
          dateTo={dateTo}
          setCategoryQuery={setCategoryQuery}
          setShowArchived={setShowArchived}
          setDateFrom={setDateFrom}
          setDateTo={setDateTo}
          toggleAllApps={toggleAllApps}
          toggleAppFilter={toggleAppFilter}
          toggleVisibleCategories={toggleVisibleCategories}
          toggleCategoryFilter={toggleCategoryFilter}
          handleClearFilters={handleClearFilters}
          handleApplyFilters={handleApplyFilters}
          t={t}
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
              {t.sortPrefix}{" "}
              {columns.find((c) => c.value === filters.sortColumn)?.label}
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

        {hasActiveFilters && (
          <Button
            variant="outline"
            className="bg-zinc-900 text-zinc-300 hover:bg-zinc-800"
            onClick={handleClearFilters}
          >
            {messages.memories.clearAll}
          </Button>
        )}

        {selectedMemoryIds.length > 0 && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="outline"
                className="border-zinc-700/50 bg-zinc-900 hover:bg-zinc-800"
              >
                {messages.memories.actions}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="end"
              className="bg-zinc-900 border-zinc-800"
            >
              <DropdownMenuItem onClick={handleArchiveSelected}>
                <Archive className="mr-2 h-4 w-4" />
                {messages.memories.archiveSelected}
              </DropdownMenuItem>
              <DropdownMenuItem onClick={handlePauseSelected}>
                <Pause className="mr-2 h-4 w-4" />
                {messages.memories.pauseSelected}
              </DropdownMenuItem>
              <DropdownMenuItem onClick={handleResumeSelected}>
                <Play className="mr-2 h-4 w-4" />
                {messages.memories.resumeSelected}
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={handleDeleteSelected}
                className="text-red-500"
              >
                <FiTrash2 className="mr-2 h-4 w-4" />
                {messages.memories.deleteSelected}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
    </div>
  );
}
