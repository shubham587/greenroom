"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { createSession } from "@/lib/api";

export default function Upload() {
  const router = useRouter();
  const [resume, setResume] = useState<File | null>(null);
  const [jd, setJd] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function start() {
    if (!resume) return;
    setBusy(true);
    setError("");
    try {
      const id = await createSession(resume, jd);
      router.push(`/session/${id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "something went wrong");
      setBusy(false);
    }
  }

  return (
    <main>
      <h1>Greenroom</h1>
      <p className="sub">practise the interview before you have it</p>

      <label htmlFor="resume">Your resume — PDF or plain text</label>
      <input
        id="resume"
        type="file"
        accept=".pdf,.txt,.md"
        onChange={(e) => setResume(e.target.files?.[0] ?? null)}
      />

      <label htmlFor="jd">The job description</label>
      <textarea
        id="jd"
        value={jd}
        onChange={(e) => setJd(e.target.value)}
        placeholder="Paste the posting. The questions come from where this and your resume overlap."
      />

      <button onClick={start} disabled={!resume || !jd.trim() || busy}>
        {busy ? "Reading your resume…" : "Start"}
      </button>

      {error && <p className="err">{error}</p>}
    </main>
  );
}
