const TRANSPORT_MESSAGE = "MYSMIS_BRIDGE_COMMAND";
const DEFAULT_REPLAY_KEY = "mysmisBridgeReplayClaimsV1";

export class InternalTransportError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "InternalTransportError";
    this.code = code;
  }
}

export class ChromeSessionReplayStore {
  #storage;
  #key;
  #queue = Promise.resolve();

  constructor({ storageSession, key = DEFAULT_REPLAY_KEY }) {
    if (!storageSession
      || typeof storageSession.get !== "function"
      || typeof storageSession.set !== "function") {
      throw new InternalTransportError("MV3_SESSION_STORAGE_REQUIRED", "chrome.storage.session is required for restart-safe replay claims.");
    }
    this.#storage = storageSession;
    this.#key = key;
  }

  claim(id, expiresAt, now) {
    const operation = this.#queue.then(async () => {
      const current = await this.#storage.get(this.#key);
      const raw = current?.[this.#key];
      const claims = raw && typeof raw === "object" && !Array.isArray(raw) ? raw : {};
      const active = Object.fromEntries(Object.entries(claims).filter(([, expiry]) => (
        Number.isFinite(expiry) && expiry >= now
      )));
      if (Object.hasOwn(active, id)) {
        if (Object.keys(active).length !== Object.keys(claims).length) {
          await this.#storage.set({ [this.#key]: active });
        }
        return false;
      }
      active[id] = expiresAt;
      await this.#storage.set({ [this.#key]: active });
      return true;
    });
    this.#queue = operation.catch(() => undefined);
    return operation;
  }
}

export function assertInternalSender(sender, runtimeId) {
  if (!runtimeId || typeof runtimeId !== "string") {
    throw new InternalTransportError("MV3_RUNTIME_ID_INVALID", "The extension runtime ID is unavailable.");
  }
  if (sender?.id !== runtimeId) {
    throw new InternalTransportError("MV3_EXTERNAL_SENDER_DENIED", "Only messages originating from this extension are accepted.");
  }
  return true;
}

function failClosed(error) {
  return {
    ok: false,
    error: {
      code: typeof error?.code === "string" ? error.code : "MV3_DISPATCH_FAILED_CLOSED",
      message: typeof error?.message === "string" ? error.message.slice(0, 300) : "Bridge dispatch failed closed."
    }
  };
}

export function createInternalCommandHandler({ runtimeId, dispatch }) {
  if (typeof dispatch !== "function") {
    throw new InternalTransportError("MV3_DISPATCHER_REQUIRED", "A fixed bridge dispatcher is required.");
  }
  return async function handle(message, sender) {
    try {
      if (message?.type !== TRANSPORT_MESSAGE || !message.command || typeof message.command !== "object") {
        throw new InternalTransportError("MV3_MESSAGE_TYPE_DENIED", "Only a structured MYSMIS_BRIDGE_COMMAND message is accepted.");
      }
      assertInternalSender(sender, runtimeId);
      const response = await dispatch(message.command);
      return { ok: true, response };
    } catch (error) {
      return failClosed(error);
    }
  };
}

export function installInternalCommandTransport({ chromeApi, dispatch }) {
  const runtimeId = chromeApi?.runtime?.id;
  const onMessage = chromeApi?.runtime?.onMessage;
  if (!onMessage || typeof onMessage.addListener !== "function") {
    throw new InternalTransportError("MV3_RUNTIME_UNAVAILABLE", "chrome.runtime.onMessage is unavailable.");
  }
  const handle = createInternalCommandHandler({ runtimeId, dispatch });
  const listener = (message, sender, sendResponse) => {
    if (message?.type !== TRANSPORT_MESSAGE) return false;
    handle(message, sender).then(sendResponse, (error) => sendResponse(failClosed(error)));
    return true;
  };
  onMessage.addListener(listener);
  return () => onMessage.removeListener?.(listener);
}

export const INTERNAL_TRANSPORT_MESSAGE = TRANSPORT_MESSAGE;
