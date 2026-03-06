const REQUIRED_EVENTS = new Set([
    "session.started",
    "chat.turn",
    "session.ended",
    "sub_agent.roles",
    "sub_agent.status",
    "sub_agent.queued",
    "sub_agent.error",
]);

function isObjectRecord(value: unknown): value is Record<string, unknown> {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export interface StoryCraftrEvent {
    event: string;
    payload: Record<string, any>;
}

export function parseEventLine(line: string): StoryCraftrEvent | undefined {
    const trimmed = line.trim();
    if (!trimmed) {
        return undefined;
    }

    let parsed: unknown;
    try {
        parsed = JSON.parse(trimmed);
    } catch {
        return undefined;
    }

    if (!isObjectRecord(parsed)) {
        return undefined;
    }

    const eventValue = parsed.event;
    if (typeof eventValue !== "string" || !eventValue.trim()) {
        return undefined;
    }

    const payloadValue = parsed.payload;
    const payload = isObjectRecord(payloadValue) ? payloadValue : {};

    if (REQUIRED_EVENTS.has(eventValue) && !isObjectRecord(payloadValue)) {
        return undefined;
    }

    return {
        event: eventValue,
        payload,
    };
}
