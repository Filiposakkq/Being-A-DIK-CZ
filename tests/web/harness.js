// Minimal test harness for the browser-run website tests. Results are written to #result
// (data-pass / data-fail) so a headless browser can read them: see tools/translation-manager/tests/test_web.py.
(function () {
  const results = [];
  window.test = async function (name, fn) {
    try { await fn(); results.push([name, true, ""]); }
    catch (e) { results.push([name, false, String(e && e.message || e)]); }
  };
  window.eq = function (a, b, msg) {
    if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error((msg ? msg + ": " : "") + "expected " + JSON.stringify(b) + " got " + JSON.stringify(a));
  };
  window.ok = function (v, msg) { if (!v) throw new Error(msg || "assertion failed"); };
  window.finish = function () {
    const pass = results.filter((r) => r[1]).length, fail = results.length - pass;
    const out = document.createElement("div");
    out.id = "result";
    out.dataset.pass = String(pass);
    out.dataset.fail = String(fail);
    out.textContent = `${pass} passed, ${fail} failed`;
    const ul = document.createElement("ul");
    for (const [n, p, m] of results) {
      const li = document.createElement("li");
      li.textContent = `${p ? "PASS" : "FAIL"}  ${n}${m ? "  — " + m : ""}`;
      li.style.color = p ? "green" : "crimson";
      ul.append(li);
    }
    document.body.append(out, ul);
    document.title = `${pass} passed, ${fail} failed`;
  };
  window.loadJson = (name) => fetch("fixtures/" + name, { cache: "no-store" }).then((r) => r.json());
})();
