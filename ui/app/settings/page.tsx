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
import { useConfig } from "@/hooks/useConfig"
import { useSelector } from "react-redux"
import { RootState } from "@/store/store"
import { useToast } from "@/components/ui/use-toast"
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

export default function SettingsPage() {
  const { toast } = useToast()
  const configState = useSelector((state: RootState) => state.config)
  const [settings, setSettings] = useState({
    settings: configState.settings || {
      custom_instructions: null
    },
    llm: configState.llm
  })
  const [viewMode, setViewMode] = useState<"form" | "json">("form")
  const [apiUrl, setApiUrl] = useState(DEFAULT_API_URL)
  const { fetchConfig, saveConfig, resetConfig, isLoading, error } = useConfig()

  useEffect(() => {
    setApiUrl(getApiBaseUrl())
    // Load config from API on component mount
    const loadConfig = async () => {
      try {
        await fetchConfig()
      } catch (error) {
        toast({
          title: "Error",
          description: "Failed to load configuration",
          variant: "destructive",
        })
      }
    }
    
    loadConfig()
  }, [])

  // Update local state when redux state changes
  useEffect(() => {
    setSettings(prev => ({
      ...prev,
      settings: configState.settings || { custom_instructions: null },
      llm: configState.llm
    }))
  }, [configState.settings, configState.llm])

  const handleSave = async () => {
    try {
      setApiUrl(setApiBaseUrl(apiUrl))
      await saveConfig({
        settings: settings.settings,
        llm: settings.llm
      })
      toast({
        title: "Settings saved",
        description: "Your configuration has been updated successfully.",
      })
    } catch (error) {
      toast({
        title: "Error",
        description: "Failed to save configuration",
        variant: "destructive",
      })
    }
  }

  const handleReset = async () => {
    try {
      setApiUrl(setApiBaseUrl(DEFAULT_API_URL))
      await resetConfig()
      toast({
        title: "Settings reset",
        description: "Configuration has been reset to default values.",
      })
      await fetchConfig()
    } catch (error) {
      toast({
        title: "Error",
        description: "Failed to reset configuration",
        variant: "destructive",
      })
    }
  }

  return (
    <div className="text-white py-6">
      <div className="container mx-auto py-10 max-w-4xl">
        <div className="flex justify-between items-center mb-8">
          <div className="animate-fade-slide-down">
            <h1 className="text-3xl font-bold tracking-tight text-white">Settings</h1>
            <p className="text-zinc-400 mt-1">Manage your MemoryCore configuration</p>
          </div>
          <div className="flex space-x-2">
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="outline" className="border-zinc-800 text-zinc-200 hover:bg-zinc-700 hover:text-zinc-50 animate-fade-slide-down" disabled={isLoading}>
                  <RotateCcw className="mr-2 h-4 w-4" />
                  Reset Defaults
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Reset Configuration?</AlertDialogTitle>
                  <AlertDialogDescription>
                    This will reset all settings to the system defaults. Any custom configuration will be lost.
                    API keys will be set to use environment variables.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction onClick={handleReset} className="bg-red-600 hover:bg-red-700">
                    Reset
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
            
            <Button onClick={handleSave} className="bg-primary hover:bg-primary/90 animate-fade-slide-down" disabled={isLoading}>
              <SaveIcon className="mr-2 h-4 w-4" />
              {isLoading ? "Saving..." : "Save Configuration"}
            </Button>
          </div>
        </div>

        <Card className="mb-8 animate-fade-slide-down delay-1">
          <CardHeader>
            <CardTitle>API Connection</CardTitle>
            <CardDescription>Configure the MemoryCore backend API endpoint</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              <Label htmlFor="api-url">API URL</Label>
              <Input
                id="api-url"
                value={apiUrl}
                placeholder="http://127.0.0.1:8318"
                onChange={(event) => setApiUrl(event.target.value)}
              />
            </div>
          </CardContent>
        </Card>

        <Tabs value={viewMode} onValueChange={(value) => setViewMode(value as "form" | "json")} className="w-full animate-fade-slide-down delay-1">
          <TabsList className="grid w-full grid-cols-2 mb-8">
            <TabsTrigger value="form">Form View</TabsTrigger>
            <TabsTrigger value="json">JSON Editor</TabsTrigger>
          </TabsList>

          <TabsContent value="form">
            <FormView settings={settings} onChange={setSettings} />
          </TabsContent>

          <TabsContent value="json">
            <Card>
              <CardHeader>
                <CardTitle>JSON Configuration</CardTitle>
                <CardDescription>Edit the entire configuration directly as JSON</CardDescription>
              </CardHeader>
              <CardContent>
                <JsonEditor value={settings} onChange={setSettings} />
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  )
}
