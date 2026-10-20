// Repro's tracing plugin for Vitest (K07; ADR-0017, phase 3).
//
// Repro copies this file into the snapshot and adds it to the project's plugins through its
// wrapper config (repro.vitest.config.mts). Last of the transforms (enforce: "post"), it sees
// JavaScript, TypeScript already stripped. In the files REPRO_JS_TRACE_PLAN names, it wraps the
// named functions in place, so that calls from inside the module are traced too:
// - a top-level function declaration, exported or not: `name = wrap(name)` appended;
// - a top-level `const`/`let`/`var` holding a function: the declaration made `let`, then the
//   same reassignment;
// - a top-level class's methods and accessors, by V8's names (`load`, `get size`): replaced on
//   the prototype, or on the class for static ones.
// The wrapper comes from the runtime the setup file installs (globalThis.__reproTrace); without
// it the module is left as it was.
const plan = JSON.parse(process.env.REPRO_JS_TRACE_PLAN || "{}");

function fileOf(id) {
  const path = id.split("?")[0].split("\\").join("/");
  return Object.keys(plan).find((file) => path.endsWith(`/${file}`));
}

function isFunction(node) {
  return node && (node.type === "FunctionExpression" || node.type === "ArrowFunctionExpression");
}

export default function reproTrace() {
  return {
    name: "repro-trace",
    enforce: "post",
    transform(code, id) {
      const file = fileOf(id);
      if (!file) return null;
      const wanted = new Set(plan[file]);
      const ast = this.parse(code);
      const edits = []; // [start, end, text], applied from the end
      const lines = [];
      const at = JSON.stringify(file);
      for (const statement of ast.body) {
        const node =
          statement.type === "ExportNamedDeclaration" ||
          statement.type === "ExportDefaultDeclaration"
            ? statement.declaration
            : statement;
        if (!node) continue;
        if (node.type === "FunctionDeclaration" && node.id && wanted.has(node.id.name)) {
          const name = node.id.name;
          lines.push(`${name} = __reproTrace.wrap(${at}, ${JSON.stringify(name)}, ${name});`);
        } else if (node.type === "VariableDeclaration") {
          const traced = node.declarations.filter(
            (d) => d.id.type === "Identifier" && wanted.has(d.id.name) && isFunction(d.init),
          );
          if (!traced.length) continue;
          if (node.kind === "const") edits.push([node.start, node.start + 5, "let  "]);
          for (const d of traced) {
            const name = d.id.name;
            lines.push(`${name} = __reproTrace.wrap(${at}, ${JSON.stringify(name)}, ${name});`);
          }
        } else if (node.type === "ClassDeclaration" && node.id) {
          const cls = node.id.name;
          for (const member of node.body.body) {
            if (member.type !== "MethodDefinition" || member.key.type !== "Identifier") continue;
            const key = member.key.name;
            const name =
              member.kind === "get" || member.kind === "set" ? `${member.kind} ${key}` : key;
            if (member.kind === "constructor" || !wanted.has(name)) continue;
            const holder = member.static ? cls : `${cls}.prototype`;
            const slot = member.kind === "get" || member.kind === "set" ? member.kind : "value";
            lines.push(
              `__reproTrace.method(${holder}, ${JSON.stringify(key)}, ${JSON.stringify(slot)}, ${at}, ${JSON.stringify(name)});`,
            );
          }
        }
      }
      if (!lines.length) return null;
      let out = code;
      for (const [start, end, text] of edits.sort((a, b) => b[0] - a[0])) {
        out = out.slice(0, start) + text + out.slice(end);
      }
      out += `\n;{ const __reproTrace = globalThis.__reproTrace; if (__reproTrace) {\n${lines.join("\n")}\n} }\n`;
      return { code: out, map: null };
    },
  };
}
