"use client"

import { useState, useRef } from "react"
import { Eye, EyeOff, Download, Upload } from "lucide-react"
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "./ui/accordion"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card"
import { Checkbox } from "./ui/checkbox"
import { Input } from "./ui/input"
import { Label } from "./ui/label"
import { Slider } from "./ui/slider"
import { Switch } from "./ui/switch"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./ui/tabs"
import { Button } from "./ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import { Textarea } from "./ui/textarea"
import { useSelector } from "react-redux"
import { RootState } from "@/store/store"
import { useI18n } from "@/hooks/useI18n"
import { useToast } from "@/hooks/use-toast"

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnySettings = any

const ALL_MEMORY_TYPES = [
  "user_profile", "environment_fact", "agent_architecture", "project_memory",
  "episodic_memory", "timeline_event", "decision", "feedback", "skill_candidate", "raw_event",
]

const DEFAULT_RULE_PRECIOUS = ["user_profile", "environment_fact", "decision", "project_memory", "skill_candidate"]
const DEFAULT_GOV_PRECIOUS = ["user_profile", "decision", "project_memory"]

const ALL_ACTIONS = [
  "mark_contradicted", "archive_and_merge_duplicate", "archive", "split", "promote",
]

function SliderField({ label, hint, value, min, max, step, onChange }: {
  label: string; hint?: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Label className="text-sm">{label}</Label>
        <span className="text-xs text-muted-foreground tabular-nums">{value}</span>
      </div>
      <Slider min={min} max={max} step={step} value={[value]} onValueChange={(v) => onChange(v[0])} />
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

function NumberField({ label, hint, value, min, onChange }: {
  label: string; hint?: string; value: number; min?: number; onChange: (v: number) => void;
}) {
  return (
    <div className="space-y-2">
      <Label className="text-sm">{label}</Label>
      <Input
        type="number"
        min={min}
        value={value}
        onChange={(e) => {
          const n = Number(e.target.value)
          if (Number.isFinite(n)) onChange(n)
        }}
      />
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

interface FormViewProps {
  settings: AnySettings
  onChange: (settings: AnySettings) => void
}

export function FormView({ settings, onChange }: FormViewProps) {
  const [showLlmAdvanced, setShowLlmAdvanced] = useState(false)
  const [showLlmApiKey, setShowLlmApiKey] = useState(false)
  const [showEmbedderApiKey, setShowEmbedderApiKey] = useState(false)
  const [isUploading, setIsUploading] = useState(false)
  const [selectedImportFileName, setSelectedImportFileName] = useState("")
  const fileInputRef = useRef<HTMLInputElement>(null)
  const API_URL = process.env.NEXT_PUBLIC_API_URL || ""
  const userId = useSelector((state: RootState) => state.profile.userId)
  const { messages } = useI18n()
  const { toast } = useToast()
  const s = messages.settings
  const st = s.strategy

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const llm = settings.llm as Record<string, any> | undefined
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const extraction = llm?.extraction as Record<string, any> | undefined
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const embedding = llm?.embedding as Record<string, any> | undefined
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const settingsSection = settings.settings as Record<string, any> | undefined

  const handleMemoryCoreChange = (key: string, value: unknown) => {
    onChange({
      ...settings,
      settings: {
        ...settingsSection,
        [key]: value,
      },
    })
  }

  const handleExtractionChange = (key: string, value: unknown) => {
    onChange({
      ...settings,
      llm: {
        ...llm,
        extraction: {
          ...extraction,
          [key]: value,
        },
      },
    })
  }

  const handleEmbeddingChange = (key: string, value: unknown) => {
    onChange({
      ...settings,
      llm: {
        ...llm,
        embedding: {
          ...embedding,
          [key]: value,
        },
      },
    })
  }

  const isEmbeddingOllama = (embedding?.provider as string | undefined)?.toLowerCase() === "ollama"
  const embeddingProvider = (embedding?.provider as string | undefined) || "auto"

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const strategy = settings.strategy as Record<string, any> | undefined
  const ruleCurator = (strategy?.rule_curator ?? {}) as Record<string, unknown>
  const llmCurator = (strategy?.llm_curator ?? {}) as Record<string, unknown>
  const govConfig = (strategy?.governance ?? {}) as Record<string, unknown>

  const extractionStrategy = (strategy?.extraction_strategy ?? {}) as Record<string, unknown>

  const handleStrategyChange = (section: "rule_curator" | "llm_curator" | "governance" | "extraction_strategy", key: string, value: unknown) => {
    const current = (strategy?.[section] ?? {}) as Record<string, unknown>
    onChange({
      ...settings,
      strategy: {
        ...strategy,
        [section]: {
          ...current,
          [key]: value,
        },
      },
    })
  }

  const handleTypeListToggle = (section: "rule_curator" | "llm_curator" | "governance" | "extraction_strategy", key: string, item: string, checked: boolean) => {
    const current = ((strategy?.[section] as Record<string, unknown> | undefined)?.[key] as string[] | undefined) ?? []
    const next = checked ? [...current, item] : current.filter((t) => t !== item)
    handleStrategyChange(section, key, next)
  }

  return (
    <div className="space-y-8">
      {/* MemoryCore Settings */}
      <Card>
        <CardHeader>
          <CardTitle>{s.memoryCoreSettings}</CardTitle>
          <CardDescription>{s.memoryCoreSettingsDescription}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="space-y-2">
            <Label htmlFor="custom-instructions">{s.customInstructions}</Label>
            <Textarea
              id="custom-instructions"
              placeholder={s.customInstructionsPlaceholder}
              value={(settingsSection?.custom_instructions as string) || ""}
              onChange={(e) => handleMemoryCoreChange("custom_instructions", e.target.value)}
              className="min-h-[100px]"
            />
            <p className="text-xs text-muted-foreground mt-1">{s.customInstructionsHint}</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="output-language">{s.outputLanguage}</Label>
            <Select
              value={(settingsSection?.output_language as string) || "auto"}
              onValueChange={(v) => handleMemoryCoreChange("output_language", v)}
            >
              <SelectTrigger id="output-language">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="auto">{s.outputLanguageAuto}</SelectItem>
                <SelectItem value="zh">{s.outputLanguageChinese}</SelectItem>
                <SelectItem value="en">{s.outputLanguageEnglish}</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground mt-1">{s.outputLanguageHint}</p>
          </div>
        </CardContent>
      </Card>

      {/* Extraction LLM Settings */}
      <Card>
        <CardHeader>
          <CardTitle>{s.extractionLlm}</CardTitle>
          <CardDescription>{s.extractionLlmDescription}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="extraction-base-url">{s.baseUrl}</Label>
            <Input
              id="extraction-base-url"
              placeholder="http://127.0.0.1:8317/v1"
              value={(extraction?.base_url as string) || ""}
              onChange={(e) => handleExtractionChange("base_url", e.target.value)}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="extraction-model">{s.model}</Label>
            <Input
              id="extraction-model"
              placeholder="gpt-4o-mini"
              value={(extraction?.model as string) || ""}
              onChange={(e) => handleExtractionChange("model", e.target.value)}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="extraction-api-key">{s.apiKey}</Label>
            <div className="relative">
              <Input
                id="extraction-api-key"
                type={showLlmApiKey ? "text" : "password"}
                placeholder="env:OPENAI_API_KEY"
                value={(extraction?.api_key as string) || ""}
                onChange={(e) => handleExtractionChange("api_key", e.target.value)}
              />
              <Button
                variant="ghost"
                size="icon"
                type="button"
                className="absolute right-2 top-1/2 transform -translate-y-1/2 h-7 w-7"
                onClick={() => setShowLlmApiKey(!showLlmApiKey)}
              >
                {showLlmApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">{s.apiKeyHint}</p>
          </div>

          <div className="flex items-center space-x-2 pt-2">
            <Switch id="extraction-advanced" checked={showLlmAdvanced} onCheckedChange={setShowLlmAdvanced} />
            <Label htmlFor="extraction-advanced">{s.showAdvancedSettings}</Label>
          </div>

          {showLlmAdvanced && (
            <div className="space-y-4 pt-2">
              <div className="space-y-2">
                <Label htmlFor="extraction-temperature">
                  {s.temperature((extraction?.temperature as number) ?? 0.1)}
                </Label>
                <Slider
                  id="extraction-temperature"
                  min={0}
                  max={1}
                  step={0.05}
                  value={[(extraction?.temperature as number) ?? 0.1]}
                  onValueChange={(value) => handleExtractionChange("temperature", value[0])}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="extraction-max-tokens">{s.maxTokens}</Label>
                <Input
                  id="extraction-max-tokens"
                  type="number"
                  placeholder="2000"
                  value={(extraction?.max_tokens as string | number) || ""}
                  onChange={(e) => handleExtractionChange("max_tokens", Number.parseInt(e.target.value) || "")}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="extraction-timeout">{s.timeout}</Label>
                <Input
                  id="extraction-timeout"
                  type="number"
                  placeholder="180"
                  value={(extraction?.timeout as string | number) || ""}
                  onChange={(e) => handleExtractionChange("timeout", Number.parseInt(e.target.value) || "")}
                />
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Embedding Settings */}
      <Card>
        <CardHeader>
          <CardTitle>{s.embeddingModel}</CardTitle>
          <CardDescription>{s.embeddingModelDescription}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="embedding-provider">{s.provider}</Label>
            <Select
              value={embeddingProvider}
              onValueChange={(v) => handleEmbeddingChange("provider", v)}
            >
              <SelectTrigger id="embedding-provider">
                <SelectValue placeholder={s.selectProvider} />
              </SelectTrigger>
              <SelectContent>
                {["auto", "ollama", "openai", "api", "sentence-transformers", "hashing"].map((p) => (
                  <SelectItem key={p} value={p}>{p}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="embedding-model">{s.model}</Label>
            <Input
              id="embedding-model"
              placeholder="nomic-embed-text"
              value={(embedding?.model as string) || ""}
              onChange={(e) => handleEmbeddingChange("model", e.target.value)}
            />
          </div>

          {isEmbeddingOllama && (
            <div className="space-y-2">
              <Label htmlFor="embedding-ollama-url">{s.ollamaUrl}</Label>
              <Input
                id="embedding-ollama-url"
                placeholder="http://127.0.0.1:11434"
                value={(embedding?.ollama_url as string) || ""}
                onChange={(e) => handleEmbeddingChange("ollama_url", e.target.value)}
              />
            </div>
          )}

          {["openai", "api"].includes(embeddingProvider) && (
            <>
              <div className="space-y-2">
                <Label htmlFor="embedding-api-key">{s.apiKey}</Label>
                <div className="relative">
                  <Input
                    id="embedding-api-key"
                    type={showEmbedderApiKey ? "text" : "password"}
                    placeholder="env:OPENAI_API_KEY"
                    value={(embedding?.api_key as string) || ""}
                    onChange={(e) => handleEmbeddingChange("api_key", e.target.value)}
                  />
                  <Button
                    variant="ghost"
                    size="icon"
                    type="button"
                    className="absolute right-2 top-1/2 transform -translate-y-1/2 h-7 w-7"
                    onClick={() => setShowEmbedderApiKey(!showEmbedderApiKey)}
                  >
                    {showEmbedderApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </Button>
                </div>
              </div>
              {embeddingProvider === "api" && (
                <div className="space-y-2">
                  <Label htmlFor="embedding-api-url">{s.apiUrl}</Label>
                  <Input
                    id="embedding-api-url"
                    placeholder="http://127.0.0.1:11434/v1/embeddings"
                    value={(embedding?.api_url as string) || ""}
                    onChange={(e) => handleEmbeddingChange("api_url", e.target.value)}
                  />
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      {/* Backup (Export / Import) */}
      <Card>
        <CardHeader>
          <CardTitle>{s.backupTitle}</CardTitle>
          <CardDescription>{s.backupDescription}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Export Section */}
          <div className="p-4 border border-zinc-800 rounded-lg space-y-2">
            <div className="text-sm font-medium">{s.exportTitle}</div>
            <p className="text-xs text-muted-foreground">{s.exportDescription}</p>
            <div>
              <Button
                type="button"
                className="bg-zinc-800 hover:bg-zinc-700"
                onClick={async () => {
                  try {
                    const res = await fetch(`${API_URL}/api/v1/backup/export`, {
                      method: "POST",
                      headers: { "Content-Type": "application/json", Accept: "application/zip" },
                      body: JSON.stringify({ user_id: userId }),
                    })
                    if (!res.ok) throw new Error(`HTTP ${res.status}`)
                    const blob = await res.blob()
                    const url = window.URL.createObjectURL(blob)
                    const a = document.createElement("a")
                    a.href = url
                    a.download = "memories_export.zip"
                    document.body.appendChild(a)
                    a.click()
                    a.remove()
                    window.URL.revokeObjectURL(url)
                  } catch {
                    toast({ title: s.exportFailed, variant: "destructive" })
                  }
                }}
              >
                <Download className="h-4 w-4 mr-2" /> {s.exportMemories}
              </Button>
            </div>
          </div>

          {/* Import Section */}
          <div className="p-4 border border-zinc-800 rounded-lg space-y-2">
            <div className="text-sm font-medium">{s.importTitle}</div>
            <p className="text-xs text-muted-foreground">{s.importDescription}</p>
            <div className="flex items-center gap-3 flex-wrap">
              <input
                ref={fileInputRef}
                type="file"
                accept=".zip"
                className="hidden"
                onChange={(evt) => {
                  const f = evt.target.files?.[0]
                  if (!f) return
                  setSelectedImportFileName(f.name)
                }}
              />
              <Button
                type="button"
                className="bg-zinc-800 hover:bg-zinc-700"
                onClick={() => { if (fileInputRef.current) fileInputRef.current.click() }}
              >
                <Upload className="h-4 w-4 mr-2" /> {s.chooseZip}
              </Button>
              <span className="text-xs text-muted-foreground truncate max-w-[220px]">
                {selectedImportFileName || s.noFileSelected}
              </span>
              <div className="ml-auto">
                <Button
                  type="button"
                  disabled={isUploading || !fileInputRef.current}
                  className="bg-primary hover:bg-primary/80 disabled:opacity-50"
                  onClick={async () => {
                    const file = fileInputRef.current?.files?.[0]
                    if (!file) return
                    try {
                      setIsUploading(true)
                      const form = new FormData()
                      form.append("file", file)
                      form.append("user_id", String(userId))
                      const res = await fetch(`${API_URL}/api/v1/backup/import`, { method: "POST", body: form })
                      if (!res.ok) throw new Error(`HTTP ${res.status}`)
                      await res.json()
                      if (fileInputRef.current) fileInputRef.current.value = ""
                      setSelectedImportFileName("")
                    } catch {
                      toast({ title: s.importFailed, variant: "destructive" })
                    } finally {
                      setIsUploading(false)
                    }
                  }}
                >
                  {isUploading ? s.uploading : s.import}
                </Button>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Strategy Configuration */}
      <Card>
        <CardHeader>
          <CardTitle>{st.title}</CardTitle>
          <CardDescription>{st.description}</CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="rule_curator" className="w-full">
            <TabsList className="grid w-full grid-cols-4">
              <TabsTrigger value="rule_curator">{st.ruleCurator}</TabsTrigger>
              <TabsTrigger value="llm_curator">{st.llmCurator}</TabsTrigger>
              <TabsTrigger value="governance">{st.governance}</TabsTrigger>
              <TabsTrigger value="extraction_strategy">{st.extractionStrategy}</TabsTrigger>
            </TabsList>

            <TabsContent value="rule_curator" className="mt-4">
              <Accordion type="multiple" defaultValue={["decay", "candidate"]} className="space-y-2">
                <AccordionItem value="decay">
                  <AccordionTrigger className="text-sm">{st.decayGroup}</AccordionTrigger>
                  <AccordionContent className="space-y-4 pt-2">
                    <SliderField label={st.decayStep} hint={st.decayStepHint} value={(ruleCurator.decay_step as number) ?? 0.05} min={0.01} max={0.5} step={0.01} onChange={(v) => handleStrategyChange("rule_curator", "decay_step", v)} />
                    <NumberField label={st.decayIntervalDays} hint={st.decayIntervalDaysHint} value={(ruleCurator.decay_interval_days as number) ?? 30} min={1} onChange={(v) => handleStrategyChange("rule_curator", "decay_interval_days", v)} />
                    <SliderField label={st.decayMinConfidence} hint={st.decayMinConfidenceHint} value={(ruleCurator.decay_min_confidence as number) ?? 0.15} min={0} max={1} step={0.01} onChange={(v) => handleStrategyChange("rule_curator", "decay_min_confidence", v)} />
                  </AccordionContent>
                </AccordionItem>

                <AccordionItem value="candidate">
                  <AccordionTrigger className="text-sm">{st.candidateGroup}</AccordionTrigger>
                  <AccordionContent className="space-y-4 pt-2">
                    <NumberField label={st.candidateTtlEpisodicDays} value={(ruleCurator.candidate_ttl_episodic_days as number) ?? 7} min={1} onChange={(v) => handleStrategyChange("rule_curator", "candidate_ttl_episodic_days", v)} />
                    <NumberField label={st.candidateTtlPreciousDays} value={(ruleCurator.candidate_ttl_precious_days as number) ?? 30} min={1} onChange={(v) => handleStrategyChange("rule_curator", "candidate_ttl_precious_days", v)} />
                    <NumberField label={st.candidateTtlDefaultDays} value={(ruleCurator.candidate_ttl_default_days as number) ?? 7} min={1} onChange={(v) => handleStrategyChange("rule_curator", "candidate_ttl_default_days", v)} />
                    <NumberField label={st.neverAccessedCandidateDays} value={(ruleCurator.never_accessed_candidate_days as number) ?? 14} min={1} onChange={(v) => handleStrategyChange("rule_curator", "never_accessed_candidate_days", v)} />
                  </AccordionContent>
                </AccordionItem>

                <AccordionItem value="lifecycle">
                  <AccordionTrigger className="text-sm">{st.lifecycleGroup}</AccordionTrigger>
                  <AccordionContent className="space-y-4 pt-2">
                    <NumberField label={st.staleDaysEpisodic} value={(ruleCurator.stale_days_episodic as number) ?? 14} min={1} onChange={(v) => handleStrategyChange("rule_curator", "stale_days_episodic", v)} />
                    <NumberField label={st.archiveDaysEpisodic} value={(ruleCurator.archive_days_episodic as number) ?? 30} min={1} onChange={(v) => handleStrategyChange("rule_curator", "archive_days_episodic", v)} />
                    <NumberField label={st.staleDaysDefault} value={(ruleCurator.stale_days_default as number) ?? 365} min={1} onChange={(v) => handleStrategyChange("rule_curator", "stale_days_default", v)} />
                    <NumberField label={st.archiveDaysDefault} value={(ruleCurator.archive_days_default as number) ?? 730} min={1} onChange={(v) => handleStrategyChange("rule_curator", "archive_days_default", v)} />
                    <NumberField label={st.contradictedArchiveDays} value={(ruleCurator.contradicted_archive_days as number) ?? 90} min={1} onChange={(v) => handleStrategyChange("rule_curator", "contradicted_archive_days", v)} />
                  </AccordionContent>
                </AccordionItem>

                <AccordionItem value="promotion">
                  <AccordionTrigger className="text-sm">{st.promotionGroup}</AccordionTrigger>
                  <AccordionContent className="space-y-4 pt-2">
                    <SliderField label={st.promoteImportanceThreshold} value={(ruleCurator.promote_importance_threshold as number) ?? 0.75} min={0} max={1} step={0.01} onChange={(v) => handleStrategyChange("rule_curator", "promote_importance_threshold", v)} />
                    <NumberField label={st.promoteInjectedThreshold} value={(ruleCurator.promote_injected_threshold as number) ?? 3} min={1} onChange={(v) => handleStrategyChange("rule_curator", "promote_injected_threshold", v)} />
                    <NumberField label={st.revivalWindowDays} value={(ruleCurator.revival_window_days as number) ?? 7} min={1} onChange={(v) => handleStrategyChange("rule_curator", "revival_window_days", v)} />
                    <SliderField label={st.revivalEffectivenessMin} value={(ruleCurator.revival_effectiveness_min as number) ?? 0.5} min={0} max={1} step={0.01} onChange={(v) => handleStrategyChange("rule_curator", "revival_effectiveness_min", v)} />
                    <SliderField label={st.revivalFeedbackMin} value={(ruleCurator.revival_feedback_min as number) ?? 0} min={-5} max={5} step={0.1} onChange={(v) => handleStrategyChange("rule_curator", "revival_feedback_min", v)} />
                    <SliderField label={st.skillPromoteImportance} value={(ruleCurator.skill_promote_importance as number) ?? 0.65} min={0} max={1} step={0.01} onChange={(v) => handleStrategyChange("rule_curator", "skill_promote_importance", v)} />
                    <SliderField label={st.skillPromoteFeedbackMin} value={(ruleCurator.skill_promote_feedback_min as number) ?? 0} min={-5} max={5} step={0.1} onChange={(v) => handleStrategyChange("rule_curator", "skill_promote_feedback_min", v)} />
                  </AccordionContent>
                </AccordionItem>

                <AccordionItem value="stale">
                  <AccordionTrigger className="text-sm">{st.staleGroup}</AccordionTrigger>
                  <AccordionContent className="space-y-4 pt-2">
                    <SliderField label={st.staleImportanceThreshold} value={(ruleCurator.stale_importance_threshold as number) ?? 0.45} min={0} max={1} step={0.01} onChange={(v) => handleStrategyChange("rule_curator", "stale_importance_threshold", v)} />
                    <SliderField label={st.staleFeedbackThreshold} value={(ruleCurator.stale_feedback_threshold as number) ?? -0.5} min={-5} max={0} step={0.1} onChange={(v) => handleStrategyChange("rule_curator", "stale_feedback_threshold", v)} />
                    <SliderField label={st.preciousStaleFeedback} value={(ruleCurator.precious_stale_feedback as number) ?? -2} min={-10} max={0} step={0.1} onChange={(v) => handleStrategyChange("rule_curator", "precious_stale_feedback", v)} />
                    <SliderField label={st.preciousStaleImportance} value={(ruleCurator.precious_stale_importance as number) ?? 0.3} min={0} max={1} step={0.01} onChange={(v) => handleStrategyChange("rule_curator", "precious_stale_importance", v)} />
                  </AccordionContent>
                </AccordionItem>

                <AccordionItem value="precious">
                  <AccordionTrigger className="text-sm">{st.preciousGroup}</AccordionTrigger>
                  <AccordionContent className="space-y-3 pt-2">
                    <Label className="text-xs text-muted-foreground">{st.preciousTypes}</Label>
                    <div className="grid grid-cols-2 gap-2">
                      {ALL_MEMORY_TYPES.map((t) => (
                        <label key={t} className="flex items-center gap-2 text-sm">
                          <Checkbox
                            checked={((ruleCurator.precious_types as string[] | undefined) ?? DEFAULT_RULE_PRECIOUS).includes(t)}
                            onCheckedChange={(checked) => handleTypeListToggle("rule_curator", "precious_types", t, checked === true)}
                          />
                          {t}
                        </label>
                      ))}
                    </div>
                  </AccordionContent>
                </AccordionItem>
              </Accordion>
            </TabsContent>

            <TabsContent value="llm_curator" className="mt-4 space-y-4">
              <SliderField label={st.simThreshold} hint={st.simThresholdHint} value={(llmCurator.sim_threshold as number) ?? 0.6} min={0} max={1} step={0.01} onChange={(v) => handleStrategyChange("llm_curator", "sim_threshold", v)} />
              <NumberField label={st.batchSize} hint={st.batchSizeHint} value={(llmCurator.batch_size as number) ?? 10} min={1} onChange={(v) => handleStrategyChange("llm_curator", "batch_size", v)} />
              <NumberField label={st.importanceLimit} hint={st.importanceLimitHint} value={(llmCurator.importance_limit as number) ?? 1000} min={1} onChange={(v) => handleStrategyChange("llm_curator", "importance_limit", v)} />
              <NumberField label={st.splitContentThreshold} hint={st.splitContentThresholdHint} value={(llmCurator.split_content_threshold as number) ?? 400} min={50} onChange={(v) => handleStrategyChange("llm_curator", "split_content_threshold", v)} />
              <NumberField label={st.reviewCooldownSeconds} hint={st.reviewCooldownSecondsHint} value={(llmCurator.review_cooldown_seconds as number) ?? 7200} min={0} onChange={(v) => handleStrategyChange("llm_curator", "review_cooldown_seconds", v)} />
              <NumberField label={st.reviewedIdsMaxAgeSeconds} hint={st.reviewedIdsMaxAgeSecondsHint} value={(llmCurator.reviewed_ids_max_age_seconds as number) ?? 86400} min={0} onChange={(v) => handleStrategyChange("llm_curator", "reviewed_ids_max_age_seconds", v)} />
            </TabsContent>

            <TabsContent value="governance" className="mt-4 space-y-4">
              <SliderField label={st.reviewConfidenceThreshold} hint={st.reviewConfidenceThresholdHint} value={(govConfig.review_confidence_threshold as number) ?? 0.55} min={0} max={1} step={0.01} onChange={(v) => handleStrategyChange("governance", "review_confidence_threshold", v)} />
              <SliderField label={st.highImportanceThreshold} hint={st.highImportanceThresholdHint} value={(govConfig.high_importance_threshold as number) ?? 0.85} min={0} max={1} step={0.01} onChange={(v) => handleStrategyChange("governance", "high_importance_threshold", v)} />
              <SliderField label={st.autoApproveConfidence} hint={st.autoApproveConfidenceHint} value={(govConfig.auto_approve_confidence as number) ?? 0.9} min={0} max={1} step={0.01} onChange={(v) => handleStrategyChange("governance", "auto_approve_confidence", v)} />
              <SliderField label={st.autoApproveLowRiskConfidence} hint={st.autoApproveLowRiskConfidenceHint} value={(govConfig.auto_approve_low_risk_confidence as number) ?? 0.7} min={0} max={1} step={0.01} onChange={(v) => handleStrategyChange("governance", "auto_approve_low_risk_confidence", v)} />
              <div className="space-y-2">
                <Label className="text-xs text-muted-foreground">{st.governancePreciousTypes}</Label>
                <div className="grid grid-cols-2 gap-2">
                  {ALL_MEMORY_TYPES.map((t) => (
                    <label key={t} className="flex items-center gap-2 text-sm">
                      <Checkbox
                        checked={((govConfig.precious_types as string[] | undefined) ?? DEFAULT_GOV_PRECIOUS).includes(t)}
                        onCheckedChange={(checked) => handleTypeListToggle("governance", "precious_types", t, checked === true)}
                      />
                      {t}
                    </label>
                  ))}
                </div>
              </div>
              <div className="space-y-2">
                <Label className="text-xs text-muted-foreground">{st.manualOnlyActions}</Label>
                <div className="flex flex-wrap gap-2">
                  {ALL_ACTIONS.map((a) => (
                    <label key={a} className="flex items-center gap-2 text-sm">
                      <Checkbox
                        checked={((govConfig.manual_only_actions as string[] | undefined) ?? ["split"]).includes(a)}
                        onCheckedChange={(checked) => handleTypeListToggle("governance", "manual_only_actions", a, checked === true)}
                      />
                      {a}
                    </label>
                  ))}
                </div>
              </div>
              <div className="space-y-2">
                <Label className="text-xs text-muted-foreground">{st.mergeActions}</Label>
                <div className="flex flex-wrap gap-2">
                  {ALL_ACTIONS.map((a) => (
                    <label key={a} className="flex items-center gap-2 text-sm">
                      <Checkbox
                        checked={((govConfig.merge_actions as string[] | undefined) ?? ["archive_and_merge_duplicate"]).includes(a)}
                        onCheckedChange={(checked) => handleTypeListToggle("governance", "merge_actions", a, checked === true)}
                      />
                      {a}
                    </label>
                  ))}
                </div>
              </div>
            </TabsContent>

            <TabsContent value="extraction_strategy" className="mt-4">
              <Accordion type="multiple" defaultValue={["quality", "dedup"]} className="space-y-2">
                <AccordionItem value="quality">
                  <AccordionTrigger className="text-sm">{st.extractionQualityGroup}</AccordionTrigger>
                  <AccordionContent className="space-y-4 pt-2">
                    <SliderField label={st.minImportance} hint={st.minImportanceHint} value={(extractionStrategy.min_importance as number) ?? 0.3} min={0} max={1} step={0.05} onChange={(v) => handleStrategyChange("extraction_strategy", "min_importance", v)} />
                    <SliderField label={st.defaultConfidence} hint={st.defaultConfidenceHint} value={(extractionStrategy.default_confidence as number) ?? 0.65} min={0} max={1} step={0.05} onChange={(v) => handleStrategyChange("extraction_strategy", "default_confidence", v)} />
                    <SliderField label={st.defaultImportance} hint={st.defaultImportanceHint} value={(extractionStrategy.default_importance as number) ?? 0.5} min={0} max={1} step={0.05} onChange={(v) => handleStrategyChange("extraction_strategy", "default_importance", v)} />
                    <SliderField label={st.chineseDetectionRatio} hint={st.chineseDetectionRatioHint} value={(extractionStrategy.chinese_detection_ratio as number) ?? 0.15} min={0.05} max={0.5} step={0.01} onChange={(v) => handleStrategyChange("extraction_strategy", "chinese_detection_ratio", v)} />
                  </AccordionContent>
                </AccordionItem>

                <AccordionItem value="dedup">
                  <AccordionTrigger className="text-sm">{st.dedupThresholdGroup}</AccordionTrigger>
                  <AccordionContent className="space-y-4 pt-2">
                    <SliderField label={st.skipThreshold} hint={st.skipThresholdHint} value={(extractionStrategy.skip_threshold as number) ?? 0.92} min={0.8} max={0.99} step={0.01} onChange={(v) => handleStrategyChange("extraction_strategy", "skip_threshold", v)} />
                    <SliderField label={st.updateThreshold} hint={st.updateThresholdHint} value={(extractionStrategy.update_threshold as number) ?? 0.78} min={0.6} max={0.95} step={0.01} onChange={(v) => handleStrategyChange("extraction_strategy", "update_threshold", v)} />
                    <SliderField label={st.linkThreshold} hint={st.linkThresholdHint} value={(extractionStrategy.link_threshold as number) ?? 0.55} min={0.3} max={0.8} step={0.01} onChange={(v) => handleStrategyChange("extraction_strategy", "link_threshold", v)} />
                  </AccordionContent>
                </AccordionItem>

                <AccordionItem value="context">
                  <AccordionTrigger className="text-sm">{st.contextSearchGroup}</AccordionTrigger>
                  <AccordionContent className="space-y-4 pt-2">
                    <NumberField label={st.contextSampleLength} hint={st.contextSampleLengthHint} value={(extractionStrategy.context_sample_length as number) ?? 200} min={50} onChange={(v) => handleStrategyChange("extraction_strategy", "context_sample_length", v)} />
                    <NumberField label={st.contextMemoryLimit} hint={st.contextMemoryLimitHint} value={(extractionStrategy.context_memory_limit as number) ?? 10} min={1} onChange={(v) => handleStrategyChange("extraction_strategy", "context_memory_limit", v)} />
                    <NumberField label={st.dedupSearchLimit} hint={st.dedupSearchLimitHint} value={(extractionStrategy.dedup_search_limit as number) ?? 5} min={1} onChange={(v) => handleStrategyChange("extraction_strategy", "dedup_search_limit", v)} />
                    <NumberField label={st.maxRelatedIds} hint={st.maxRelatedIdsHint} value={(extractionStrategy.max_related_ids as number) ?? 10} min={1} onChange={(v) => handleStrategyChange("extraction_strategy", "max_related_ids", v)} />
                  </AccordionContent>
                </AccordionItem>

                <AccordionItem value="defaults">
                  <AccordionTrigger className="text-sm">{st.memoryDefaultsGroup}</AccordionTrigger>
                  <AccordionContent className="space-y-4 pt-2">
                    <div className="space-y-2">
                      <Label className="text-sm">{st.defaultMemoryType}</Label>
                      <Select value={(extractionStrategy.default_memory_type as string) ?? "episodic_memory"} onValueChange={(v) => handleStrategyChange("extraction_strategy", "default_memory_type", v)}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {ALL_MEMORY_TYPES.map((t) => (<SelectItem key={t} value={t}>{t}</SelectItem>))}
                        </SelectContent>
                      </Select>
                      <p className="text-xs text-muted-foreground">{st.defaultMemoryTypeHint}</p>
                    </div>
                    <div className="space-y-2">
                      <Label className="text-sm">{st.defaultStatus}</Label>
                      <Select value={(extractionStrategy.default_status as string) ?? "candidate"} onValueChange={(v) => handleStrategyChange("extraction_strategy", "default_status", v)}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="candidate">candidate</SelectItem>
                          <SelectItem value="active">active</SelectItem>
                        </SelectContent>
                      </Select>
                      <p className="text-xs text-muted-foreground">{st.defaultStatusHint}</p>
                    </div>
                    <div className="space-y-2">
                      <Label className="text-sm">{st.defaultDecayPolicy}</Label>
                      <Select value={(extractionStrategy.default_decay_policy as string) ?? "review"} onValueChange={(v) => handleStrategyChange("extraction_strategy", "default_decay_policy", v)}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="review">review</SelectItem>
                          <SelectItem value="standard">standard</SelectItem>
                          <SelectItem value="slow">slow</SelectItem>
                          <SelectItem value="never">never</SelectItem>
                        </SelectContent>
                      </Select>
                      <p className="text-xs text-muted-foreground">{st.defaultDecayPolicyHint}</p>
                    </div>
                    <NumberField label={st.titleMaxLength} hint={st.titleMaxLengthHint} value={(extractionStrategy.title_max_length as number) ?? 80} min={40} onChange={(v) => handleStrategyChange("extraction_strategy", "title_max_length", v)} />
                    <div className="space-y-2">
                      <Label className="text-sm">{st.defaultScope}</Label>
                      <Select value={(extractionStrategy.default_scope as string) ?? "global"} onValueChange={(v) => handleStrategyChange("extraction_strategy", "default_scope", v)}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="global">global</SelectItem>
                          <SelectItem value="session">session</SelectItem>
                          <SelectItem value="agent">agent</SelectItem>
                        </SelectContent>
                      </Select>
                      <p className="text-xs text-muted-foreground">{st.defaultScopeHint}</p>
                    </div>
                  </AccordionContent>
                </AccordionItem>
              </Accordion>
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </div>
  )
}
