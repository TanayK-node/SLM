"use client"

import { useState } from "react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Separator } from "@/components/ui/separator"
import {
  Database,
  Loader2,
  CheckCircle2,
  Zap,
} from "lucide-react"

export function DataSidebar() {
  const [connectionString, setConnectionString] = useState("")
  const [isConnecting, setIsConnecting] = useState(false)
  const [isConnected, setIsConnected] = useState(false)

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

        <div className="rounded-lg border border-dashed border-border bg-card/60 px-3 py-4 text-center text-xs text-muted-foreground">
          File upload moved to chat input.
          <br />
          Use the plus button beside the message box.
        </div>
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
