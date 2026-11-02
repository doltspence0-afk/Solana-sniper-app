const K = require("../docs/calc.js"); let d = "";
process.stdin.on("data", (c) => (d += c)).on("end", () => { const { fn, args } = JSON.parse(d); console.log(JSON.stringify(typeof K[fn] === "function" ? K[fn](...args) : K[fn])); });
