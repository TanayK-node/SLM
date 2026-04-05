"use client"

import { useState, useRef, useEffect } from "react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import {
  Send,
  Loader2,
  Sparkles,
  User,
  Bot,
} from "lucide-react"

type Message = {
  id: string
  role: "user" | "assistant"
  content: string
  intentUsed?: string
}

const INTENT_CONFIG: Record<string, { label: string; icon: string; className: string }> = {
  sql: {
    label: "SQL Engine",
    icon: "\u26A1",
    className: "border-amber-500/30 bg-amber-500/10 text-amber-400",
  },
  csv: {
    label: "CSV Engine",
    icon: "\uD83D\uDCCA",
    className: "border-blue-500/30 bg-blue-500/10 text-blue-400",
  },
  rag: {
    label: "RAG Engine",
    icon: "\uD83D\uDCC4",
    className: "border-emerald-500/30 bg-emerald-500/10 text-emerald-400",
  },
  chat: {
    label: "Chat Engine",
    icon: "\uD83E\uDDE0",
    className: "border-pink-500/30 bg-pink-500/10 text-pink-400",
  },
}

function getIntentConfig(intentUsed: string) {
  const key = intentUsed.toLowerCase()
  if (key.includes("sql")) return INTENT_CONFIG.sql
  if (key.includes("csv")) return INTENT_CONFIG.csv
  if (key.includes("rag")) return INTENT_CONFIG.rag
  if (key.includes("chat")) return INTENT_CONFIG.chat
  return {
    label: intentUsed,
    icon: "\u2728",
    className: "border-primary/30 bg-primary/10 text-primary",
  }
}

interface ChatInterfaceProps {
  userRole: string
}

export function ChatInterface({ userRole }: ChatInterfaceProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, isLoading])

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  async function handleSend() {
    const query = input.trim()
    if (!query || isLoading) return

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: query,
    }
    const historyToSend = messages.slice(-6).map((m) => ({
      role: m.role,
      content: m.content,
    }))
    
    const assistantId = crypto.randomUUID()
    const emptyAssistantMsg: Message = {
      id: assistantId,
      role: "assistant",
      content: "",
      intentUsed: "CHAT", // Default, will be updated
    }

    setMessages((prev) => [...prev, userMsg, emptyAssistantMsg])
    setInput("")
    setIsLoading(true)

    try {
      const res = await fetch("http://localhost:8000/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          query: query, 
          history: historyToSend,
          role: userRole
        }),
      })

      if (!res.ok) throw new Error("Chat request failed")

      // Extract the intent from the custom header
      const intentUsed = res.headers.get("X-Intent-Used") || "CHAT"
      
      const reader = res.body?.getReader()
      const decoder = new TextDecoder()
      let firstChunk = true

      if (!reader) throw new Error("No reader available")

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        if (firstChunk) {
          setIsLoading(false)
          firstChunk = false
        }

        const chunk = decoder.decode(value, { stream: true })
        
        setMessages((prev) => 
          prev.map((msg) => 
            msg.id === assistantId 
              ? { ...msg, content: msg.content + chunk, intentUsed } 
              : msg
          )
        )
      }
    } catch (error) {
      console.error("Streaming error:", error)
      toast.error("Failed to get a response. Please try again.")
      setIsLoading(false)
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex flex-1 flex-col bg-background">
      {/* Header */}
      <header className="flex items-center justify-between border-b border-border px-6 py-4">
        <div className="flex items-center gap-3">
          <div className="flex size-8 items-center justify-center rounded-lg bg-primary/10">
            <Sparkles className="size-4 text-primary" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-foreground">
              Chat Interface
            </h2>
            <p className="text-xs text-muted-foreground">
              Ask anything about your data
            </p>
          </div>
        </div>
        <Badge variant="outline" className="text-xs text-muted-foreground">
          {messages.filter((m) => m.role === "assistant").length} responses
        </Badge>
      </header>

      {/* Messages */}
      <div ref={scrollRef} className="flex flex-1 flex-col gap-6 overflow-y-auto p-6">
        {messages.length === 0 && !isLoading && <EmptyState />}

        {messages.map((msg) =>
          msg.role === "user" ? (
            <UserBubble key={msg.id} content={msg.content} />
          ) : (
            <AssistantBubble
              key={msg.id}
              content={msg.content}
              intentUsed={msg.intentUsed}
            />
          )
        )}

        {isLoading && <TypingIndicator />}
      </div>

      {/* Input Area */}
      <div className="border-t border-border p-4">
        <div className="mx-auto flex max-w-3xl items-end gap-3">
          <div className="relative flex-1">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask about your data..."
              rows={1}
              className="w-full resize-none rounded-xl border border-border bg-card px-4 py-3 pr-12 text-sm text-foreground placeholder:text-muted-foreground outline-none transition-colors focus:border-primary/50 focus:ring-1 focus:ring-primary/20"
              disabled={isLoading}
            />
          </div>
          <Button
            onClick={handleSend}
            disabled={isLoading || !input.trim()}
            size="icon"
            className="size-11 shrink-0 rounded-xl"
          >
            {isLoading ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Send className="size-4" />
            )}
            <span className="sr-only">Send message</span>
          </Button>
        </div>
      </div>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center py-20">
      <div className="flex size-16 items-center justify-center rounded-2xl bg-primary/10 mb-5">
        <Sparkles className="size-7 text-primary" />
      </div>
      <h3 className="mb-2 text-base font-semibold text-foreground">
        Welcome to AI Copilot
      </h3>
      <p className="mb-6 max-w-md text-center text-sm text-muted-foreground leading-relaxed">
        Connect a database or upload a file using the sidebar, then ask questions
        about your data in natural language.
      </p>
      <div className="flex flex-wrap items-center justify-center gap-2">
        {[
          { icon: "\u26A1", label: "SQL Engine" },
          { icon: "\uD83D\uDCCA", label: "CSV Engine" },
          { icon: "\uD83D\uDCC4", label: "RAG Engine" },
          { icon: "\uD83E\uDDE0", label: "Chat Engine" },
        ].map((engine) => (
          <span
            key={engine.label}
            className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1.5 text-xs text-muted-foreground"
          >
            <span>{engine.icon}</span>
            {engine.label}
          </span>
        ))}
      </div>
    </div>
  )
}

function UserBubble({ content }: { content: string }) {
  return (
    <div className="flex justify-end">
      <div className="flex max-w-[70%] items-start gap-3">
        <div className="rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-sm text-primary-foreground leading-relaxed">
          {content}
        </div>
        <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/20">
          <User className="size-3.5 text-primary" />
        </div>
      </div>
    </div>
  )
}

function AssistantBubble({
  content,
  intentUsed,
}: {
  content: string
  intentUsed?: string
}) {
  const config = intentUsed ? getIntentConfig(intentUsed) : null

  return (
    <div className="flex justify-start">
      <div className="flex max-w-[85%] items-start gap-3">
        <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-secondary">
          <Bot className="size-3.5 text-secondary-foreground" />
        </div>
        <div className="flex flex-col gap-1.5">
          {config && (
            <span
              className={`inline-flex w-fit items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${config.className}`}
            >
              <span>{config.icon}</span>
              {config.label}
            </span>
          )}
          <div className="rounded-2xl rounded-bl-md border border-border bg-card px-4 py-2.5 text-sm text-card-foreground leading-relaxed whitespace-pre-wrap break-words">
            {content}
          </div>
        </div>
      </div>
    </div>
  )
}

function TypingIndicator() {
  return (
    <div className="flex justify-start">
      <div className="flex items-start gap-3">
        <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-secondary">
          <Bot className="size-3.5 text-secondary-foreground" />
        </div>
        <div className="flex items-center gap-1.5 rounded-2xl rounded-bl-md border border-border bg-card px-4 py-3">
          <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:0ms]" />
          <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:150ms]" />
          <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:300ms]" />
        </div>
      </div>
    </div>
  )
}
