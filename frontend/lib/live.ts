import { API, type AuthOpts } from "./api";

type Handlers = {
  /** Something this person can see changed: reload the room. */
  onChange: () => void;
  /** The room no longer exists. */
  onGone?: () => void;
  /** Whether a live stream is currently connected (poll faster when it isn't). */
  onStatus?: (connected: boolean) => void;
};

/**
 * Live room updates over server-sent events.
 *
 * EventSource can't send the Authorization / X-Invite-Token headers, so this
 * reads the stream with fetch. It reconnects with backoff when the stream
 * ends or fails; callers keep polling as a fallback while it's down.
 * Returns a function that stops it.
 */
export function subscribeRoom(id: string, auth: AuthOpts, handlers: Handlers): () => void {
  let stopped = false;
  let controller: AbortController | null = null;
  let failures = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const headers: Record<string, string> = { Accept: "text/event-stream" };
  if (auth.accessToken) headers.Authorization = `Bearer ${auth.accessToken}`;
  if (auth.inviteToken) headers["X-Invite-Token"] = auth.inviteToken;
  if (auth.roomAccess) headers["X-Room-Access"] = auth.roomAccess;

  function dispatch(block: string) {
    let event = "message";
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
    }
    if (event === "change") handlers.onChange();
    if (event === "gone") {
      stopped = true;
      handlers.onGone?.();
    }
  }

  async function connect() {
    if (stopped) return;
    controller = new AbortController();
    try {
      const res = await fetch(`${API}/api/sessions/${id}/events`, { headers, signal: controller.signal, cache: "no-store" });
      if (res.status === 404) {
        stopped = true;
        handlers.onGone?.();
        return;
      }
      // No access yet, or a PIN is needed: retrying won't help, and the page handles it.
      if (res.status === 403 || res.status === 423) {
        stopped = true;
        return;
      }
      if (!res.ok || !res.body) throw new Error(`stream ${res.status}`);
      failures = 0;
      handlers.onStatus?.(true);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
        let split = buffer.indexOf("\n\n");
        while (split !== -1) {
          dispatch(buffer.slice(0, split));
          buffer = buffer.slice(split + 2);
          split = buffer.indexOf("\n\n");
        }
      }
    } catch {
      failures += 1;
    } finally {
      handlers.onStatus?.(false);
    }
    if (stopped) return;
    // A clean end (the server closes streams after a few minutes) reconnects
    // at once; errors back off up to 30s.
    const delay = failures ? Math.min(30000, 1000 * 2 ** Math.min(failures, 5)) : 250;
    timer = setTimeout(() => void connect(), delay);
  }

  void connect();
  return () => {
    stopped = true;
    if (timer) clearTimeout(timer);
    controller?.abort();
  };
}
