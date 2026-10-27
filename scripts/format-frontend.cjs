/* Format with the project's pinned TypeScript language service. No extra package. */
const fs = require('node:fs');
const path = require('node:path');
const ts = require('../frontend/node_modules/typescript');

const root = path.resolve(__dirname, '../frontend');
const sourceDir = path.join(root, 'src');
const files = fs.readdirSync(sourceDir)
  .filter(name => /\.tsx?$/.test(name))
  .map(name => path.join(sourceDir, name));
const checkOnly = process.argv.includes('--check');
const source = new Map(files.map(file => [file, fs.readFileSync(file, 'utf8')]));
const versions = new Map();
const compilerOptions = {
  target: ts.ScriptTarget.ES2022,
  module: ts.ModuleKind.ESNext,
  jsx: ts.JsxEmit.ReactJSX,
  removeComments: true,
};
const service = ts.createLanguageService({
  getScriptFileNames: () => files,
  getScriptVersion: file => String(versions.get(file) ?? 0),
  getScriptSnapshot: file => {
    const text = source.get(file) ?? ts.sys.readFile(file);
    return text === undefined ? undefined : ts.ScriptSnapshot.fromString(text);
  },
  getCurrentDirectory: () => root,
  getCompilationSettings: () => compilerOptions,
  getDefaultLibFileName: options => ts.getDefaultLibFilePath(options),
  fileExists: ts.sys.fileExists,
  readFile: ts.sys.readFile,
  readDirectory: ts.sys.readDirectory,
});
const settings = {
  indentSize: 2,
  tabSize: 2,
  newLineCharacter: '\n',
  convertTabsToSpaces: true,
  indentStyle: ts.IndentStyle.Smart,
  trimTrailingWhitespace: true,
  insertSpaceAfterCommaDelimiter: true,
  insertSpaceAfterSemicolonInForStatements: true,
  insertSpaceBeforeAndAfterBinaryOperators: true,
  insertSpaceAfterKeywordsInControlFlowStatements: true,
  insertSpaceAfterFunctionKeywordForAnonymousFunctions: true,
  insertSpaceAfterOpeningAndBeforeClosingNonemptyBraces: true,
  placeOpenBraceOnNewLineForFunctions: false,
  placeOpenBraceOnNewLineForControlBlocks: false,
  semicolons: ts.SemicolonPreference.Ignore,
};

// Compile both inputs and compare syntax, including strings produced from JSX.
// This guards meaningful whitespace in JSX, strings, templates and expressions.
function runtimeSyntax(text, fileName) {
  const emitted = ts.transpileModule(text, { fileName, compilerOptions }).outputText;
  const tree = ts.createSourceFile('formatted.js', emitted, ts.ScriptTarget.Latest, true);
  if (tree.parseDiagnostics.length) throw new Error(`Invalid JavaScript: ${fileName}`);
  function nodeShape(node) {
    const children = [];
    ts.forEachChild(node, child => { children.push(nodeShape(child)); });
    const leaf = children.length ? null : (node.text ?? node.escapedText ?? null);
    return [node.kind, leaf, children];
  }
  return JSON.stringify(nodeShape(tree));
}

// TypeScript's indentation formatter does not wrap compressed JSX. Split at
// parsed structural boundaries first; never split string/template literals or
// rewrite executable tokens. The compiler-equivalence check below also guards
// JSX whitespace, which can otherwise change rendered text.
function wrapSource(text, fileName) {
  const tree = ts.createSourceFile(fileName, text, ts.ScriptTarget.Latest, true);
  if (tree.parseDiagnostics.length) throw new Error(`Invalid source: ${fileName}`);
  const breaks = new Set();
  const newline = position => {
    const lineStart = text.lastIndexOf('\n', position - 1) + 1;
    if (text.slice(lineStart, position).trim()) breaks.add(position);
  };
  const list = (nodes, close) => {
    for (const item of nodes) newline(item.getStart(tree));
    if (nodes.length && close !== undefined) newline(close);
  };
  function visit(node) {
    if (ts.isJsxText(node)) {
      const raw = text.slice(node.pos, node.end);
      const contentStart = offset => offset + (text.slice(offset).match(/^[ \t]*/)?.[0].length || 0);
      let lineStart = contentStart(node.pos);
      for (const match of raw.matchAll(/\S( +)(?=\S)/g)) {
        const position = node.pos + match.index + match[0].length;
        const lastBreak = text.lastIndexOf('\n', position - 1);
        lineStart = Math.max(lineStart, contentStart(lastBreak + 1));
        if (position - lineStart >= 100) {
          newline(position);
          lineStart = position;
        }
      }
    }
    const long = node.getWidth(tree) > 100;
    if (long) {
      if (ts.isBlock(node)) list(node.statements, node.end - 1);
      else if (ts.isObjectLiteralExpression(node)) list(node.properties, node.end - 1);
      else if (ts.isTypeLiteralNode(node)) list(node.members, node.end - 1);
      else if (ts.isArrayLiteralExpression(node)) list(node.elements, node.end - 1);
      else if (ts.isVariableDeclarationList(node) && node.declarations.length > 1) {
        for (const item of node.declarations.slice(1)) newline(item.getStart(tree));
      } else if (ts.isCallExpression(node) && node.arguments.length > 1) {
        list(node.arguments, node.end - 1);
      } else if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
        list(node.attributes.properties, node.end - (ts.isJsxSelfClosingElement(node) ? 2 : 1));
      } else if (ts.isJsxExpression(node) && node.expression) {
        newline(node.expression.getStart(tree));
        newline(node.end - 1);
      } else if (ts.isConditionalExpression(node)) {
        newline(node.whenTrue.getStart(tree));
        newline(node.whenFalse.getStart(tree));
      } else if (ts.isBinaryExpression(node) && [ts.SyntaxKind.AmpersandAmpersandToken, ts.SyntaxKind.BarBarToken].includes(node.operatorToken.kind)) {
        newline(node.right.getStart(tree));
      }
      if (ts.isJsxElement(node) || ts.isJsxFragment(node)) {
        const children = node.children;
        for (let index = 0; index < children.length; index += 1) {
          const child = children[index];
          const previous = children[index - 1];
          if (!ts.isJsxText(child) && (!previous || !ts.isJsxText(previous))) {
            newline(child.getStart(tree));
          }
        }
        if (children.length && !ts.isJsxText(children[children.length - 1])) {
          newline((ts.isJsxElement(node) ? node.closingElement : node.closingFragment).getStart(tree));
        }
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(tree);
  for (const position of [...breaks].sort((a, b) => b - a)) {
    text = text.slice(0, position) + '\n' + text.slice(position);
  }
  return text;
}

let changed = 0;
const updates = [];
for (const file of files) {
  const original = source.get(file);
  let formatted = wrapSource(original, file);
  source.set(file, formatted);
  versions.set(file, 1);
  // JSX indentation can require a second pass after surrounding blocks move.
  for (let pass = 0; pass < 5; pass += 1) {
    const edits = service.getFormattingEditsForDocument(file, settings)
      .sort((a, b) => b.span.start - a.span.start);
    if (!edits.length) break;
    if (pass === 4) throw new Error(`Formatting did not converge: ${file}`);
    let boundary = formatted.length;
    for (const { span, newText } of edits) {
      if (span.start < 0 || span.length < 0 || span.start + span.length > boundary) {
        throw new Error(`Overlapping or invalid formatting edits: ${file}`);
      }
      boundary = span.start;
      formatted = formatted.slice(0, span.start) + newText + formatted.slice(span.start + span.length);
    }
    source.set(file, formatted);
    versions.set(file, pass + 2);
  }
  if (formatted === original) continue;
  if (runtimeSyntax(original, file) !== runtimeSyntax(formatted, file)) {
    throw new Error(`Formatting changed compiled syntax: ${file}`);
  }
  updates.push([file, formatted]);
  changed += 1;
}
// Validate all changes before writing any file.
if (!checkOnly) for (const [file, text] of updates) fs.writeFileSync(file, text, 'utf8');
service.dispose();
console.log(`${changed} of ${files.length} TypeScript files ${checkOnly ? 'need formatting' : 'formatted'}; compiled syntax preserved.`);
console.log('JSX and expression structure is wrapped before indentation; prose and string literals are preserved.');
if (checkOnly && changed) process.exitCode = 1;
