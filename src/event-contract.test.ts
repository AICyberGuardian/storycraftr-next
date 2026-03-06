import test from "node:test";
import assert from "node:assert/strict";

import { parseEventLine } from "./event-contract";

const FIXTURE_LINES: string[] = [
    JSON.stringify({ event: "session.started", payload: { book_path: "/tmp/book" } }),
    JSON.stringify({ event: "chat.turn", payload: { user: "u", answer: "a" } }),
    JSON.stringify({ event: "session.ended", payload: { book_path: "/tmp/book" } }),
    JSON.stringify({ event: "sub_agent.roles", payload: { roles: [] } }),
    JSON.stringify({ event: "sub_agent.status", payload: { jobs: [] } }),
    JSON.stringify({ event: "sub_agent.queued", payload: { job_id: "1" } }),
    JSON.stringify({ event: "sub_agent.error", payload: { error: "boom" } }),
];

test("parseEventLine accepts representative StoryCraftr fixture events", () => {
    for (const line of FIXTURE_LINES) {
        const parsed = parseEventLine(line);
        assert.ok(parsed, `expected parser output for line: ${line}`);
        assert.equal(typeof parsed.event, "string");
        assert.equal(typeof parsed.payload, "object");
    }
});

test("parseEventLine rejects required events with non-object payload", () => {
    const invalidLine = JSON.stringify({ event: "chat.turn", payload: "oops" });
    const parsed = parseEventLine(invalidLine);
    assert.equal(parsed, undefined);
});

test("parseEventLine tolerates unknown events with missing payload", () => {
    const unknownLine = JSON.stringify({ event: "custom.event" });
    const parsed = parseEventLine(unknownLine);
    assert.ok(parsed);
    assert.equal(parsed.event, "custom.event");
    assert.deepEqual(parsed.payload, {});
});
