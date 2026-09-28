"use client";

import { Room, RoomEvent, Track } from "livekit-client";
import { use, useCallback, useEffect, useRef, useState } from "react";
import {
  getToken,
  getTurns,
  watchSession,
  type SessionState,
  type Topic,
  type Turn,
} from "@/lib/api";

const WAITING = "Getting your interview ready…";

export default function Session({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);

  const [state, setState] = useState<SessionState | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [joined, setJoined] = useState(false);
  const [error, setError] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const room = useRef<Room | null>(null);

  // session state, pushed
  useEffect(() => watchSession(id, setState), [id]);

  // the transcript is a fetch: it is written by a worker in another process,
  // so there is nothing to push it from
  useEffect(() => {
    if (!joined) return;
    const poll = setInterval(() => getTurns(id).then(setTurns), 2000);
    return () => clearInterval(poll);
  }, [id, joined]);

  useEffect(() => {
    if (!joined) return;
    const t = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [joined]);

  const join = useCallback(async () => {
    try {
      const { token, url } = await getToken(id);
      const r = new Room();
      r.on(RoomEvent.TrackSubscribed, (track) => {
        if (track.kind === Track.Kind.Audio) track.attach().play();
      });
      r.on(RoomEvent.Disconnected, () => setJoined(false));
      await r.connect(url, token);
      await r.localParticipant.setMicrophoneEnabled(true);
      room.current = r;
      setJoined(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "could not join");
    }
  }, [id]);

  useEffect(() => () => void room.current?.disconnect(), []);

  const ready = state?.state === "ready" || state?.state === "live";
  const finished = state?.state === "completed" || state?.state === "reported";
  const mmss = `${String(Math.floor(elapsed / 60)).padStart(2, "0")}:${String(
    elapsed % 60,
  ).padStart(2, "0")}`;

  return (
    <main>
      <h1>Interview</h1>
      <p className="sub">
        session {id} · {state?.state ?? "connecting"}
      </p>

      {!ready && !finished && <p>{WAITING}</p>}

      {ready && !joined && (
        <>
          <p>
            Your interviewer is ready. It will ask about what your resume and the job
            description have in common — and follow whatever you bring up.
          </p>
          <button onClick={join}>Join and talk</button>
        </>
      )}

      {joined && (
        <div className="stat">
          <span>
            <b>{mmss}</b> elapsed
          </span>
          <span>
            <b>{state?.turns ?? 0}</b> turns
          </span>
          <span>
            <b>{state?.coverage.filter((t) => t.status !== "unprobed").length ?? 0}</b> of{" "}
            {state?.coverage.length ?? 0} topics covered
          </span>
        </div>
      )}

      {finished && (
        <p>
          That&apos;s the end of the interview. <a href={`/report/${id}`}>Read your report →</a>
        </p>
      )}

      {error && <p className="err">{error}</p>}

      {(joined || finished) && (
        <div className="row">
          <div className="transcript">
            {turns.length === 0 && <p className="sub">Listening…</p>}
            {turns.map((t, i) => (
              <div key={i} className={`turn ${t.speaker}`}>
                <div className="who">{t.speaker}</div>
                <div>{t.text}</div>
              </div>
            ))}
          </div>

          <aside className="coverage panel">
            <h2>Coverage</h2>
            {(state?.coverage ?? []).map((t: Topic) => (
              <div key={t.name} className={`topic ${t.status}`}>
                <span className="dot" />
                <span>{t.name}</span>
              </div>
            ))}
          </aside>
        </div>
      )}
    </main>
  );
}
