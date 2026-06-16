"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { Loader2, Stethoscope } from "lucide-react";

import { useAuth } from "@/contexts/auth-context";

export function LoginForm() {
  const { signIn, signUp } = useAuth();
  const router = useRouter();
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setInfo(null);
    setSubmitting(true);

    const result =
      mode === "signin"
        ? await signIn(email.trim(), password)
        : await signUp(email.trim(), password);

    setSubmitting(false);

    if (result.error) {
      setError(result.error);
      return;
    }

    if (mode === "signup") {
      setInfo("สมัครสมาชิกสำเร็จ — ตรวจสอบอีเมลหรือลองเข้าสู่ระบบ");
      setMode("signin");
      return;
    }

    router.replace("/chat");
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#0d0d0d] px-4">
      <div className="w-full max-w-md rounded-2xl border border-white/10 bg-[#171717] p-8 shadow-2xl">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-600/20 text-emerald-400">
            <Stethoscope className="h-7 w-7" />
          </div>
          <h1 className="text-2xl font-semibold text-white">Medical AI Assistant</h1>
          <p className="text-sm text-zinc-400">
            เข้าสู่ระบบเพื่อเริ่มแชท triage และ clinical support
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="email" className="mb-1.5 block text-sm text-zinc-300">
              อีเมล
            </label>
            <input
              id="email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-xl border border-white/10 bg-[#0d0d0d] px-4 py-3 text-white outline-none transition focus:border-emerald-500/60 focus:ring-2 focus:ring-emerald-500/20"
              placeholder="you@hospital.org"
            />
          </div>

          <div>
            <label htmlFor="password" className="mb-1.5 block text-sm text-zinc-300">
              รหัสผ่าน
            </label>
            <input
              id="password"
              type="password"
              required
              minLength={6}
              autoComplete={mode === "signin" ? "current-password" : "new-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-xl border border-white/10 bg-[#0d0d0d] px-4 py-3 text-white outline-none transition focus:border-emerald-500/60 focus:ring-2 focus:ring-emerald-500/20"
              placeholder="••••••••"
            />
          </div>

          {error && (
            <p className="rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-400">{error}</p>
          )}
          {info && (
            <p className="rounded-lg bg-emerald-500/10 px-3 py-2 text-sm text-emerald-400">
              {info}
            </p>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-600 py-3 font-medium text-white transition hover:bg-emerald-500 disabled:opacity-60"
          >
            {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
            {mode === "signin" ? "เข้าสู่ระบบ" : "สมัครสมาชิก"}
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-zinc-400">
          {mode === "signin" ? "ยังไม่มีบัญชี?" : "มีบัญชีแล้ว?"}{" "}
          <button
            type="button"
            onClick={() => {
              setMode(mode === "signin" ? "signup" : "signin");
              setError(null);
              setInfo(null);
            }}
            className="text-emerald-400 hover:underline"
          >
            {mode === "signin" ? "สมัครสมาชิก" : "เข้าสู่ระบบ"}
          </button>
        </p>
      </div>
    </div>
  );
}
