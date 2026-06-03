"use client"

import { useState } from "react"
import { Eye, EyeOff, Download, Upload } from "lucide-react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card"
import { Input } from "./ui/input"
import { Label } from "./ui/label"
import { Slider } from "./ui/slider"
import { Switch } from "./ui/switch"
import { Button } from "./ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import { Textarea } from "./ui/textarea"
import { useRef, useState as useReactState } from "react"
import { useSelector } from "react-redux"
import { RootState } from "@/store/store"

interface FormViewProps {
  settings: any
  onChange: (settings: any) => void
}

export function FormView({ settings, onChange }: FormViewProps) {
  const [showLlmAdvanced, setShowLlmAdvanced] = useState(false)
  const [showLlmApiKey, setShowLlmApiKey] = useState(false)
  const [showEmbedderApiKey, setShowEmbedderApiKey] = useState(false)
  const [isUploading, setIsUploading] = useReactState(false)
  const [selectedImportFileName, setSelectedImportFileName] = useReactState("")
  const fileInputRef = useRef<HTMLInputElement>(null)
  const API_URL = process.env.NEXT_PUBLIC_API_URL || ""
  const userId = useSelector((state: RootState) => state.profile.userId)

  const handleMemoryCoreChange = (key: string, value: any) => {
    onChange({
      ...settings,
      settings: {
        ...settings.settings,
        [key]: value,
      },
    })
  }

  const handleExtractionChange = (key: string, value: any) => {
    onChange({
      ...settings,
      llm: {
        ...settings.llm,
        extraction: {
          ...settings.llm?.extraction,
          [key]: value,
        },
      },
    })
  }

  const handleEmbeddingChange = (key: string, value: any) => {
    onChange({
      ...settings,
      llm: {
        ...settings.llm,
        embedding: {
          ...settings.llm?.embedding,
          [key]: value,
        },
      },
    })
  }

  const isEmbeddingOllama = settings.llm?.embedding?.provider?.toLowerCase() === "ollama"

  return (
    <div className="space-y-8">
      {/* MemoryCore Settings */}
      <Card>
        <CardHeader>
          <CardTitle>MemoryCore Settings</CardTitle>
          <CardDescription>Configure your MemoryCore instance settings</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="space-y-2">
            <Label htmlFor="custom-instructions">Custom Instructions</Label>
            <Textarea
              id="custom-instructions"
              placeholder="Enter custom instructions for memory management..."
              value={settings.settings?.custom_instructions || ""}
              onChange={(e) => handleMemoryCoreChange("custom_instructions", e.target.value)}
              className="min-h-[100px]"
            />
            <p className="text-xs text-muted-foreground mt-1">
              Custom instructions that will be used to guide memory processing and fact extraction.
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Extraction LLM Settings */}
      <Card>
        <CardHeader>
          <CardTitle>Extraction LLM</CardTitle>
          <CardDescription>LLM used for memory fact extraction (config.yaml: extraction.*)</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="extraction-base-url">Base URL</Label>
            <Input
              id="extraction-base-url"
              placeholder="http://127.0.0.1:8317/v1"
              value={settings.llm?.extraction?.base_url || ""}
              onChange={(e) => handleExtractionChange("base_url", e.target.value)}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="extraction-model">Model</Label>
            <Input
              id="extraction-model"
              placeholder="gpt-4o-mini"
              value={settings.llm?.extraction?.model || ""}
              onChange={(e) => handleExtractionChange("model", e.target.value)}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="extraction-api-key">API Key</Label>
            <div className="relative">
              <Input
                id="extraction-api-key"
                type={showLlmApiKey ? "text" : "password"}
                placeholder="env:OPENAI_API_KEY"
                value={settings.llm?.extraction?.api_key || ""}
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
            <p className="text-xs text-muted-foreground">Use "env:VAR_NAME" to load from environment variable</p>
          </div>

          <div className="flex items-center space-x-2 pt-2">
            <Switch id="extraction-advanced" checked={showLlmAdvanced} onCheckedChange={setShowLlmAdvanced} />
            <Label htmlFor="extraction-advanced">Show advanced settings</Label>
          </div>

          {showLlmAdvanced && (
            <div className="space-y-4 pt-2">
              <div className="space-y-2">
                <Label htmlFor="extraction-temperature">
                  Temperature: {settings.llm?.extraction?.temperature ?? 0.1}
                </Label>
                <Slider
                  id="extraction-temperature"
                  min={0}
                  max={1}
                  step={0.05}
                  value={[settings.llm?.extraction?.temperature ?? 0.1]}
                  onValueChange={(value) => handleExtractionChange("temperature", value[0])}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="extraction-max-tokens">Max Tokens</Label>
                <Input
                  id="extraction-max-tokens"
                  type="number"
                  placeholder="2000"
                  value={settings.llm?.extraction?.max_tokens || ""}
                  onChange={(e) => handleExtractionChange("max_tokens", Number.parseInt(e.target.value) || "")}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="extraction-timeout">Timeout (s)</Label>
                <Input
                  id="extraction-timeout"
                  type="number"
                  placeholder="180"
                  value={settings.llm?.extraction?.timeout || ""}
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
          <CardTitle>Embedding Model</CardTitle>
          <CardDescription>Vector embedding provider and model (config.yaml: embedding.*)</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="embedding-provider">Provider</Label>
            <Select
              value={settings.llm?.embedding?.provider || "auto"}
              onValueChange={(v) => handleEmbeddingChange("provider", v)}
            >
              <SelectTrigger id="embedding-provider">
                <SelectValue placeholder="Select a provider" />
              </SelectTrigger>
              <SelectContent>
                {["auto", "ollama", "openai", "api", "sentence-transformers", "hashing"].map((p) => (
                  <SelectItem key={p} value={p}>{p}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="embedding-model">Model</Label>
            <Input
              id="embedding-model"
              placeholder="nomic-embed-text"
              value={settings.llm?.embedding?.model || ""}
              onChange={(e) => handleEmbeddingChange("model", e.target.value)}
            />
          </div>

          {isEmbeddingOllama && (
            <div className="space-y-2">
              <Label htmlFor="embedding-ollama-url">Ollama URL</Label>
              <Input
                id="embedding-ollama-url"
                placeholder="http://127.0.0.1:11434"
                value={settings.llm?.embedding?.ollama_url || ""}
                onChange={(e) => handleEmbeddingChange("ollama_url", e.target.value)}
              />
            </div>
          )}

          {["openai", "api"].includes(settings.llm?.embedding?.provider || "") && (
            <>
              <div className="space-y-2">
                <Label htmlFor="embedding-api-key">API Key</Label>
                <div className="relative">
                  <Input
                    id="embedding-api-key"
                    type={showEmbedderApiKey ? "text" : "password"}
                    placeholder="env:OPENAI_API_KEY"
                    value={settings.llm?.embedding?.api_key || ""}
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
              {settings.llm?.embedding?.provider === "api" && (
                <div className="space-y-2">
                  <Label htmlFor="embedding-api-url">API URL</Label>
                  <Input
                    id="embedding-api-url"
                    placeholder="http://127.0.0.1:11434/v1/embeddings"
                    value={settings.llm?.embedding?.api_url || ""}
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
          <CardTitle>Backup</CardTitle>
          <CardDescription>Export or import your memories</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Export Section */}
          <div className="p-4 border border-border rounded-lg space-y-2">
            <div className="text-sm font-medium">Export</div>
            <p className="text-xs text-muted-foreground">Download a ZIP containing your memories.</p>
            <div>
              <Button
                type="button"
                className="bg-muted hover:bg-muted"
                onClick={async () => {
                  try {
                    const res = await fetch(`${API_URL}/api/v1/backup/export`, {
                      method: "POST",
                      headers: { "Content-Type": "application/json", Accept: "application/zip" },
                      body: JSON.stringify({ user_id: userId }),
                    })
                    if (!res.ok) throw new Error(`Export failed with status ${res.status}`)
                    const blob = await res.blob()
                    const url = window.URL.createObjectURL(blob)
                    const a = document.createElement("a")
                    a.href = url
                    a.download = `memories_export.zip`
                    document.body.appendChild(a)
                    a.click()
                    a.remove()
                    window.URL.revokeObjectURL(url)
                  } catch (e) {
                    console.error(e)
                    alert("Export failed. Check console for details.")
                  }
                }}
              >
                <Download className="h-4 w-4 mr-2" /> Export Memories
              </Button>
            </div>
          </div>

          {/* Import Section */}
          <div className="p-4 border border-border rounded-lg space-y-2">
            <div className="text-sm font-medium">Import</div>
            <p className="text-xs text-muted-foreground">Upload a ZIP archive to import memories. Default settings will be used.</p>
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
                className="bg-muted hover:bg-muted"
                onClick={() => {
                  if (fileInputRef.current) fileInputRef.current.click()
                }}
              >
                <Upload className="h-4 w-4 mr-2" /> Choose ZIP
              </Button>
              <span className="text-xs text-muted-foreground truncate max-w-[220px]">
                {selectedImportFileName || "No file selected"}
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
                      if (!res.ok) throw new Error(`Import failed with status ${res.status}`)
                      await res.json()
                      if (fileInputRef.current) fileInputRef.current.value = ""
                      setSelectedImportFileName("")
                    } catch (e) {
                      console.error(e)
                      alert("Import failed. Check console for details.")
                    } finally {
                      setIsUploading(false)
                    }
                  }}
                >
                  {isUploading ? "Uploading..." : "Import"}
                </Button>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
} 