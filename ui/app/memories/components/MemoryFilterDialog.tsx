import { Filter, Search } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { App } from "@/store/appsSlice";
import type { Category, FiltersState } from "@/store/filtersSlice";
import type { Messages } from "@/lib/i18n/types";

interface MemoryFilterDialogProps {
  isOpen: boolean;
  handleDialogChange: (open: boolean) => void;
  hasActiveFilters: boolean;
  hasTempFilters: boolean;
  filters: FiltersState["apps"];
  apps: App[];
  categories: Category[];
  filteredCategories: Category[];
  tempSelectedApps: string[];
  tempSelectedCategories: string[];
  showArchived: boolean;
  categoryQuery: string;
  dateFrom: string;
  dateTo: string;
  setCategoryQuery: (value: string) => void;
  setShowArchived: (value: boolean) => void;
  setDateFrom: (value: string) => void;
  setDateTo: (value: string) => void;
  toggleAllApps: (checked: boolean) => void;
  toggleAppFilter: (app: string) => void;
  toggleVisibleCategories: (checked: boolean) => void;
  toggleCategoryFilter: (category: string) => void;
  handleClearFilters: () => void;
  handleApplyFilters: () => void;
  t: Messages["memories"];
}

export function MemoryFilterDialog(props: MemoryFilterDialogProps) {
  const {
    isOpen, handleDialogChange, hasActiveFilters, hasTempFilters, filters,
    apps, categories, filteredCategories, tempSelectedApps, tempSelectedCategories,
    showArchived, categoryQuery, dateFrom, dateTo, setCategoryQuery, setShowArchived,
    setDateFrom, setDateTo, toggleAllApps, toggleAppFilter, toggleVisibleCategories,
    toggleCategoryFilter, handleClearFilters, handleApplyFilters, t,
  } = props;
  return (
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
            <TabsList className="grid grid-cols-4 bg-zinc-800">
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
              <TabsTrigger
                value="daterange"
                className="data-[state=active]:bg-zinc-700"
              >
                {t.tabDateRange}
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
            <TabsContent value="daterange" className="mt-4">
              <div className="space-y-4">
                <div className="space-y-1">
                  <Label className="text-xs text-zinc-400">{t.dateFrom}</Label>
                  <Input
                    type="date"
                    value={dateFrom}
                    onChange={(e) => setDateFrom(e.target.value)}
                    placeholder={t.dateFromPlaceholder}
                    className="h-9 border-zinc-700 bg-zinc-950 text-sm text-zinc-100"
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs text-zinc-400">{t.dateTo}</Label>
                  <Input
                    type="date"
                    value={dateTo}
                    onChange={(e) => setDateTo(e.target.value)}
                    placeholder={t.dateToPlaceholder}
                    className="h-9 border-zinc-700 bg-zinc-950 text-sm text-zinc-100"
                  />
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
  );
}
