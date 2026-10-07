// E13-K01 SPIKE — dumps TS-kernel outputs over the recorded window (and a 100k synthetic set) to JSON
// for services/api/candleviewer/orderflow/_spike_e13/parity.py. JSON round-trips float64 exactly.
import { writeFileSync } from "node:fs";
import { KERNELS, densify, outputs } from "./kernels.mjs";
import { recordedBars, syntheticBars } from "./data.mjs";

const out = process.argv[2] ?? "spike-e13-parity.json";
const sets = { recorded: densify(recordedBars()), synthetic100k: densify(syntheticBars(100_000)) };
const res = {};
for (const [setName, bars] of Object.entries(sets)) {
  res[setName] = { bars, series: {} };
  for (const [name, K] of Object.entries(KERNELS)) {
    const k = new K(bars.length); for (const b of bars) k.push(b);
    for (const [s, arr] of Object.entries(outputs(k))) res[setName].series[`${name}.${s}`] = Array.from(arr, (x) => (Number.isNaN(x) ? null : x));
  }
}
writeFileSync(out, JSON.stringify(res));
console.log(`wrote ${out}: recorded=${sets.recorded.length} bars (${sets.recorded.filter((b) => b.synthetic).length} synthetic)`);
