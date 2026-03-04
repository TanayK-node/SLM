"use client"

import { useState, useRef } from "react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Separator } from "@/components/ui/separator"
import {
  Database,
  Upload,
  Loader2,
  CheckCircle2,
  FileSpreadsheet,
  FileText,
  Zap,
  X,
} from "lucide-react"

export function DataSidebar() {
  const [connectionString, setConnectionString] = useState("")
  const [isConnecting, setIsConnecting] = useState(false)
  const [isConnected, setIsConnected] = useState(false)
  const [isUploading, setIsUploading] = useState(false)
  const [uploadedFile, setUploadedFile] = useState<File | null>(null)
  const [uploadedFileName, setUploadedFileName] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [isUploadingDoc, setIsUploadingDoc] = useState(false)
  const [selectedDoc, setSelectedDoc] = useState<File | null>(null)
  const [uploadedDocs, setUploadedDocs] = useState<string[]>([])
  const docInputRef = useRef<HTMLInputElement>(null)

  async function handleConnectDB() {
    if (!connectionString.trim()) {
      toast.error("Please enter a connection string")
      return
    }
    setIsConnecting(true)
    try {
      const res = await fetch("http://localhost:8000/connect_db", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ connection_string: connectionString }),
      })
      if (!res.ok) throw new Error("Connection failed")
      setIsConnected(true)
      toast.success("Database connected successfully")
    } catch {
      toast.error("Failed to connect to database")
      setIsConnected(false)
    } finally {
      setIsConnecting(false)
    }
  }

  async function handleUploadFile() {
    if (!uploadedFile) {
      toast.error("Please select a file first")
      return
    }
    setIsUploading(true)
    try {
      const formData = new FormData()
      formData.append("file", uploadedFile)
      const res = await fetch("http://localhost:8000/upload_file", {
        method: "POST",
        body: formData,
      })
      if (!res.ok) throw new Error("Upload failed")
      setUploadedFileName(uploadedFile.name)
      setUploadedFile(null)
      if (fileInputRef.current) fileInputRef.current.value = ""
      toast.success("File uploaded successfully")
    } catch {
      toast.error("Failed to upload file")
    } finally {
      setIsUploading(false)
    }
  }

  async function handleUploadDocument() {
    if (!selectedDoc) {
      toast.error("Please select a document first")
      return
    }
    setIsUploadingDoc(true)
    try {
      const formData = new FormData()
      formData.append("file", selectedDoc)
      const res = await fetch("http://localhost:8000/upload_document", {
        method: "POST",
        body: formData,
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail ?? "Upload failed")
      }
      setUploadedDocs((prev) => [...prev, selectedDoc.name])
      setSelectedDoc(null)
      if (docInputRef.current) docInputRef.current.value = ""
      toast.success("Document ingested into RAG successfully")
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : "Failed to upload document"
      toast.error(message)
    } finally {
      setIsUploadingDoc(false)
    }
  }

  return (
    <aside className="flex h-full w-80 flex-col border-r border-border bg-sidebar">
      {/* Header */}
      <div className="flex items-center gap-3 px-5 py-5">
        <div className="flex size-8 items-center justify-center rounded-lg bg-primary">
          <Zap className="size-4 text-primary-foreground" />
        </div>
        <div>
          <h1 className="text-sm font-semibold text-sidebar-foreground">
            AI Copilot
          </h1>
          <p className="text-xs text-muted-foreground">Data Sources</p>
        </div>
      </div>

      <Separator />

      <div className="flex flex-1 flex-col gap-6 overflow-y-auto p-5">
        {/* Database Connection */}
        <section className="flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <Database className="size-4 text-primary" />
            <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Database Connection
            </h2>
          </div>

          <div className="flex flex-col gap-2.5 rounded-lg border border-border bg-card p-3">
            <Input
              placeholder="postgresql://user:pass@host/db"
              value={connectionString}
              onChange={(e) => setConnectionString(e.target.value)}
              className="h-8 bg-background font-mono text-xs"
              disabled={isConnecting}
            />
            <Button
              onClick={handleConnectDB}
              disabled={isConnecting || !connectionString.trim()}
              size="sm"
              className="w-full"
            >
              {isConnecting ? (
                <>
                  <Loader2 className="size-3.5 animate-spin" />
                  Connecting...
                </>
              ) : isConnected ? (
                <>
                  <CheckCircle2 className="size-3.5" />
                  Connected
                </>
              ) : (
                <>
                  <Database className="size-3.5" />
                  Connect DB
                </>
              )}
            </Button>
          </div>

          {isConnected && (
            <div className="flex items-center gap-2 rounded-md bg-primary/10 px-3 py-2">
              <div className="size-1.5 rounded-full bg-primary animate-pulse" />
              <span className="text-xs text-primary">
                Database active
              </span>
            </div>
          )}
        </section>

        {/* Document Upload (RAG) */}
        <section className="flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <FileText className="size-4 text-primary" />
            <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Document Upload
            </h2>
          </div>

          <div className="flex flex-col gap-2.5 rounded-lg border border-border bg-card p-3">
            <div className="relative">
              <input
                ref={docInputRef}
                type="file"
                accept=".pdf,.docx,.txt"
                onChange={(e) => {
                  const file = e.target.files?.[0] ?? null
                  setSelectedDoc(file)
                }}
                className="absolute inset-0 cursor-pointer opacity-0"
                disabled={isUploadingDoc}
              />
              <div className="flex items-center gap-2 rounded-md border border-dashed border-border bg-background px-3 py-3 text-xs text-muted-foreground transition-colors hover:border-primary/50 hover:bg-primary/5">
                <Upload className="size-4 shrink-0" />
                <span className="truncate">
                  {selectedDoc ? selectedDoc.name : "Choose .pdf, .docx, or .txt"}
                </span>
              </div>
            </div>

            <Button
              onClick={handleUploadDocument}
              disabled={isUploadingDoc || !selectedDoc}
              size="sm"
              variant="secondary"
              className="w-full"
            >
              {isUploadingDoc ? (
                <>
                  <Loader2 className="size-3.5 animate-spin" />
                  Ingesting...
                </>
              ) : (
                <>
                  <Upload className="size-3.5" />
                  Upload Document
                </>
              )}
            </Button>
          </div>

          {uploadedDocs.length > 0 && (
            <div className="flex flex-col gap-1.5">
              {uploadedDocs.map((name) => (
                <div key={name} className="flex items-center justify-between rounded-md bg-secondary px-3 py-2">
                  <div className="flex items-center gap-2">
                    <FileText className="size-3.5 text-primary shrink-0" />
                    <span className="max-w-[160px] truncate text-xs text-secondary-foreground">{name}</span>
                  </div>
                  <button
                    onClick={() => setUploadedDocs((prev) => prev.filter((n) => n !== name))}
                    className="text-muted-foreground transition-colors hover:text-foreground"
                  >
                    <X className="size-3" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Tabular Upload */}
        <section className="flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <FileSpreadsheet className="size-4 text-primary" />
            <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Tabular Upload
            </h2>
          </div>

          <div className="flex flex-col gap-2.5 rounded-lg border border-border bg-card p-3">
            <div className="relative">
              <input
                ref={fileInputRef}
                type="file"
                accept=".csv,.xlsx"
                onChange={(e) => {
                  const file = e.target.files?.[0] ?? null
                  setUploadedFile(file)
                }}
                className="absolute inset-0 cursor-pointer opacity-0"
                disabled={isUploading}
              />
              <div className="flex items-center gap-2 rounded-md border border-dashed border-border bg-background px-3 py-3 text-xs text-muted-foreground transition-colors hover:border-primary/50 hover:bg-primary/5">
                <Upload className="size-4 shrink-0" />
                <span className="truncate">
                  {uploadedFile ? uploadedFile.name : "Choose .csv or .xlsx"}
                </span>
              </div>
            </div>

            <Button
              onClick={handleUploadFile}
              disabled={isUploading || !uploadedFile}
              size="sm"
              variant="secondary"
              className="w-full"
            >
              {isUploading ? (
                <>
                  <Loader2 className="size-3.5 animate-spin" />
                  Uploading...
                </>
              ) : (
                <>
                  <Upload className="size-3.5" />
                  Upload File
                </>
              )}
            </Button>
          </div>

          {uploadedFileName && (
            <div className="flex items-center justify-between rounded-md bg-secondary px-3 py-2">
              <div className="flex items-center gap-2">
                <FileSpreadsheet className="size-3.5 text-primary" />
                <span className="max-w-[160px] truncate text-xs text-secondary-foreground">
                  {uploadedFileName}
                </span>
              </div>
              <button
                onClick={() => setUploadedFileName(null)}
                className="text-muted-foreground transition-colors hover:text-foreground"
              >
                <X className="size-3" />
              </button>
            </div>
          )}
        </section>
      </div>

      {/* Footer */}
      <div className="border-t border-border px-5 py-4">
        <p className="text-center text-[10px] text-muted-foreground">
          Powered by AI Copilot Engine v2.0
        </p>
      </div>
    </aside>
  )
}
