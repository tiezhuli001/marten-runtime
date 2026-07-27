import assert from "node:assert/strict";
import test from "node:test";

import { executeTool, renderToolResult } from "taibu-core/mcp";

const chartArguments = {
  gender: "female",
  birthYear: 1990,
  birthMonth: 5,
  birthDay: 15,
  birthHour: 15,
  birthMinute: 0,
  calendarType: "solar",
};

test("canonical structuredContent is authoritative", async () => {
  const raw = await executeTool("bazi", chartArguments);
  const rendered = renderToolResult("bazi", raw, { detailLevel: "default" });

  assert.equal(typeof rendered.structuredContent, "object");
  assert.ok(Array.isArray(rendered.content));
  assert.notEqual(rendered.content[0].text, JSON.stringify(rendered.structuredContent));
});

test("detailLevel changes canonical renderer output", async () => {
  const raw = await executeTool("bazi", chartArguments);
  const defaultResult = renderToolResult("bazi", raw, { detailLevel: "default" });
  const fullResult = renderToolResult("bazi", raw, { detailLevel: "full" });

  assert.notDeepEqual(defaultResult.structuredContent, fullResult.structuredContent);
  assert.ok(JSON.stringify(fullResult.structuredContent).length > JSON.stringify(defaultResult.structuredContent).length);
});
