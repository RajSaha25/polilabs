/* global React */
// Polilabs — self-contained Markdown renderer for the inline bill chat.
// Mirrors how the left rail renders answers (emphasis as italic, headings
// bold, lists/tables/rules), and adds blockquote support. Exposes generic
// "matchers" so a run of text can linkify bill ids, defined terms, etc.,
// each with its own click handler (jump to a section, open a bill, …).
//
// Kept separate from the rail's renderer so changes here can't regress it.
// Exposed as window.MdView.

(function () {
  const { Fragment } = React;

  function parseInline(text) {
    const runs = [];
    const re = /(\*\*\*([^*]+?)\*\*\*|\*\*([^*]+?)\*\*|\*([^*\n]+?)\*|`([^`]+?)`)/g;
    let last = 0;
    for (const m of String(text).matchAll(re)) {
      if (m.index > last) runs.push({ t: text.slice(last, m.index) });
      if (m[2] != null) runs.push({ t: m[2], b: true, i: true });
      else if (m[3] != null) runs.push({ t: m[3], b: true });
      else if (m[4] != null) runs.push({ t: m[4], i: true });
      else if (m[5] != null) runs.push({ t: m[5], code: true });
      last = m.index + m[0].length;
    }
    if (last < text.length) runs.push({ t: text.slice(last) });
    return runs.length ? runs : [{ t: text }];
  }

  function splitRow(line) {
    let s = line.trim();
    if (s.startsWith("|")) s = s.slice(1);
    if (s.endsWith("|")) s = s.slice(0, -1);
    return s.split("|").map((c) => c.trim());
  }
  const isSep = (line) => line.includes("|") && /^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$/.test(line);

  function parseMarkdown(text) {
    const lines = String(text || "").replace(/\r/g, "").split("\n");
    const blocks = [];
    let para = [], list = null, quote = null;
    const flushPara = () => { if (para.length) { blocks.push({ type: "p", runs: parseInline(para.join(" ")) }); para = []; } };
    const flushList = () => { if (list) { blocks.push(list); list = null; } };
    const flushQuote = () => { if (quote) { blocks.push({ type: "quote", runs: parseInline(quote.join(" ")) }); quote = null; } };
    const flushAll = () => { flushPara(); flushList(); flushQuote(); };
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].trim();
      let m;
      if (!line) { flushAll(); continue; }
      if (line.startsWith(">")) {
        flushPara(); flushList();
        (quote = quote || []).push(line.replace(/^>\s?/, ""));
      } else if (line.includes("|") && i + 1 < lines.length && isSep(lines[i + 1])) {
        flushAll();
        const header = splitRow(line).map(parseInline);
        const rows = [];
        i += 2;
        while (i < lines.length && lines[i].trim() && lines[i].includes("|")) { rows.push(splitRow(lines[i]).map(parseInline)); i++; }
        i--;
        blocks.push({ type: "table", header, rows });
      } else if (/^(-{3,}|\*{3,}|_{3,})$/.test(line)) {
        flushAll(); blocks.push({ type: "hr" });
      } else if ((m = line.match(/^(#{1,6})\s+(.*)$/))) {
        flushAll();
        blocks.push({ type: "h", level: m[1].length, runs: parseInline(m[2].trim().replace(/^\d+[.):]\s+/, "")) });
      } else if ((m = line.match(/^[-*+]\s+(.*)$/))) {
        flushPara(); flushQuote();
        if (!list || list.type !== "ul") { flushList(); list = { type: "ul", items: [] }; }
        list.items.push(parseInline(m[1].trim()));
      } else if ((m = line.match(/^\d+[.)]\s+(.*)$/))) {
        flushPara(); flushQuote();
        if (!list || list.type !== "ol") { flushList(); list = { type: "ol", items: [] }; }
        list.items.push(parseInline(m[1].trim()));
      } else {
        flushList(); flushQuote(); para.push(line);
      }
    }
    flushAll();
    return blocks;
  }

  // matchers: [{ regex (global), onClick(matchText), className?, title? }]
  function linkify(text, matchers) {
    if (!text || !matchers || !matchers.length) return text;
    const hits = [];
    matchers.forEach((mt) => {
      for (const f of String(text).matchAll(mt.regex)) {
        if (f.index != null) hits.push({ start: f.index, end: f.index + f[0].length, mt });
      }
    });
    if (!hits.length) return text;
    hits.sort((a, b) => a.start - b.start);
    const out = [];
    let cursor = 0, k = 0;
    hits.forEach((h) => {
      if (h.start < cursor) return;            // skip overlaps
      if (h.start > cursor) out.push(text.slice(cursor, h.start));
      const label = text.slice(h.start, h.end);
      out.push(
        <button key={"lk" + (k++)} type="button" className={h.mt.className || "md-link"}
          title={h.mt.title || ""} onClick={() => h.mt.onClick(label)}>
          {label}
        </button>,
      );
      cursor = h.end;
    });
    if (cursor < text.length) out.push(text.slice(cursor));
    return out;
  }

  function Runs({ runs, matchers }) {
    return (runs || []).map((r, i) => {
      if (r.code) return <code key={i} className="md-code">{r.t}</code>;
      const content = linkify(r.t, matchers);
      if (r.b || r.i) return <em key={i}>{content}</em>;
      return <Fragment key={i}>{content}</Fragment>;
    });
  }

  // text → rendered markdown. `matchers` make spans clickable.
  function MdView({ text, matchers = [], streaming }) {
    const blocks = React.useMemo(() => parseMarkdown(text), [text]);
    return (
      <div className="md mdview">
        {blocks.map((b, bi) => {
          const last = bi === blocks.length - 1;
          const caret = streaming && last ? <span className="stream-caret" /> : null;
          if (b.type === "hr") return <hr key={bi} className="md-hr" />;
          if (b.type === "quote") return <blockquote key={bi} className="md-quote"><Runs runs={b.runs} matchers={matchers} />{caret}</blockquote>;
          if (b.type === "table") {
            return (
              <div key={bi} className="md-table-wrap"><table className="md-table">
                <thead><tr>{b.header.map((c, ci) => <th key={ci}><Runs runs={c} matchers={matchers} /></th>)}</tr></thead>
                <tbody>{b.rows.map((r, ri) => <tr key={ri}>{r.map((c, ci) => <td key={ci}><Runs runs={c} matchers={matchers} /></td>)}</tr>)}</tbody>
              </table></div>
            );
          }
          if (b.type === "h") return <div key={bi} className={"md-h md-h" + b.level}><Runs runs={b.runs} matchers={matchers} />{caret}</div>;
          if (b.type === "ul" || b.type === "ol") {
            const Tag = b.type === "ul" ? "ul" : "ol";
            return <Tag key={bi} className="md-list">{b.items.map((it, ii) => <li key={ii}><Runs runs={it} matchers={matchers} /></li>)}</Tag>;
          }
          return <p key={bi}><Runs runs={b.runs} matchers={matchers} />{caret}</p>;
        })}
      </div>
    );
  }

  window.MdView = MdView;
})();
