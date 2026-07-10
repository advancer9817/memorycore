"use client";

import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { useI18n } from "@/hooks/useI18n";
import { Button } from "./ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import { Slider } from "./ui/slider";
import { Switch } from "./ui/switch";
import { Textarea } from "./ui/textarea";
import type { SettingsSection } from "./form-view-fields";

type ChangeHandler = (key: string, value: unknown) => void;

export function CoreAndLlmSettings({ core, extraction, embedding, onCoreChange, onExtractionChange, onEmbeddingChange }: {
  core: SettingsSection;
  extraction: SettingsSection;
  embedding: SettingsSection;
  onCoreChange: ChangeHandler;
  onExtractionChange: ChangeHandler;
  onEmbeddingChange: ChangeHandler;
}) {
  const { messages } = useI18n();
  const s = messages.settings;
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [showLlmKey, setShowLlmKey] = useState(false);
  const [showEmbeddingKey, setShowEmbeddingKey] = useState(false);
  const embeddingProvider = (embedding.provider as string | undefined) || "auto";
  const isOllama = embeddingProvider.toLowerCase() === "ollama";

  return <>
    <Card>
      <CardHeader><CardTitle>{s.memoryCoreSettings}</CardTitle><CardDescription>{s.memoryCoreSettingsDescription}</CardDescription></CardHeader>
      <CardContent className="space-y-6">
        <div className="space-y-2">
          <Label htmlFor="custom-instructions">{s.customInstructions}</Label>
          <Textarea id="custom-instructions" placeholder={s.customInstructionsPlaceholder} value={(core.custom_instructions as string) || ""} onChange={(event) => onCoreChange("custom_instructions", event.target.value)} className="min-h-[100px]" />
          <p className="text-xs text-muted-foreground mt-1">{s.customInstructionsHint}</p>
        </div>
        <div className="space-y-2">
          <Label htmlFor="output-language">{s.outputLanguage}</Label>
          <Select value={(core.output_language as string) || "auto"} onValueChange={(value) => onCoreChange("output_language", value)}>
            <SelectTrigger id="output-language"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="auto">{s.outputLanguageAuto}</SelectItem><SelectItem value="zh">{s.outputLanguageChinese}</SelectItem><SelectItem value="en">{s.outputLanguageEnglish}</SelectItem></SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground mt-1">{s.outputLanguageHint}</p>
        </div>
      </CardContent>
    </Card>

    <Card>
      <CardHeader><CardTitle>{s.extractionLlm}</CardTitle><CardDescription>{s.extractionLlmDescription}</CardDescription></CardHeader>
      <CardContent className="space-y-4">
        <TextInput id="extraction-base-url" label={s.baseUrl} placeholder="http://127.0.0.1:8317/v1" value={extraction.base_url} onChange={(value) => onExtractionChange("base_url", value)} />
        <TextInput id="extraction-model" label={s.model} placeholder="gpt-4o-mini" value={extraction.model} onChange={(value) => onExtractionChange("model", value)} />
        <SecretInput id="extraction-api-key" label={s.apiKey} hint={s.apiKeyHint} shown={showLlmKey} value={extraction.api_key} onToggle={() => setShowLlmKey((value) => !value)} onChange={(value) => onExtractionChange("api_key", value)} />
        <div className="flex items-center space-x-2 pt-2"><Switch id="extraction-advanced" checked={showAdvanced} onCheckedChange={setShowAdvanced} /><Label htmlFor="extraction-advanced">{s.showAdvancedSettings}</Label></div>
        {showAdvanced && <div className="space-y-4 pt-2">
          <div className="space-y-2"><Label htmlFor="extraction-temperature">{s.temperature((extraction.temperature as number) ?? 0.1)}</Label><Slider id="extraction-temperature" min={0} max={1} step={0.05} value={[(extraction.temperature as number) ?? 0.1]} onValueChange={(value) => onExtractionChange("temperature", value[0])} /></div>
          <NumberInput id="extraction-max-tokens" label={s.maxTokens} placeholder="2000" value={extraction.max_tokens} onChange={(value) => onExtractionChange("max_tokens", value)} />
          <NumberInput id="extraction-timeout" label={s.timeout} placeholder="180" value={extraction.timeout} onChange={(value) => onExtractionChange("timeout", value)} />
        </div>}
      </CardContent>
    </Card>

    <Card>
      <CardHeader><CardTitle>{s.embeddingModel}</CardTitle><CardDescription>{s.embeddingModelDescription}</CardDescription></CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2"><Label htmlFor="embedding-provider">{s.provider}</Label><Select value={embeddingProvider} onValueChange={(value) => onEmbeddingChange("provider", value)}><SelectTrigger id="embedding-provider"><SelectValue placeholder={s.selectProvider} /></SelectTrigger><SelectContent>{["auto", "ollama", "openai", "api", "sentence-transformers", "hashing"].map((provider) => <SelectItem key={provider} value={provider}>{provider}</SelectItem>)}</SelectContent></Select></div>
        <TextInput id="embedding-model" label={s.model} placeholder="nomic-embed-text" value={embedding.model} onChange={(value) => onEmbeddingChange("model", value)} />
        {isOllama && <TextInput id="embedding-ollama-url" label={s.ollamaUrl} placeholder="http://127.0.0.1:11434" value={embedding.ollama_url} onChange={(value) => onEmbeddingChange("ollama_url", value)} />}
        {["openai", "api"].includes(embeddingProvider) && <>
          <SecretInput id="embedding-api-key" label={s.apiKey} shown={showEmbeddingKey} value={embedding.api_key} onToggle={() => setShowEmbeddingKey((value) => !value)} onChange={(value) => onEmbeddingChange("api_key", value)} />
          {embeddingProvider === "api" && <TextInput id="embedding-api-url" label={s.apiUrl} placeholder="http://127.0.0.1:11434/v1/embeddings" value={embedding.api_url} onChange={(value) => onEmbeddingChange("api_url", value)} />}
        </>}
      </CardContent>
    </Card>
  </>;
}

function TextInput({ id, label, placeholder, value, onChange }: { id: string; label: string; placeholder: string; value: unknown; onChange: (value: string) => void }) {
  return <div className="space-y-2"><Label htmlFor={id}>{label}</Label><Input id={id} placeholder={placeholder} value={(value as string) || ""} onChange={(event) => onChange(event.target.value)} /></div>;
}

function NumberInput({ id, label, placeholder, value, onChange }: { id: string; label: string; placeholder: string; value: unknown; onChange: (value: number | "") => void }) {
  return <div className="space-y-2"><Label htmlFor={id}>{label}</Label><Input id={id} type="number" placeholder={placeholder} value={(value as string | number) || ""} onChange={(event) => onChange(Number.parseInt(event.target.value) || "")} /></div>;
}

function SecretInput({ id, label, hint, shown, value, onToggle, onChange }: { id: string; label: string; hint?: string; shown: boolean; value: unknown; onToggle: () => void; onChange: (value: string) => void }) {
  return <div className="space-y-2"><Label htmlFor={id}>{label}</Label><div className="relative"><Input id={id} type={shown ? "text" : "password"} placeholder="env:OPENAI_API_KEY" value={(value as string) || ""} onChange={(event) => onChange(event.target.value)} /><Button variant="ghost" size="icon" type="button" className="absolute right-2 top-1/2 transform -translate-y-1/2 h-7 w-7" onClick={onToggle}>{shown ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}</Button></div>{hint && <p className="text-xs text-muted-foreground">{hint}</p>}</div>;
}
