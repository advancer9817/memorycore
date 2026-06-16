"use client"

import { useState, useEffect, useCallback } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Slider } from "@/components/ui/slider"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { SaveIcon, RotateCcw, ChevronDown, ChevronUp, SlidersHorizontal } from "lucide-react"
import { useSelector } from "react-redux"
import { RootState } from "@/store/store"
import { useConfig } from "@/hooks/useConfig"
import { useI18n } from "@/hooks/useI18n"
import { useToast } from "@/hooks/use-toast"

const PRESETS = {
  economy: {
    label: "economy",
    temperature: 0.2,
    sim_threshold: 0.75,
    split_content_threshold: 800,
    importance_limit: 200,
    content_max_chars: 800,
    batch_size: 20,
    review_cooldown_seconds: 7200,
    keep_threshold: 0.1,
    auto_approve_confidence: 0.95,
    prompt_style: "conservative",
    reviewed_ids_max_age_seconds: 172800,
  },
  balanced: {
    label: "balanced",
    temperature: 0.4,
    sim_threshold: 0.60,
    split_content_threshold: 500,
    importance_limit: 500,
    content_max_chars: 1500,
    batch_size: 10,
    review_cooldown_seconds: 3600,
    keep_threshold: 0.05,
    auto_approve_confidence: 0.85,
    prompt_style: "balanced",
    reviewed_ids_max_age_seconds: 86400,
  },
  precision: {
    label: "precision",
    temperature: 0.3,
    sim_threshold: 0.80,
    split_content_threshold: 300,
    importance_limit: 500,
    content_max_chars: 2000,
    batch_size: 5,
    review_cooldown_seconds: 1800,
    keep_threshold: 0.01,
    auto_approve_confidence: 0.95,
    prompt_style: "balanced",
    reviewed_ids_max_age_seconds: 86400,
  },
  aggressive: {
    label: "aggressive",
    temperature: 0.6,
    sim_threshold: 0.50,
    split_content_threshold: 400,
    importance_limit: 1000,
    content_max_chars: 2000,
    batch_size: 10,
    review_cooldown_seconds: 1800,
    keep_threshold: 0.02,
    auto_approve_confidence: 0.90,
    prompt_style: "aggressive",
    reviewed_ids_max_age_seconds: 86400,
  },
  deep: {
    label: "deep",
    temperature: 0.8,
    sim_threshold: 0.40,
    split_content_threshold: 200,
    importance_limit: 2000,
    content_max_chars: 5000,
    batch_size: 5,
    review_cooldown_seconds: 900,
    keep_threshold: 0.01,
    auto_approve_confidence: 0.80,
    prompt_style: "aggressive",
    reviewed_ids_max_age_seconds: 43200,
  },
} as const;

type PresetKey = keyof typeof PRESETS;

const DIMENSIONS = [
  { key: "temperature", min: 0, max: 1, step: 0.05, section: "llm_curator" },
  { key: "sim_threshold", min: 0, max: 1, step: 0.01, section: "llm_curator" },
  { key: "split_content_threshold", min: 100, max: 2000, step: 50, section: "llm_curator" },
  { key: "importance_limit", min: 100, max: 3000, step: 100, section: "llm_curator" },
  { key: "content_max_chars", min: 500, max: 5000, step: 100, section: "llm_curator" },
  { key: "batch_size", min: 1, max: 30, step: 1, section: "llm_curator" },
  { key: "review_cooldown_seconds", min: 0, max: 14400, step: 300, section: "llm_curator" },
  { key: "keep_threshold", min: 0, max: 0.2, step: 0.01, section: "llm_curator" },
  { key: "reviewed_ids_max_age_seconds", min: 3600, max: 259200, step: 3600, section: "llm_curator" },
  { key: "auto_approve_confidence", min: 0.5, max: 1, step: 0.01, section: "governance" },
] as const;

export function CuratorTuningPanel() {
  const { messages } = useI18n()
  const t = messages.tuning
  const { toast } = useToast()
  const { saveConfig, fetchConfig } = useConfig()
  const configState = useSelector((state: RootState) => state.config)

  const [expanded, setExpanded] = useState(false)
  const [activePreset, setActivePreset] = useState<PresetKey | "custom">("aggressive")
  const [values, setValues] = useState<Record<string, number | string>>({})
  const [isSaving, setIsSaving] = useState(false)

  // Initialize values from config store
  useEffect(() => {
    const llmCurator = configState.strategy?.llm_curator ?? {}
    const governance = configState.strategy?.governance ?? {}
    const merged: Record<string, number | string> = {}
    for (const dim of DIMENSIONS) {
      const source = dim.section === "governance" ? governance : llmCurator
      const val = source[dim.key as keyof typeof source]
      const preset = PRESETS.aggressive
      merged[dim.key] = typeof val === "number" ? val : preset[dim.key as keyof typeof preset]
    }
    // Detect which preset matches
    const presetName = (llmCurator as Record<string, unknown>).preset as string | undefined
    if (presetName && presetName in PRESETS) {
      setActivePreset(presetName as PresetKey)
    }
    setValues(merged)
  }, [configState.strategy])

  const handlePresetClick = useCallback((key: PresetKey) => {
    const preset = PRESETS[key]
    const newValues: Record<string, number | string> = {}
    for (const dim of DIMENSIONS) {
      newValues[dim.key] = preset[dim.key as keyof typeof preset]
    }
    setValues(newValues)
    setActivePreset(key)
  }, [])

  const handleSliderChange = useCallback((key: string, value: number) => {
    setValues(prev => ({ ...prev, [key]: value }))
    setActivePreset("custom")
  }, [])

  const handleSave = useCallback(async () => {
    setIsSaving(true)
    try {
      const llmCuratorPatch: Record<string, unknown> = { preset: activePreset }
      const governancePatch: Record<string, unknown> = {}
      for (const dim of DIMENSIONS) {
        if (dim.section === "governance") {
          governancePatch[dim.key] = values[dim.key]
        } else {
          llmCuratorPatch[dim.key] = values[dim.key]
        }
      }
      // Also set prompt_style from the preset
      if (activePreset !== "custom" && activePreset in PRESETS) {
        llmCuratorPatch.prompt_style = PRESETS[activePreset].prompt_style
      }
      await saveConfig({
        strategy: {
          ...configState.strategy,
          llm_curator: {
            ...(configState.strategy?.llm_curator ?? {}),
            ...llmCuratorPatch,
          },
          governance: {
            ...(configState.strategy?.governance ?? {}),
            ...governancePatch,
          },
        },
      })
      toast({ description: t.saved })
    } catch {
      toast({ title: messages.common.error, description: messages.settings.saveFailure, variant: "destructive" })
    } finally {
      setIsSaving(false)
    }
  }, [values, activePreset, configState.strategy, saveConfig, toast, t, messages])

  const handleReset = useCallback(() => {
    if (activePreset !== "custom" && activePreset in PRESETS) {
      handlePresetClick(activePreset)
    } else {
      handlePresetClick("aggressive")
    }
  }, [activePreset, handlePresetClick])

  // i18n label lookup for dimension keys
  const dimLabel = useCallback((key: string): string => {
    return (t as Record<string, unknown>)[key] as string ?? key
  }, [t])

  // Format display value
  const formatValue = (key: string, val: number): string => {
    if (key === "review_cooldown_seconds") return `${Math.round(val / 60)}min`
    if (key === "reviewed_ids_max_age_seconds") return `${Math.round(val / 3600)}h`
    if (key === "content_max_chars" || key === "split_content_threshold" || key === "importance_limit" || key === "batch_size") return String(val)
    return val.toFixed(2)
  }

  const presetKeys: PresetKey[] = ["economy", "balanced", "precision", "aggressive", "deep"]

  return (
    <Card>
      <CardHeader className="cursor-pointer" onClick={() => setExpanded(!expanded)}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <SlidersHorizontal className="h-5 w-5 text-primary" />
            <CardTitle className="text-lg">{t.title}</CardTitle>
            {activePreset !== "custom" && (
              <Badge variant="secondary" className="ml-2">
                {(t as Record<string, unknown>)[`preset${activePreset.charAt(0).toUpperCase() + activePreset.slice(1)}`] as string ?? activePreset}
              </Badge>
            )}
            {activePreset === "custom" && (
              <Badge variant="outline" className="ml-2">{t.custom}</Badge>
            )}
          </div>
          <div className="flex items-center gap-2">
            {expanded && (
              <>
                <Button variant="outline" size="sm" onClick={(e) => { e.stopPropagation(); handleReset() }} className="border-zinc-700 text-zinc-300 hover:bg-zinc-800">
                  <RotateCcw className="h-3.5 w-3.5 mr-1" />
                  {t.reset}
                </Button>
                <Button size="sm" onClick={(e) => { e.stopPropagation(); handleSave() }} disabled={isSaving} className="bg-primary hover:bg-primary/90">
                  <SaveIcon className="h-3.5 w-3.5 mr-1" />
                  {t.save}
                </Button>
              </>
            )}
            {expanded ? <ChevronUp className="h-4 w-4 text-zinc-400" /> : <ChevronDown className="h-4 w-4 text-zinc-400" />}
          </div>
        </div>
      </CardHeader>
      {expanded && (
        <CardContent className="space-y-6">
          {/* Preset pills */}
          <div className="flex flex-wrap gap-2">
            {presetKeys.map((key) => (
              <Button
                key={key}
                variant={activePreset === key ? "default" : "outline"}
                size="sm"
                onClick={() => handlePresetClick(key)}
                className={activePreset === key
                  ? "bg-primary text-primary-foreground"
                  : "border-zinc-700 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
                }
              >
                {(t as Record<string, unknown>)[`preset${key.charAt(0).toUpperCase() + key.slice(1)}`] as string ?? key}
              </Button>
            ))}
          </div>

          {/* Sliders grid - 2 columns on desktop */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-4">
            {DIMENSIONS.map((dim) => {
              const val = typeof values[dim.key] === "number" ? (values[dim.key] as number) : dim.min
              return (
                <div key={dim.key} className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <Label className="text-sm text-zinc-300">{dimLabel(dim.key)}</Label>
                    <span className="text-xs text-zinc-500 tabular-nums font-mono">{formatValue(dim.key, val)}</span>
                  </div>
                  <Slider
                    min={dim.min}
                    max={dim.max}
                    step={dim.step}
                    value={[val]}
                    onValueChange={([v]) => handleSliderChange(dim.key, v)}
                  />
                </div>
              )
            })}
          </div>
        </CardContent>
      )}
    </Card>
  )
}
