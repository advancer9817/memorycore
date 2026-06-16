"use client";
import { useEffect, useState, useMemo } from "react";
import { Search, ChevronDown, SortAsc, SortDesc } from "lucide-react";
import { useDispatch, useSelector } from "react-redux";
import {
  setSearchQuery,
  setActiveFilter,
  setSortBy,
  setSortDirection,
} from "@/store/appsSlice";
import { RootState } from "@/store/store";
import { useCallback } from "react";
import debounce from "lodash/debounce";
import { useAppsApi } from "@/hooks/useAppsApi";
import { AppFiltersSkeleton } from "@/skeleton/AppFiltersSkeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuGroup,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/hooks/useI18n";

type SortByValue = "name" | "memories" | "memories_accessed" | "last_activity" | "status";

export function AppFilters() {
  const dispatch = useDispatch();
  const filters = useSelector((state: RootState) => state.apps.filters);
  const [localSearch, setLocalSearch] = useState(filters.searchQuery);
  const { isLoading } = useAppsApi();
  const { messages } = useI18n();
  const t = messages.apps;

  const sortOptions = useMemo(
    () => [
      { value: "name", label: t.sortName },
      { value: "memories", label: t.sortMemoriesCreated },
      { value: "memories_accessed", label: t.sortMemoriesAccessed },
      { value: "last_activity", label: t.sortLastActivity },
      { value: "status", label: t.sortStatus },
    ],
    [t]
  );

  const debouncedSearch = useCallback(
    debounce((query: string) => {
      dispatch(setSearchQuery(query));
    }, 300),
    [dispatch]
  );

  const handleSearchChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const query = e.target.value;
    setLocalSearch(query);
    debouncedSearch(query);
  };

  const handleActiveFilterChange = (value: string) => {
    dispatch(setActiveFilter(value === "all" ? "all" : value === "true"));
  };

  const setSorting = (sortBy: SortByValue) => {
    const newDirection =
      filters.sortBy === sortBy && filters.sortDirection === "asc"
        ? "desc"
        : "asc";
    dispatch(setSortBy(sortBy));
    dispatch(setSortDirection(newDirection));
  };

  useEffect(() => {
    setLocalSearch(filters.searchQuery);
  }, [filters.searchQuery]);

  if (isLoading) {
    return <AppFiltersSkeleton />;
  }

  return (
    <div className="flex items-center gap-2">
      <div className="relative flex-1">
        <Search className="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
        <Input
          placeholder={t.searchPlaceholder}
          className="pl-8 bg-zinc-950 border-zinc-800 max-w-[500px]"
          value={localSearch}
          onChange={handleSearchChange}
        />
      </div>

      <Select
        value={String(filters.isActive)}
        onValueChange={handleActiveFilterChange}
      >
        <SelectTrigger className="w-[130px] border-zinc-700/50 bg-zinc-900 hover:bg-zinc-800">
          <SelectValue placeholder={t.allStatus} />
        </SelectTrigger>
        <SelectContent className="border-zinc-700/50 bg-zinc-900 hover:bg-zinc-800">
          <SelectItem value="all">{t.allStatus}</SelectItem>
          <SelectItem value="true">{t.statusActive}</SelectItem>
          <SelectItem value="false">{t.statusInactive}</SelectItem>
        </SelectContent>
      </Select>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="outline"
            className="h-9 px-4 border-zinc-700 bg-zinc-900 hover:bg-zinc-800"
          >
            {filters.sortDirection === "asc" ? (
              <SortDesc className="h-4 w-4 mr-2" />
            ) : (
              <SortAsc className="h-4 w-4 mr-2" />
            )}
            {t.sortPrefix} {sortOptions.find((o) => o.value === filters.sortBy)?.label}
            <ChevronDown className="h-4 w-4 ml-2" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent className="w-56 bg-zinc-900 border-zinc-800 text-zinc-100">
          <DropdownMenuLabel>{t.sortBy}</DropdownMenuLabel>
          <DropdownMenuSeparator className="bg-zinc-800" />
          <DropdownMenuGroup>
            {sortOptions.map((option) => (
              <DropdownMenuItem
                key={option.value}
                onClick={() => setSorting(option.value as SortByValue)}
                className="cursor-pointer flex justify-between items-center"
              >
                {option.label}
                {filters.sortBy === option.value &&
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
