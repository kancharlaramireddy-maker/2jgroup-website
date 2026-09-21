import { Suspense } from "react"
import { AdminPanel } from "./panel"

export default function AdminPage() {
  return (
    <Suspense fallback={<div className="p-6">Loading...</div>}>
      <AdminPanel />
    </Suspense>
  )
}
