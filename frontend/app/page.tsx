"use client"

import { useState } from "react"
import { ChatInterface } from "@/components/chat-interface"
import { DataSidebar } from "@/components/data-sidebar"
import { Login } from "@/components/login"
import { Button } from "@/components/ui/button"
import { LogOut, User, ShieldCheck } from "lucide-react"

export default function Home() {
  const [userRole, setUserRole] = useState<string | null>(null)
  const [userName, setUserName] = useState<string | null>(null)

  const handleLogin = (role: string, name: string) => {
    setUserRole(role)
    setUserName(name)
  }

  const handleLogout = () => {
    setUserRole(null)
    setUserName(null)
  }

  if (!userRole) {
    return <Login onLogin={handleLogin} />
  }

  return (
    <div className="flex h-screen w-full flex-col overflow-hidden bg-background">
      {/* Top Navigation Bar */}
      <header className="flex h-14 items-center justify-between border-b border-border bg-card px-6">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 rounded-lg bg-primary/10 px-3 py-1.5">
            <ShieldCheck className="size-4 text-primary" />
            <span className="text-sm font-semibold text-primary">Enterprise Secure AI</span>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <User className="size-4" />
            <span>
              Logged in as: <span className="font-medium text-foreground">{userName}</span> 
              <span className="mx-2 text-border">|</span>
              Role: <span className="font-medium text-primary">{userRole}</span>
            </span>
          </div>
          <Button variant="ghost" size="sm" onClick={handleLogout} className="text-muted-foreground hover:text-destructive">
            <LogOut className="mr-2 size-4" />
            Logout
          </Button>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        <DataSidebar />
        <main className="flex flex-1 flex-col overflow-hidden">
          <ChatInterface userRole={userRole} />
        </main>
      </div>
    </div>
  )
}
