import { DataSidebar } from "@/components/data-sidebar"
import { ChatInterface } from "@/components/chat-interface"

export default function Home() {
  return (
    <div className="flex h-dvh overflow-hidden">
      <DataSidebar />
      <ChatInterface />
    </div>
  )
}
