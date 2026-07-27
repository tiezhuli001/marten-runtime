import assert from "node:assert/strict";
import test from "node:test";

import { ACTIONS } from "../lib/contract.mjs";
import { executeBridgeRequest } from "../lib/execute.mjs";

const birthArguments = {
  gender: "male",
  birthYear: 1988,
  birthMonth: 2,
  birthDay: 15,
  birthHour: 23,
  birthMinute: 30,
  calendarType: "solar",
};

test("action mapping is fixed", () => {
  assert.deepEqual(ACTIONS, {
    chart: {
      toolName: "bazi",
      resultSchemaVersion: "bazi.chart.v1",
    },
    dayun: {
      toolName: "bazi_dayun",
      resultSchemaVersion: "bazi.dayun.v1",
    },
    resolve_pillars: {
      toolName: "bazi_pillars_resolve",
      resultSchemaVersion: "bazi.resolve_pillars.v1",
    },
  });
});

test("all three actions return their canonical schema identity", async () => {
  const requests = [
    ["chart", birthArguments, "bazi.chart.v1"],
    ["dayun", birthArguments, "bazi.dayun.v1"],
    ["resolve_pillars", {
      yearPillar: "戊辰",
      monthPillar: "甲寅",
      dayPillar: "辛丑",
      hourPillar: "戊子",
    }, "bazi.resolve_pillars.v1"],
  ];

  for (const [action, args, schema] of requests) {
    const response = await executeBridgeRequest({
      protocolVersion: "1",
      requestId: `req_${action}`,
      tool: action,
      arguments: args,
      detailLevel: "default",
    });
    assert.equal(response.ok, true);
    assert.equal(response.action, action);
    assert.equal(response.resultSchemaVersion, schema);
    assert.equal(typeof response.structuredContent, "object");
  }
});
