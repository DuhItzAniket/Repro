"use strict";
/*
 * Repro's TypeScript worker (K11; ADR-0017, phase 4), run with the host's Node:
 *
 *     node _ts_worker.cjs <request.json>
 *
 * It loads the TypeScript compiler Repro pins (the request's "typescript": a package directory
 * Repro fetched and checked, ``repro.analysis.typescript``), never a target's own. The compiler
 * parses and type-checks; no code of the target runs. What it reads is fenced: the trees the
 * request names and TypeScript's own lib directory, nothing else (no node_modules above a tree,
 * no @types).
 *
 * Request: {"typescript": dir,
 *           "api": [{"root": dir, "entries": [{"subpath": ".", "paths": [relative, ...]}]}],
 *           "tests": [{"file": relative, "text": source, "spans": {test: [first, last]}}]}
 * Response (stdout): {"version": ..., "api": [one per tree], "tests": [one per file]}.
 *
 * - "api": each entry point resolved to a file (a source tsconfig.json maps it to, else a
 *   declaration file, else the file itself), and each exported declaration's shape.
 * - "tests": each test's assertions (an expect(...) chain or an assert call) whose first line
 *   is in its span, with the chain's names and its last call's arguments.
 */
const fs = require("node:fs");
const path = require("node:path");

const DECLARATION = /\.d\.([cm]?ts|[^./]+\.ts)$/;
const SOURCE = /\.([cm]?[jt]s|[jt]sx)$/;
const CONFIGS = ["tsconfig.json", "tsconfig.build.json"];
const EXPECT_ROOTS = new Set(["expect", "expect.soft", "expect.poll"]);

function main() {
  const request = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
  const ts = require(path.join(request.typescript, "lib", "typescript.js"));
  const response = { version: ts.version, api: [], tests: [] };
  for (const tree of request.api ?? []) response.api.push(readApi(ts, tree));
  for (const file of request.tests ?? []) response.tests.push(readAssertions(ts, file));
  process.stdout.write(JSON.stringify(response));
}

// -- the fence -----------------------------------------------------------------------------------

function fence(ts, roots) {
  const sensitive = ts.sys.useCaseSensitiveFileNames;
  const key = (p) => {
    const found = `${path.resolve(p).replace(/\\/g, "/").replace(/\/+$/, "")}/`;
    return sensitive ? found : found.toLowerCase();
  };
  const allowed = roots.map(key);
  return (p) => {
    const found = key(p);
    return allowed.some((root) => found.startsWith(root));
  };
}

function fencedSystem(ts, inside, root) {
  const sys = ts.sys;
  return {
    useCaseSensitiveFileNames: sys.useCaseSensitiveFileNames,
    fileExists: (p) => inside(p) && sys.fileExists(p),
    readFile: (p, encoding) => (inside(p) ? sys.readFile(p, encoding) : undefined),
    directoryExists: (p) => inside(p) && sys.directoryExists(p),
    getDirectories: (p) => (inside(p) ? sys.getDirectories(p) : []),
    readDirectory: (p, extensions, excludes, includes, depth) =>
      inside(p) ? sys.readDirectory(p, extensions, excludes, includes, depth).filter(inside) : [],
    realpath: (p) => p,
    getCurrentDirectory: () => root,
    onUnRecoverableConfigFileDiagnostic: () => {},
  };
}

function compilerHost(ts, options, sys) {
  const host = ts.createCompilerHost(options, true);
  host.fileExists = sys.fileExists;
  host.readFile = sys.readFile;
  host.directoryExists = sys.directoryExists;
  host.getDirectories = sys.getDirectories;
  host.realpath = sys.realpath;
  host.getCurrentDirectory = sys.getCurrentDirectory;
  host.writeFile = () => {};
  host.getSourceFile = (fileName, languageVersion) => {
    const text = sys.readFile(fileName);
    return text === undefined
      ? undefined
      : ts.createSourceFile(fileName, text, languageVersion, true);
  };
  return host;
}

function relative(root, file) {
  const found = path.relative(root, file).replace(/\\/g, "/");
  return found && !found.startsWith("../") && !path.isAbsolute(found) ? found : null;
}

// -- entry points --------------------------------------------------------------------------------

/** Each output file the project's tsconfig.json says a source compiles to: output -> source. */
function outputs(ts, root, sys) {
  const found = new Map();
  const read = [];
  for (const name of CONFIGS) {
    const file = path.join(root, name);
    if (!sys.fileExists(file)) continue;
    let parsed;
    try {
      // As if declarations were emitted: a types entry (dist/index.d.ts) maps to its source too.
      parsed = ts.getParsedCommandLineOfConfigFile(file, { declaration: true }, sys);
    } catch {
      parsed = undefined;
    }
    if (!parsed || parsed.options.outFile) continue;
    read.push(name);
    for (const input of parsed.fileNames) {
      if (DECLARATION.test(input)) continue;
      let names = [];
      try {
        names = ts.getOutputFileNames(parsed, input, !sys.useCaseSensitiveFileNames);
      } catch {
        continue;
      }
      const source = relative(root, input);
      for (const output of names) {
        const built = relative(root, output);
        if (source && built && !found.has(built)) found.set(built, source);
      }
    }
  }
  return { map: found, configs: read };
}

function resolveEntries(root, entries, map, sys) {
  const exists = (file) => sys.fileExists(path.join(root, file));
  const resolved = [];
  const unresolved = [];
  for (const entry of entries) {
    let hit = null;
    for (const candidate of entry.paths) {
      const source = map.get(candidate);
      if (source !== undefined && exists(source)) {
        hit = { file: source, from: candidate };
        break;
      }
    }
    for (const test of [DECLARATION, SOURCE]) {
      for (const candidate of hit ? [] : entry.paths) {
        if (test.test(candidate) && exists(candidate)) {
          hit = { file: candidate, from: candidate };
          break;
        }
      }
    }
    if (hit) resolved.push({ subpath: entry.subpath, ...hit });
    else unresolved.push({ subpath: entry.subpath });
  }
  return { resolved, unresolved };
}

// -- exported declarations -----------------------------------------------------------------------

function options(ts) {
  return {
    allowJs: true,
    checkJs: false,
    noEmit: true,
    strict: true,
    skipLibCheck: true,
    types: [],
    target: ts.ScriptTarget.ESNext,
    module: ts.ModuleKind.Preserve,
    moduleResolution: ts.ModuleResolutionKind.Bundler,
    jsx: ts.JsxEmit.Preserve,
    resolveJsonModule: true,
    allowImportingTsExtensions: true,
    allowArbitraryExtensions: true,
    maxNodeModuleJsDepth: 0,
  };
}

function readApi(ts, tree) {
  const root = path.resolve(tree.root);
  const lib = path.dirname(ts.getDefaultLibFilePath({}));
  const sys = fencedSystem(ts, fence(ts, [root, lib]), root);
  const { map, configs } = outputs(ts, root, sys);
  const { resolved, unresolved } = resolveEntries(root, tree.entries, map, sys);
  const result = { configs, entries: resolved, unresolved, exports: [], problems: [] };
  if (resolved.length === 0) return result;
  const compilerOptions = options(ts);
  const files = [...new Set(resolved.map((entry) => path.join(root, entry.file)))];
  const program = ts.createProgram({
    rootNames: files,
    options: compilerOptions,
    host: compilerHost(ts, compilerOptions, sys),
  });
  const checker = program.getTypeChecker();
  const describe = describer(ts, checker, root);
  for (const entry of resolved) {
    const source = program.getSourceFile(path.join(root, entry.file));
    // A CommonJS file (module.exports, exports.x) is a module to the binder, not to
    // getSymbolAtLocation, which answers for ES modules only.
    const module = source && (checker.getSymbolAtLocation(source) ?? source.symbol);
    if (!module) {
      result.problems.push({ subpath: entry.subpath, why: `${entry.file} is not a module` });
      continue;
    }
    for (const [name, symbol] of exportsOf(ts, checker, module)) {
      result.exports.push({ subpath: entry.subpath, name, ...describe(symbol) });
    }
  }
  return result;
}

/**
 * What importing a module gives, by name: its exports, and for a CommonJS module.exports (or
 * a declaration file's export =) the value itself, unless it is a plain object, and the
 * properties of that value, which named imports and destructuring read.
 */
function exportsOf(ts, checker, module) {
  const found = checker.getExportsOfModule(module).map((symbol) => [symbol.name, symbol]);
  const equals = module.exports?.get(ts.InternalSymbolName.ExportEquals);
  if (!equals) return found;
  const target = equals.flags & ts.SymbolFlags.Alias ? checker.getAliasedSymbol(equals) : equals;
  const type = checker.getTypeOfSymbol(target);
  const callable =
    checker.getSignaturesOfType(type, ts.SignatureKind.Call).length > 0 ||
    checker.getSignaturesOfType(type, ts.SignatureKind.Construct).length > 0;
  if (callable || !(type.flags & ts.TypeFlags.Object)) found.push(["export=", equals]);
  if (target.flags & ts.SymbolFlags.Class) return found;
  const names = new Set(found.map(([name]) => name));
  for (const property of checker.getPropertiesOfType(type)) {
    if (!names.has(property.name)) found.push([property.name, property]);
  }
  return found;
}

function describer(ts, checker, root) {
  const S = ts.SymbolFlags;
  const flags = ts.TypeFormatFlags.NoTruncation;
  const prefix = `${path.resolve(root).replace(/\\/g, "/")}/`;
  const text = (type, at, extra = 0) =>
    checker
      .typeToString(type, at, flags | extra)
      .split(prefix)
      .join("./")
      .replace(/\s+/g, " ");

  // A written annotation's type, without the undefined an optional parameter or property adds
  // (optional is compared on its own). One the checker cannot resolve (a dependency's type: no
  // node_modules is read) is compared as written, so that a change of it is still seen.
  const annotated = (node, at) => {
    const written = node.getText().replace(/\s+/g, " ");
    if (ts.isTypePredicateNode(node)) return written;
    const found = text(checker.getTypeFromTypeNode(node), at);
    return /\bany\b/.test(found) && !/\bany\b/.test(written) ? written : found;
  };
  const annotation = (declaration) =>
    declaration?.type &&
    (ts.isParameter(declaration) ||
      ts.isVariableDeclaration(declaration) ||
      ts.isPropertyDeclaration(declaration) ||
      ts.isPropertySignature(declaration) ||
      ts.isGetAccessorDeclaration(declaration))
      ? declaration.type
      : undefined;
  // A value's type: its annotation's, else the checker's, a literal one ("1.0", 3) widened (a
  // new value of a constant is not a new type).
  const valueType = (symbol, at) => {
    const node = annotation(at);
    if (node) return annotated(node, at);
    return text(
      checker.getBaseTypeOfLiteralType(checker.getTypeOfSymbolAtLocation(symbol, at)),
      at,
    );
  };

  const parameter = (symbol, at) => {
    const declaration = symbol.valueDeclaration;
    const own = declaration && ts.isParameter(declaration) ? declaration : null;
    return {
      name: symbol.name,
      type: own?.type
        ? annotated(own.type, at)
        : text(checker.getTypeOfSymbolAtLocation(symbol, declaration ?? at), at),
      optional: own ? checker.isOptionalParameter(own) : (symbol.flags & S.Optional) !== 0,
      rest: own ? own.dotDotDotToken !== undefined : false,
    };
  };
  const returnType = (sig, at) => {
    const declaration = sig.getDeclaration();
    const node = declaration && !ts.isJSDocSignature(declaration) ? declaration.type : undefined;
    return node ? annotated(node, at) : text(checker.getReturnTypeOfSignature(sig), at);
  };
  const signature = (sig, at, returns = true) => ({
    params: sig.getParameters().map((p) => parameter(p, sig.getDeclaration() ?? at)),
    returns: returns ? returnType(sig, at) : null,
    text: checker.signatureToString(sig, at, flags).split(prefix).join("./"),
  });
  const calls = (type, at) =>
    checker.getSignaturesOfType(type, ts.SignatureKind.Call).map((s) => signature(s, at));

  const hidden = (member) => {
    if (member.name.startsWith("__#")) return true; // #private
    const declaration = member.valueDeclaration ?? member.declarations?.[0];
    if (!declaration) return false;
    if (declaration.name && ts.isPrivateIdentifier(declaration.name)) return true;
    const modifiers = ts.getCombinedModifierFlags(declaration);
    return (modifiers & (ts.ModifierFlags.Private | ts.ModifierFlags.Protected)) !== 0;
  };
  const member = (symbol, at) => {
    const declaration = symbol.valueDeclaration ?? symbol.declarations?.[0] ?? at;
    const type = checker.getTypeOfSymbolAtLocation(symbol, declaration);
    if (symbol.flags & S.Method) return { kind: "method", signatures: calls(type, declaration) };
    if (symbol.flags & S.EnumMember) {
      const value = ts.isEnumMember(declaration)
        ? checker.getConstantValue(declaration)
        : undefined;
      return { kind: "enum_member", value: value === undefined ? null : JSON.stringify(value) };
    }
    return {
      kind: "property",
      type: valueType(symbol, declaration),
      optional: (symbol.flags & S.Optional) !== 0,
    };
  };
  const members = (symbols, at) => {
    const found = Object.create(null); // a member may be named __proto__
    for (const symbol of symbols) {
      if (symbol.name === "prototype" || hidden(symbol) || Object.hasOwn(found, symbol.name))
        continue;
      found[symbol.name] = member(symbol, at);
    }
    return found;
  };
  // An object type, callable or not, is compared by its members and call signatures: one added
  // breaks no caller.
  const objectLike = (type) =>
    (type.flags & ts.TypeFlags.Object) !== 0 &&
    !checker.isArrayType(type) &&
    !checker.isTupleType(type);

  return (exported) => {
    let symbol = exported;
    if (symbol.flags & S.Alias) symbol = checker.getAliasedSymbol(symbol);
    const declarations = symbol.declarations ?? [];
    const at = symbol.valueDeclaration ?? declarations[0];
    if (!at) return { kind: "unresolved", file: null, local: exported.name };
    const file = relative(root, at.getSourceFile().fileName);
    const name = ts.getNameOfDeclaration(at);
    const local = name && ts.isIdentifier(name) ? name.text : exported.name;
    const base = { file, local };
    if (symbol.flags & S.Class) {
      const statics = checker.getTypeOfSymbolAtLocation(symbol, at);
      const found = members(
        [
          ...checker.getPropertiesOfType(checker.getDeclaredTypeOfSymbol(symbol)),
          ...checker.getPropertiesOfType(statics),
        ],
        at,
      );
      const constructors = checker.getSignaturesOfType(statics, ts.SignatureKind.Construct);
      if (constructors.length) {
        found.constructor = {
          kind: "constructor",
          signatures: constructors.map((s) => signature(s, at, false)),
        };
      }
      return { ...base, kind: "class", members: found };
    }
    if (symbol.flags & S.Enum) {
      return { ...base, kind: "enum", members: members(checker.getExportsOfModule(symbol), at) };
    }
    if (symbol.flags & S.Function) {
      return {
        ...base,
        kind: "function",
        signatures: calls(checker.getTypeOfSymbolAtLocation(symbol, at), at),
      };
    }
    if (symbol.flags & S.Interface) {
      const type = checker.getDeclaredTypeOfSymbol(symbol);
      return {
        ...base,
        kind: "interface",
        signatures: calls(type, at),
        members: members(checker.getPropertiesOfType(type), at),
      };
    }
    if (symbol.flags & S.TypeAlias) {
      const type = checker.getDeclaredTypeOfSymbol(symbol);
      const shape = { ...base, kind: "type", type: text(type, at, ts.TypeFormatFlags.InTypeAlias) };
      if (objectLike(type)) {
        shape.signatures = calls(type, at);
        shape.members = members(checker.getPropertiesOfType(type), at);
      }
      return shape;
    }
    const callable =
      checker.getSignaturesOfType(checker.getTypeOfSymbol(symbol), ts.SignatureKind.Call).length >
      0;
    if (
      symbol.flags & (S.ValueModule | S.NamespaceModule) &&
      !(symbol.flags & S.Variable) &&
      !callable
    ) {
      const found = Object.create(null);
      for (const inner of checker.getExportsOfModule(symbol)) {
        const target = inner.flags & S.Alias ? checker.getAliasedSymbol(inner) : inner;
        const where = target.valueDeclaration ?? target.declarations?.[0] ?? at;
        found[inner.name] =
          target.flags & S.Value
            ? { kind: "property", type: valueType(target, where), optional: false }
            : {
                kind: "type",
                type: text(
                  checker.getDeclaredTypeOfSymbol(target),
                  where,
                  ts.TypeFormatFlags.InTypeAlias,
                ),
              };
      }
      return { ...base, kind: "namespace", members: found };
    }
    const type = checker.getTypeOfSymbolAtLocation(symbol, at);
    const initializer = ts.isVariableDeclaration(at) ? at.initializer : undefined;
    const functionLike =
      initializer !== undefined &&
      (ts.isArrowFunction(initializer) || ts.isFunctionExpression(initializer));
    const signatures = checker.getSignaturesOfType(type, ts.SignatureKind.Call);
    if (functionLike || (!(symbol.flags & S.Variable) && signatures.length > 0)) {
      return { ...base, kind: "function", signatures: calls(type, at) };
    }
    return { ...base, kind: "variable", type: valueType(symbol, at) };
  };
}

// -- assertions ----------------------------------------------------------------------------------

function scriptKind(ts, file) {
  if (/\.tsx$/.test(file)) return ts.ScriptKind.TSX;
  if (/\.[cm]?ts$/.test(file)) return ts.ScriptKind.TS;
  if (/\.jsx$/.test(file)) return ts.ScriptKind.JSX;
  return ts.ScriptKind.JS;
}

function dotted(ts, node) {
  if (ts.isIdentifier(node)) return node.text;
  if (ts.isPropertyAccessExpression(node)) {
    const left = dotted(ts, node.expression);
    return left === null ? null : `${left}.${node.name.text}`;
  }
  return null;
}

function argument(ts, node) {
  if (ts.isStringLiteralLike(node) || ts.isTemplateExpression(node)) return { kind: "string" };
  if (ts.isRegularExpressionLiteral(node)) return { kind: "regex" };
  if (ts.isIdentifier(node)) return { kind: "name", name: node.text };
  if (ts.isPropertyAccessExpression(node)) return { kind: "name", name: node.name.text };
  return { kind: "other" };
}

/** An assertion rooted at ``call``: expect(...) and the chain after it, or an assert call. */
function assertion(ts, source, call) {
  const callee = dotted(ts, call.expression);
  const line = source.getLineAndCharacterOfPosition(call.getStart(source)).line + 1;
  if (callee !== null && EXPECT_ROOTS.has(callee)) {
    const chain = [];
    let top = call;
    let last = null;
    for (;;) {
      const parent = top.parent;
      if (parent && ts.isPropertyAccessExpression(parent) && parent.expression === top) {
        chain.push(parent.name.text);
        top = parent;
        last = null;
      } else if (
        parent &&
        ts.isCallExpression(parent) &&
        parent.expression === top &&
        chain.length
      ) {
        top = parent;
        last = parent;
      } else {
        break;
      }
    }
    if (chain.length === 0) return null;
    const args = last ? last.arguments.map((a) => argument(ts, a)) : [];
    return { line, root: "expect", chain, called: last !== null, args };
  }
  if (callee === "assert" || (callee?.startsWith("assert.") && callee.split(".").length === 2)) {
    const chain = callee === "assert" ? [] : [callee.slice("assert.".length)];
    return {
      line,
      root: "assert",
      chain,
      called: true,
      args: call.arguments.map((a) => argument(ts, a)),
    };
  }
  return null;
}

function readAssertions(ts, file) {
  const source = ts.createSourceFile(
    file.file,
    file.text,
    ts.ScriptTarget.Latest,
    true,
    scriptKind(ts, file.file),
  );
  const found = [];
  const visit = (node) => {
    if (ts.isCallExpression(node)) {
      const one = assertion(ts, source, node);
      if (one) found.push(one);
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  const tests = Object.create(null);
  for (const [test, [first, last]] of Object.entries(file.spans)) {
    tests[test] = found.filter((a) => first <= a.line && a.line <= last);
  }
  return tests;
}

main();
