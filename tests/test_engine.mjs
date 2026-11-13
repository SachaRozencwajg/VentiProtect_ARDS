// VentiProtect ARDS v1.1: tests of the calculation engine.
//
// These tests load the engine straight out of web/index.html (the <script id="vp-engine"> block)
// and run that exact code. Nothing is copied or re-typed from the page.
//
//   node --test tests/test_engine.mjs
//
// No dependency: only Node.js 18 or later.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import vm from "node:vm";

const html = readFileSync(new URL("../web/index.html", import.meta.url), "utf8");
const block = html.match(/<script id="vp-engine">([\s\S]*?)<\/script>/);
assert.ok(block, "engine block not found in web/index.html");
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(block[1] + "\n;globalThis.VentiProtect = VentiProtect;", sandbox);
const VP = sandbox.VentiProtect;

const EMPTY = { heightCm: null, sex: null, weightKg: null, fio2: null, pao2: null, spo2: null, rr: null, vt: null, ppeak: null, pplat: null, peep: null };
const run = (values) => VP.compute({ ...EMPTY, ...values });
const near = (actual, expected, tol = 0.01) =>
  assert.ok(Math.abs(actual - expected) <= tol, `expected ${expected}, got ${actual}`);
// Array.from: the engine runs in its own context, so its arrays are copied before being compared.
const types = (res) => Array.from(res.suggestions, (s) => (s.type === "flag" ? `flag:${s.metric}` : s.type));

// ---------------------------------------------------------------------------
// 1. Worked examples. Expected values are computed by hand, the arithmetic is shown.
// ---------------------------------------------------------------------------

test("article Figure 1 case, with a peak pressure of 38 cmH2O", () => {
  const res = run({ heightCm: 177, sex: "female", vt: 400, rr: 22, ppeak: 38, pplat: 31, peep: 8, fio2: 90, pao2: 83 });
  const m = res.metrics;
  assert.deepEqual({ ...res.errors }, {});
  near(m.pbw.value, 67.886);    // 45.5 + 0.91 x (177 - 152.4) = 45.5 + 22.386
  near(m.vtPbw.value, 5.892);   // 400 / 67.886
  assert.equal(m.vtPbw.state, "safe");
  assert.equal(m.pplat.state, "danger");   // 31 > 30
  assert.equal(m.dp.value, 23);            // 31 - 8
  assert.equal(m.dp.state, "danger");
  near(m.crs.value, 17.391);    // 400 / 23
  assert.equal(m.crs.state, "critical");
  near(m.mp.value, 22.854);     // 0.098 x 22 x 0.4 x (38 - 23/2) = 0.8624 x 26.5
  assert.equal(m.mp.state, "warning");
  near(res.oxy.value, 92.22);   // 83 / 0.90
  assert.equal(res.oxy.cls, "severe");
  assert.equal(res.banner.show, true);
  assert.equal(res.banner.usedSF, false);

  assert.deepEqual(types(res), ["dp", "mp", "flag:pplat"]);
  const [dp, mp] = res.suggestions;
  // Vt for a driving pressure of 14 would be 400 x 14/23 = 243 mL, below the 4 mL/kg floor (271.5 mL).
  assert.equal(dp.mode, "floor");
  assert.equal(dp.vtFloor, 272);
  assert.equal(mp.rr, 16);      // 17 / (0.098 x 0.4 x 26.5) = 16.37
  assert.equal(mp.vt, 297);     // 17 / (0.098 x 22 x 26.5) = 0.29755 L
  assert.equal(mp.vtBelowFloor, false);
  assert.equal(res.allSafe, false);
});

test("a fully protective setting", () => {
  const res = run({ heightCm: 175, sex: "male", vt: 420, rr: 18, ppeak: 26, pplat: 22, peep: 10, fio2: 40, pao2: 90 });
  const m = res.metrics;
  near(m.pbw.value, 70.566);    // 50 + 0.91 x 22.6
  near(m.vtPbw.value, 5.952);
  assert.equal(m.dp.value, 12);
  near(m.crs.value, 35);        // 420 / 12
  assert.equal(m.crs.state, "severe");
  near(m.mp.value, 14.818);     // 0.098 x 18 x 0.42 x (26 - 6)
  near(res.oxy.value, 225);
  assert.equal(res.oxy.cls, "mild");
  assert.equal(res.suggestions.length, 0);
  assert.equal(res.complete, true);
  assert.equal(res.allSafe, true);
  assert.equal(res.banner.show, false);
});

test("driving pressure correction when the target Vt stays above the floor", () => {
  // DP 18, Vt 450: 450 x 14/18 = 350 mL = 4.96 mL/kg for a PBW of 70.566 kg (floor 282.3 mL).
  const res = run({ heightCm: 175, sex: "male", vt: 450, rr: 20, ppeak: 32, pplat: 28, peep: 10 });
  const dp = res.suggestions.find((s) => s.type === "dp");
  assert.equal(dp.mode, "reduce");
  assert.equal(dp.vt, 350);
  near(dp.vtPerKg, 4.96);
});

test("tidal volume above 6 mL/kg", () => {
  // PBW 70.566 kg: 6 mL/kg = 423.4 -> 423 mL (rounded down), 4 mL/kg = 282.3 -> 283 mL (rounded up).
  const res = run({ heightCm: 175, sex: "male", vt: 550 });
  const vt = res.suggestions.find((s) => s.type === "vt");
  assert.equal(vt.target, 423);
  assert.equal(vt.delta, 127);
  assert.equal(vt.min, 283);
  assert.equal(res.metrics.vtPbw.state, "warning"); // 7.79 mL/kg
});

// ---------------------------------------------------------------------------
// 2. Alert boundaries
// ---------------------------------------------------------------------------

test("alert boundaries", () => {
  const c = VP.classify;
  const expect = (fn, pairs) => pairs.forEach(([x, state]) => assert.equal(fn(x), state, `${fn.name}(${x})`));
  expect(c.vtPbw, [[6, "safe"], [6.01, "warning"], [8, "warning"], [8.01, "danger"]]);
  expect(c.pplat, [[27.9, "safe"], [28, "warning"], [30, "warning"], [30.1, "danger"]]);
  expect(c.dp, [[12.9, "safe"], [13, "warning"], [15, "warning"], [15.1, "danger"]]);
  expect(c.mp, [[16.99, "safe"], [17, "warning"], [27, "warning"], [27.01, "danger"]]);
  expect(c.crs, [[40.1, "reduced"], [40, "severe"], [25, "severe"], [24.9, "critical"]]);
  // Berlin: upper bounds are inclusive (P/F 200 is moderate, P/F 100 is severe).
  expect(c.pf, [[100, "severe"], [100.1, "moderate"], [200, "moderate"], [200.1, "mild"], [300, "mild"], [300.1, "none"]]);
  // Rice 2007: S/F = 64 + 0.84 x P/F -> 148, 235 (232 rounded by the authors), 315.
  expect(c.sf, [[148, "severe"], [148.1, "moderate"], [235, "moderate"], [235.1, "mild"], [315, "mild"], [315.1, "none"]]);
});

test("mechanical power is the published simplified equation, not the v1.0 one", () => {
  // Pplat 34, PEEP 22, RR 20, Vt 420, Ppeak 34 (no resistive pressure):
  // 0.098 x 20 x 0.42 x (34 - 6) = 23.05 J/min. v1.0 gave 0.098 x 20 x 0.42 x (34 - 11) = 18.93.
  near(VP.mechanicalPower(20, 420, 34, 34, 22), 23.05);
});

// ---------------------------------------------------------------------------
// 3. Input checks: the situations that misled v1.0
// ---------------------------------------------------------------------------

test("a height typed in inches is an error, not a negative body weight", () => {
  const res = run({ heightCm: 70, sex: "male", vt: 500 });
  assert.equal(res.errors.heightCm, "range");
  assert.equal(res.metrics.pbw, undefined);
  assert.equal(res.metrics.vtPbw, undefined);
  assert.equal(res.allSafe, false);
});

test("every out-of-range or non-numeric value is rejected", () => {
  for (const [key, [lo, hi]] of Object.entries(VP.LIMITS)) {
    assert.equal(run({ [key]: lo - 1 }).errors[key], "range", `${key} below range`);
    assert.equal(run({ [key]: hi + 1 }).errors[key], "range", `${key} above range`);
    assert.equal(run({ [key]: NaN }).errors[key], "range", `${key} not a number`);
    assert.equal(run({ [key]: lo }).errors[key], undefined, `${key} lower bound accepted`);
    assert.equal(run({ [key]: hi }).errors[key], undefined, `${key} upper bound accepted`);
  }
});

test("no oxygenation result without an explicit FiO2", () => {
  assert.equal(run({ pao2: 80 }).oxy, null);
  assert.equal(run({ spo2: 92 }).oxy, null);
});

test("PEEP above plateau pressure is an error on both fields", () => {
  const res = run({ heightCm: 175, sex: "male", vt: 420, rr: 20, ppeak: 30, pplat: 12, peep: 18 });
  assert.equal(res.errors.pplat, "pplat_le_peep");
  assert.equal(res.errors.peep, "pplat_le_peep");
  assert.equal(res.metrics.dp, undefined);
  assert.equal(res.metrics.pplat, undefined);
  assert.equal(res.metrics.mp, undefined);
  assert.equal(res.allSafe, false);
});

test("peak pressure below plateau pressure is an error", () => {
  const res = run({ rr: 20, vt: 420, ppeak: 20, pplat: 25, peep: 10 });
  assert.equal(res.errors.ppeak, "ppeak_lt_pplat");
  assert.equal(res.metrics.mp, undefined);
  assert.equal(res.metrics.dp.value, 15);
});

test("a danger card never comes with the 'all protective' message", () => {
  const res = run({ pplat: 20, peep: 3, pao2: 90, fio2: 60 });
  assert.equal(res.metrics.dp.state, "danger");   // 17 cmH2O
  assert.deepEqual(types(res), ["flag:dp"]);
  assert.equal(res.suggestions[0].reason, "need_vt_pbw");
  assert.equal(res.allSafe, false);
  assert.equal(res.complete, false);
  // PEEP 3: P/F 150 is not given a Berlin class, and the severe banner stays off.
  assert.equal(res.oxy.cls, "peep_lt5");
  assert.equal(res.banner.show, false);
});

test("a driving pressure in the warning zone is flagged", () => {
  const res = run({ heightCm: 175, sex: "male", vt: 420, rr: 18, ppeak: 28, pplat: 24, peep: 10 });
  assert.equal(res.metrics.dp.state, "warning");  // 14
  assert.deepEqual(types(res), ["flag:dp"]);
  assert.equal(res.allSafe, false);
});

test("plateau pressure above 30 is flagged even when driving pressure is fine", () => {
  const res = run({ heightCm: 175, sex: "male", vt: 420, rr: 14, ppeak: 34, pplat: 34, peep: 22 });
  assert.equal(res.metrics.dp.state, "safe");
  assert.equal(res.metrics.pplat.state, "danger");
  assert.ok(types(res).includes("flag:pplat"));
  assert.equal(res.allSafe, false);
});

test("S/F ratio: thresholds, SpO2 ceiling and banner", () => {
  // SpO2 92% on FiO2 30%: S/F 306.7 -> mild (v1.0 showed no ARDS class above 296).
  assert.equal(run({ spo2: 92, fio2: 30 }).oxy.cls, "mild");
  // SpO2 above 97%: not interpreted.
  const flat = run({ spo2: 100, fio2: 40 });
  assert.equal(flat.oxy.cls, "uninterpretable");
  assert.equal(flat.banner.show, false);
  // SpO2 88% on FiO2 60%: S/F 146.7 -> severe, banner with the "confirm with a blood gas" warning.
  const severe = run({ spo2: 88, fio2: 60 });
  assert.equal(severe.oxy.cls, "severe");
  assert.deepEqual({ ...severe.banner }, { show: true, usedSF: true });
});

test("PaO2 takes priority over SpO2, and an invalid PaO2 does not fall back to SpO2", () => {
  assert.equal(run({ pao2: 70, spo2: 92, fio2: 50 }).oxy.path, "pf");
  const bad = run({ pao2: 9.5, spo2: 92, fio2: 50 });   // 9.5 looks like kPa
  assert.equal(bad.errors.pao2, "range");
  assert.equal(bad.oxy, null);
});

test("nothing entered", () => {
  const res = run({});
  assert.equal(res.anyInput, false);
  assert.equal(res.allSafe, false);
  assert.equal(res.suggestions.length, 0);
});

// ---------------------------------------------------------------------------
// 4. Sweep: 2,000 seeded scenarios against a reference written separately from the engine
// ---------------------------------------------------------------------------

function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

test("2,000 random scenarios: values match the reference and suggestions reach their target", () => {
  const rnd = mulberry32(42);
  const int = (lo, hi) => lo + Math.floor(rnd() * (hi - lo + 1));
  for (let i = 0; i < 2000; i++) {
    const heightCm = int(150, 195);
    const sex = rnd() < 0.5 ? "male" : "female";
    const refPbw = sex === "male" ? 50 + 0.91 * (heightCm - 152.4) : 45.5 + 0.91 * (heightCm - 152.4);
    const vt = Math.round(refPbw * (4 + rnd() * 6));
    const rr = int(10, 34);
    const peep = int(5, 14);
    const pplat = peep + int(6, 24);
    const ppeak = pplat + int(0, 10);
    const fio2 = int(21, 100);
    const useAbg = rnd() < 0.5;
    const pao2 = useAbg ? int(45, 200) : null;
    const spo2 = useAbg ? null : int(80, 100);
    const input = { heightCm, sex, vt, rr, peep, pplat, ppeak, fio2, pao2, spo2 };
    const res = run(input);
    const m = res.metrics;
    const label = `scenario ${i} ${JSON.stringify(input)}`;

    // Reference values, from the definitions.
    const refDp = pplat - peep;
    const refMp = (0.098 * rr * vt * (ppeak - 0.5 * (pplat - peep))) / 1000;
    assert.deepEqual({ ...res.errors }, {}, label);
    near(m.pbw.value, refPbw, 1e-9);
    near(m.vtPbw.value, vt / refPbw, 1e-9);
    near(m.dp.value, refDp, 1e-9);
    near(m.crs.value, vt / refDp, 1e-9);
    near(m.mp.value, refMp, 1e-9);
    near(res.oxy.value, useAbg ? (pao2 * 100) / fio2 : (spo2 * 100) / fio2, 1e-9);
    assert.equal(res.complete, true, label);

    // The plan and the cards never contradict each other.
    const flagged = ["vtPbw", "pplat", "dp", "mp"].filter((k) => m[k].state !== "safe");
    assert.equal(res.allSafe, flagged.length === 0, label);
    assert.equal(res.suggestions.length > 0, flagged.length > 0, label);
    assert.equal(res.banner.show, res.oxy.cls === "severe", label);
    if (!useAbg && spo2 > 97) assert.equal(res.oxy.cls, "uninterpretable", label);

    // Following a suggestion reaches its target.
    for (const s of res.suggestions) {
      if (s.type === "mp") {
        assert.ok(run({ ...input, rr: Math.max(s.rr, 4) }).metrics.mp.value < 17 || s.rr < 4, label);
        assert.ok(VP.mechanicalPower(rr, s.vt, ppeak, pplat, peep) < 17, label);
        assert.equal(s.vtBelowFloor, s.vt < 4 * refPbw, label);
      }
      if (s.type === "vt") {
        assert.ok(s.target / refPbw <= 6, label);
        assert.ok(s.min / refPbw >= 4, label);
      }
      if (s.type === "dp" && s.mode === "reduce") {
        assert.ok(s.vt / refPbw >= 4 - 1e-9, label);
        assert.ok((s.vt * refDp) / vt <= 14 + 0.06, label);   // new driving pressure at unchanged compliance
      }
      if (s.type === "dp" && s.mode === "floor") {
        assert.ok(s.vtFloor / refPbw >= 4, label);
      }
    }
  }
});

// ---------------------------------------------------------------------------
// 5. The published version is not to be edited
// ---------------------------------------------------------------------------

test("app/index.html is still the published v1.0, byte for byte", () => {
  const v10 = readFileSync(new URL("../app/index.html", import.meta.url));
  assert.equal(
    createHash("sha256").update(v10).digest("hex"),
    "cd6596674d87087e726bb96c5a3484af0e79dfa683fe180841c393f8ac52cd3b"
  );
});

test("the page declares no external resource", () => {
  assert.ok(html.includes("default-src 'none'"), "content security policy missing");
  assert.equal(/<(script|link|img|iframe)[^>]+(src|href)="https?:\/\/[^"]+"[^>]*>/i.test(html.replace(/<link rel="canonical"[^>]*>/, "")), false);
  assert.equal(/@import|fonts\.googleapis/.test(html), false);
});
