import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useI18n } from "@/hooks/useI18n";

interface PageSizeSelectorProps {
  pageSize: number;
  onPageSizeChange: (size: number) => void;
}

export function PageSizeSelector({
  pageSize,
  onPageSizeChange,
}: PageSizeSelectorProps) {
  const pageSizeOptions = [10, 20, 50, 100];
  const { messages } = useI18n();
  const t = messages.memories;

  return (
    <div className="flex items-center gap-2">
      <span className="text-sm text-zinc-500">{t.pageSizeShow}</span>
      <Select
        value={pageSize.toString()}
        onValueChange={(value) => onPageSizeChange(Number(value))}
      >
        <SelectTrigger className="w-[70px] h-8">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {pageSizeOptions.map((size) => (
            <SelectItem key={size} value={size.toString()}>
              {size}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <span className="text-sm text-zinc-500">{t.pageSizeItems}</span>
    </div>
  );
}

export default PageSizeSelector;
