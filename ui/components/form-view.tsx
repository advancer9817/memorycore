"use client";

import { CoreAndLlmSettings } from "./form-view-llm";
import { BackupSettings } from "./form-view-backup";
import { StrategySettings } from "./form-view-strategy";
import { asSettingsSection, type SettingsSection, type StrategySection } from "./form-view-fields";

type FormSettings = {
  settings?: unknown;
  llm?: unknown;
  strategy?: unknown;
};

interface FormViewProps<T extends FormSettings> {
  settings: T;
  onChange: (settings: T) => void;
}

export function FormView<T extends FormSettings>({ settings, onChange }: FormViewProps<T>) {
  const core = asSettingsSection(settings.settings);
  const llm = asSettingsSection(settings.llm);
  const extraction = asSettingsSection(llm.extraction);
  const embedding = asSettingsSection(llm.embedding);
  const strategy = asSettingsSection(settings.strategy);

  const updateRoot = (key: keyof FormSettings, value: SettingsSection) => {
    onChange({ ...settings, [key]: value });
  };
  const updateCore = (key: string, value: unknown) => updateRoot("settings", { ...core, [key]: value });
  const updateLlmSection = (section: "extraction" | "embedding", current: SettingsSection, key: string, value: unknown) => {
    updateRoot("llm", { ...llm, [section]: { ...current, [key]: value } });
  };
  const updateStrategy = (section: StrategySection, key: string, value: unknown) => {
    const current = asSettingsSection(strategy[section]);
    updateRoot("strategy", { ...strategy, [section]: { ...current, [key]: value } });
  };
  const toggleStrategyList = (section: StrategySection, key: string, item: string, checked: boolean) => {
    const currentSection = asSettingsSection(strategy[section]);
    const current = (currentSection[key] as string[] | undefined) ?? [];
    updateStrategy(section, key, checked ? [...current, item] : current.filter((value) => value !== item));
  };

  return <div className="space-y-8">
    <CoreAndLlmSettings
      core={core}
      extraction={extraction}
      embedding={embedding}
      onCoreChange={updateCore}
      onExtractionChange={(key, value) => updateLlmSection("extraction", extraction, key, value)}
      onEmbeddingChange={(key, value) => updateLlmSection("embedding", embedding, key, value)}
    />
    <BackupSettings />
    <StrategySettings strategy={strategy} onChange={updateStrategy} onListToggle={toggleStrategyList} />
  </div>;
}
