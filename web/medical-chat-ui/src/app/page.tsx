"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "@/contexts/auth-context";

export default function HomePage() {
  const { session, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    router.replace(session ? "/chat" : "/login");
  }, [loading, session, router]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#0d0d0d] text-zinc-400">
      กำลังโหลด...
    </div>
  );
}
