"use client";

import { useState, useEffect } from "react"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { SaveIcon, RotateCcw } from "lucide-react"
import { FormView } from "@/components/form-view"
import { JsonEditor } from "@/components/json-editor"
import { BackupSettings } from "@/components/form-view-backup"
import { MaintenanceHistory } from "@/components/settings/MaintenanceHistory"
import { useConfig } from "@/hooks/useConfig"
import { useSelector } from "react-redux"
import { RootState } from "@/store/store"
import { useToast } from "@/hooks/use-toast"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { DEFAULT_API_URL, getApiBaseUrl, setApiBaseUrl } from "@/lib/api-url"
import { useI18n } from "@/hooks/useI18n"
import { PageShell } from "@/components/shared/PageShell"

export default function SettingsPage() {
  const { toast } = useToast()
  const { messages } = useI18n()
  const configState = useSelector((state: RootState) => state.config)
  const [settings, setSettings] = useState({
    settings: configState.settings || {
      custom_instructions: null
    },
    llm: configState.llm,
    strategy: configState.strategy || {},
  })
  const [viewMode, setViewMode] = useState<"form" | "data" | "json">("form")
  const [apiUrl, setApiUrl] = useState(DEFAULT_API_URL)
  const { fetchConfig, saveConfig, resetConfig, isLoading, error } = useConfig()

  useEffect(() => {
    setApiUrl(getApiBaseUrl())
    const loadConfig = async () => {
      try {
        await fetchConfig()
      } catch (error) {
        toast({
          title: messages.common.error,
          description: messages.settings.loadFailure,
          variant: "destructive",
        })
      }
    }
    loadConfig()
  }, [])

  useEffect(() => {
    setSettings(prev => ({
      ...prev,
      settings: configState.settings || { custom_instructions: null },
      llm: configState.llm,
      strategy: configState.strategy || {},
    }))
  }, [configState.settings, configState.llm, configState.strategy])

  const handleSave = async () => {
    try {
      setApiUrl(setApiBaseUrl(apiUrl))
      await saveConfig({
        settings: settings.settings,
        llm: settings.llm,
        strategy: settings.strategy,
      })
      toast({
        title: messages.settings.settingsSavedTitle,
        description: messages.settings.settingsSavedDescription,
      })
    } catch (error) {
      toast({
        title: messages.common.error,
        description: messages.settings.saveFailure,
        variant: "destructive",
      })
    }
  }

  const handleReset = async () => {
    try {
      setApiUrl(setApiBaseUrl(DEFAULT_API_URL))
      await resetConfig()
      toast({
        title: messages.settings.settingsResetTitle,
        description: messages.settings.settingsResetDescription,
      })
      await fetchConfig()
    } catch (error) {
      toast({
        title: messages.common.error,
        description: messages.settings.resetFailure,
        variant: "destructive",
      })
    }
  }

  const headerActions = (
    <div className="flex space-x-2">
      <AlertDialog>
        <AlertDialogTrigger asChild>
          <Button variant="outline" className="border-zinc-800 text-zinc-200 hover:bg-zinc-700 hover:text-zinc-50" disabled={isLoading}>
            <RotateCcw className="mr-2 h-4 w-4" />
            {messages.settings.resetDefaults}
          </Button>
        </AlertDialogTrigger>
        <AlertDialogContent className="border-zinc-800 bg-zinc-950 text-zinc-100">
          <AlertDialogHeader>
            <AlertDialogTitle>{messages.settings.resetTitle}</AlertDialogTitle>
            <AlertDialogDescription className="text-zinc-400">
              {messages.settings.resetDescription}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="border-zinc-700 bg-zinc-900 text-zinc-200 hover:bg-zinc-800">{messages.common.cancel}</AlertDialogCancel>
            <AlertDialogAction onClick={handleReset} className="bg-red-600 hover:bg-red-700">
              {messages.common.reset}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <Button onClick={handleSave} className="bg-primary hover:bg-primary/90" disabled={isLoading}>
        <SaveIcon className="mr-2 h-4 w-4" />
        {isLoading ? messages.common.saving : messages.settings.saveConfiguration}
      </Button>
    </div>
  )

  return (
    <PageShell
      title={messages.settings.title}
      subtitle={messages.settings.description}
      actions={headerActions}
      maxWidth="max-w-4xl"
    >
      <Card className="mb-6 animate-fade-slide-down delay-1">
        <CardHeader>
          <CardTitle>{messages.settings.apiConnection}</CardTitle>
          <CardDescription>{messages.settings.apiConnectionDescription}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <Label htmlFor="api-url">{messages.settings.apiUrl}</Label>
            <Input
              id="api-url"
              value={apiUrl}
              placeholder="http://127.0.0.1:8318"
              onChange={(event) => setApiUrl(event.target.value)}
            />
          </div>
        </CardContent>
      </Card>

      <Tabs value={viewMode} onValueChange={(value) => setViewMode(value as "form" | "data" | "json")} className="w-full animate-fade-slide-down delay-2">
        <TabsList className="grid w-full grid-cols-3 mb-6">
          <TabsTrigger value="form">{messages.settings.formView}</TabsTrigger>
          <TabsTrigger value="data">{messages.settings.dataMaintenance}</TabsTrigger>
          <TabsTrigger value="json">{messages.settings.jsonEditor}</TabsTrigger>
        </TabsList>

        <TabsContent value="form">
          <FormView settings={settings} onChange={setSettings} />
        </TabsContent>

        <TabsContent value="data">
          <div className="space-y-6">
            <BackupSettings />
            <MaintenanceHistory />
          </div>
        </TabsContent>

        <TabsContent value="json">
          <Card>
            <CardHeader>
              <CardTitle>{messages.settings.jsonConfiguration}</CardTitle>
              <CardDescription>{messages.settings.jsonConfigurationDescription}</CardDescription>
            </CardHeader>
            <CardContent>
              <JsonEditor value={settings} onChange={setSettings} />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </PageShell>
  )
}
