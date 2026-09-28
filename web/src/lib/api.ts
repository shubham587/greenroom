// One place that knows where the API is, so changing it is an env var and
// not a search-and-replace.
export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010";

export type Topic = { name: string; status: string; priority: string };

export type SessionState = {
  state: string;
  stage: string | null;
  turns: number;
  coverage: Topic[];
};

export type Turn = {
  speaker: "candidate" | "interviewer";
  text: string;
  t_start: number;
  ttft_ms: number | null;
};

export async function createSession(resume: File, jd: string): Promise<string> {
  const body = new FormData();
  body.append("resume", resume);
  body.append("jd", jd);

  const res = await fetch(`${API}/sessions`, { method: "POST", body });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail ?? "upload failed");
  }
  return (await res.json()).session_id;
}

export async function getToken(sessionId: string) {
  const res = await fetch(`${API}/sessions/${sessionId}/token`);
  if (!res.ok) throw new Error((await res.json()).detail ?? "no token");
  return res.json() as Promise<{ token: string; url: string; room: string }>;
}

export async function getTurns(sessionId: string): Promise<Turn[]> {
  const res = await fetch(`${API}/sessions/${sessionId}`);
  if (!res.ok) return [];
  return (await res.json()).turns ?? [];
}

// The socket is the only push we have; everything else is a fetch.
export function watchSession(
  sessionId: string,
  onState: (s: SessionState) => void,
): () => void {
  const url = `${API.replace(/^http/, "ws")}/ws/sessions/${sessionId}`;
  const ws = new WebSocket(url);
  ws.onmessage = (e) => onState(JSON.parse(e.data));
  return () => ws.close();
}
