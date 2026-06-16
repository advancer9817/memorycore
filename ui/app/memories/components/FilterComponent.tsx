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
    filters.showArchived;

  const hasTempFilters =
    tempSelectedApps.length > 0 ||
    tempSelectedCategories.length > 0 ||
    showArchived;

  return (
    <div className="flex items-center gap-2">
      <Dialog open={isOpen} onOpenChange={handleDialogChange}>
        <DialogTrigger asChild>
          <Button
            variant="outline"
            className={`h-9 px-4 border-zinc-700/50 bg-zinc-900 hover:bg-zinc-800 ${
              hasActiveFilters ? "border-primary" : ""
            }`}
          >
            <Filter
              className={`h-4 w-4 ${hasActiveFilters ? "text-primary" : ""}`}
            />
            {t.filter}
            {hasActiveFilters && (
              <Badge className="ml-2 bg-primary hover:bg-primary/80 text-xs">
                {filters.selectedApps.length +
                  filters.selectedCategories.length +
                  (filters.showArchived ? 1 : 0)}
              </Badge>
            )}
          </Button>
        </DialogTrigger>
        <DialogContent className="sm:max-w-[425px] bg-zinc-900 border-zinc-800 text-zinc-100">
          <DialogHeader>
            <DialogTitle className="text-zinc-100 flex justify-between items-center">
              <span>{t.filters}</span>
            </DialogTitle>
          </DialogHeader>
          <Tabs defaultValue="apps" className="w-full">
            <TabsList className="grid grid-cols-3 bg-zinc-800">
              <TabsTrigger
                value="apps"
                className="data-[state=active]:bg-zinc-700"
              >
                {t.tabApps}
              </TabsTrigger>
              <TabsTrigger
                value="categories"
                className="data-[state=active]:bg-zinc-700"
              >
                {t.tabCategories}
              </TabsTrigger>
              <TabsTrigger
                value="archived"
                className="data-[state=active]:bg-zinc-700"
              >
                {t.tabArchived}
              </TabsTrigger>
            </TabsList>
            <TabsContent value="apps" className="mt-4">
              <div className="space-y-3">
                <div className="flex items-center space-x-2">
                  <Checkbox
                    id="select-all-apps"
                    checked={
                      apps.length > 0 && tempSelectedApps.length === apps.length
                    }
                    onCheckedChange={(checked) =>
                      toggleAllApps(checked as boolean)
                    }
                    className="border-zinc-600 data-[state=checked]:bg-primary data-[state=checked]:border-primary"
                  />
                  <Label
                    htmlFor="select-all-apps"
                    className="text-sm font-normal text-zinc-300 cursor-pointer"
                  >
                    {t.selectAll}
                  </Label>
                </div>
                {apps.map((app) => (
                  <div key={app.id} className="flex items-center space-x-2">
                    <Checkbox
                      id={`app-${app.id}`}
                      checked={tempSelectedApps.includes(app.id)}
                      onCheckedChange={() => toggleAppFilter(app.id)}
                      className="border-zinc-600 data-[state=checked]:bg-primary data-[state=checked]:border-primary"
                    />
                    <Label
                      htmlFor={`app-${app.id}`}
                      className="text-sm font-normal text-zinc-300 cursor-pointer"
                    >
                      {app.name}
                    </Label>
                  </div>
                ))}
              </div>
            </TabsContent>
            <TabsContent value="categories" className="mt-4">
              <div className="space-y-3">
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
                  <Input
                    value={categoryQuery}
                    onChange={(event) => setCategoryQuery(event.target.value)}
                    placeholder={t.searchCategoriesPlaceholder}
                    aria-label={t.searchCategoriesPlaceholder}
                    className="h-9 border-zinc-700 bg-zinc-950 pl-9 text-sm text-zinc-100 placeholder:text-zinc-500"
                  />
                </div>
                <div className="flex items-center justify-between gap-3 rounded-lg border border-zinc-800 bg-zinc-950/55 px-3 py-2">
                  <div className="flex items-center space-x-2">
                    <Checkbox
                      id="select-visible-categories"
                      checked={
                        filteredCategories.length > 0 &&
                        filteredCategories.every((category) =>
                          tempSelectedCategories.includes(category.name)
                        )
                      }
                      onCheckedChange={(checked) =>
                        toggleVisibleCategories(checked as boolean)
                      }
                      className="border-zinc-600 data-[state=checked]:bg-primary data-[state=checked]:border-primary"
                    />
                    <Label
                      htmlFor="select-visible-categories"
                      className="cursor-pointer text-sm font-normal text-zinc-300"
                    >
                      {t.selectVisible}
                    </Label>
                  </div>
                  <span className="text-xs text-zinc-500">
                    {t.shownCount(filteredCategories.length, categories.length, tempSelectedCategories.length)}
                  </span>
                </div>
                <div className="max-h-72 space-y-2 overflow-y-auto rounded-lg border border-zinc-800 bg-zinc-950/35 p-2 pr-3">
                  {filteredCategories.length > 0 ? (
                    filteredCategories.map((category) => (
                      <div
                        key={category.name}
                        className="flex items-center space-x-2 rounded-md px-1 py-1.5 hover:bg-zinc-800/60"
                      >
                        <Checkbox
                          id={`category-${category.id}`}
                          checked={tempSelectedCategories.includes(category.name)}
                          onCheckedChange={() =>
                            toggleCategoryFilter(category.name)
                          }
                          className="border-zinc-600 data-[state=checked]:bg-primary data-[state=checked]:border-primary"
                        />
                        <Label
                          htmlFor={`category-${category.id}`}
                          className="min-w-0 flex-1 cursor-pointer truncate text-sm font-normal text-zinc-300"
                          title={category.name}
                        >
                          {category.name}
                        </Label>
                      </div>
                    ))
                  ) : (
                    <div className="px-2 py-8 text-center text-sm text-zinc-500">
                      {t.noCategoriesMatch}
                    </div>
                  )}
                </div>
              </div>
            </TabsContent>
            <TabsContent value="archived" className="mt-4">
              <div className="space-y-3">
                <div className="flex items-center space-x-2">
                  <Checkbox
                    id="show-archived"
                    checked={showArchived}
                    onCheckedChange={(checked) =>
                      setShowArchived(checked as boolean)
                    }
                    className="border-zinc-600 data-[state=checked]:bg-primary data-[state=checked]:border-primary"
                  />
                  <Label
                    htmlFor="show-archived"
                    className="text-sm font-normal text-zinc-300 cursor-pointer"
                  >
                    {t.showArchivedMemories}
                  </Label>
                </div>
              </div>
            </TabsContent>
          </Tabs>
          <div className="flex justify-end mt-4 gap-3">
            {hasTempFilters && (
              <Button
                onClick={handleClearFilters}
                className="bg-zinc-800 hover:bg-zinc-700 text-zinc-300"
              >
                {t.clearAll}
              </Button>
            )}
            <Button
              onClick={handleApplyFilters}
              className="bg-primary hover:bg-primary/80 text-white"
            >
              {t.applyFilters}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

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
