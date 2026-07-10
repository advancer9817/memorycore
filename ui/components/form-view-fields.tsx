import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Slider } from "./ui/slider";

export type SettingsSection = Record<string, unknown>;
export type StrategySection = "rule_curator" | "llm_curator" | "governance" | "extraction_strategy";

export function asSettingsSection(value: unknown): SettingsSection {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as SettingsSection
    : {};
}

export function SliderField({ label, hint, value, min, max, step, onChange }: {
  label: string;
  hint?: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Label className="text-sm">{label}</Label>
        <span className="text-xs text-muted-foreground tabular-nums">{value}</span>
      </div>
      <Slider min={min} max={max} step={step} value={[value]} onValueChange={(next) => onChange(next[0])} />
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

export function NumberField({ label, hint, value, min, onChange }: {
  label: string;
  hint?: string;
  value: number;
  min?: number;
  onChange: (value: number) => void;
}) {
  return (
    <div className="space-y-2">
      <Label className="text-sm">{label}</Label>
      <Input type="number" min={min} value={value} onChange={(event) => {
        const next = Number(event.target.value);
        if (Number.isFinite(next)) onChange(next);
      }} />
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}
