import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
const core = path.resolve(process.argv[2]);
const version = JSON.parse(
    fs.readFileSync(path.join(core, "package.json"), "utf8"),
).version;
if (version !== "0.66.0") throw new Error("Use @google/gemini-cli-core@0.66.0");
const { ChatRecordingService, loadConversationRecord } = await import(
    pathToFileURL(path.join(core, "dist/src/services/chatRecordingService.js"))
        .href
);

// The real recorder, offline: no Config initialization, auth, model or tools run.
const work = path.resolve(process.argv[3]);
fs.mkdirSync(work, { recursive: true });
const recorder = new ChatRecordingService({
    promptId: "fixture-session-0001",
    config: {
        getProjectRoot: () => "/fixture-project",
        storage: { getProjectTempDir: () => work },
    },
    toolRegistry: { getTool: () => undefined },
});
await recorder.initialize(undefined, "main");
const user = [
    { text: "Keep spacing exactly:  café  \n" },
    { text: "\tsecond line\r\n" },
];
const intro = [{ text: "I will inspect two fixture files.\n" }];
const record = (id, type, content) =>
    recorder.recordMessage({
        id,
        type,
        content,
        model: type === "gemini" ? "fixture-model" : undefined,
    });
record("user-1", "user", user);
record("assistant-1", "gemini", intro);
const call = (id, file) => ({
    id,
    name: "read_file",
    args: { file_path: file },
    status: "executing",
    timestamp: "2026-11-02T00:00:00.000Z",
});
const calls = [call("call-1", "hello.txt"), call("call-2", "other.txt")];
recorder.recordToolCalls("fixture-model", calls);
recorder.recordToolCalls(
    "fixture-model",
    calls.map((c) => ({
        ...c,
        status: "success",
        result: [
            {
                functionResponse: {
                    id: c.id,
                    name: c.name,
                    response: {
                        output: c.id === "call-1" ? "hello\n" : "world\n",
                    },
                },
            },
        ],
    })),
);
record("discarded-user", "user", "This branch is discarded.");
record("discarded-assistant", "gemini", "This answer is discarded.");
recorder.rewindTo("discarded-user");
record("user-2", "user", "Keep the final summary short.\n");
record("assistant-2", "gemini", "The fixture greeting is hello.\n");
// Exercise real patch records used by Gemini when history is synchronized.
const history = [
    { id: "user-1", content: { role: "user", parts: user } },
    { id: "assistant-1", content: { role: "model", parts: intro } },
    {
        id: "tool-results",
        content: {
            role: "user",
            parts: calls.map((c) => ({
                functionResponse: {
                    id: c.id,
                    name: c.name,
                    response: {
                        output: c.id === "call-1" ? "hello\n" : "world\n",
                    },
                },
            })),
        },
    },
    {
        id: "user-2",
        content: {
            role: "user",
            parts: [{ text: "Keep the final summary short.\n" }],
        },
    },
    {
        id: "assistant-2",
        content: {
            role: "model",
            parts: [{ text: "The fixture greeting is hello.\n" }],
        },
    },
];
recorder.updateMessagesFromHistory(history);
const file = recorder.getConversationFilePath();
const loaded = await loadConversationRecord(file);
fs.copyFileSync(file, path.join(work, "gemini_cli_0_66_0.jsonl"));
fs.writeFileSync(
    path.join(work, "loaded.json"),
    JSON.stringify(loaded, null, 2) + "\n",
);
console.log(
    JSON.stringify({
        file,
        loaded: loaded.messages.map((m) => ({ id: m.id, type: m.type })),
        version,
    }),
);
