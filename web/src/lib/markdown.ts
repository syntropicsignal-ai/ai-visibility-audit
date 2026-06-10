/**
 * Tiny, dependency-free markdown→HTML for response text. Handles only what
 * LLM web-search responses actually use: headings, bold, italics, links,
 * bullet lists, numbered lists, line breaks. Anything else is rendered as
 * escaped plain text.
 *
 * Why not a real markdown lib? They're all 30-100kb minified for features
 * we don't need (tables, code blocks, html passthrough, custom plugins).
 */

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function renderMarkdown(text: string): string {
  const lines = text.split("\n");
  const out: string[] = [];
  let inUl = false;
  let inOl = false;

  function closeLists() {
    if (inUl) {
      out.push("</ul>");
      inUl = false;
    }
    if (inOl) {
      out.push("</ol>");
      inOl = false;
    }
  }

  for (const raw of lines) {
    const line = raw.trimEnd();
    if (!line.trim()) {
      closeLists();
      out.push("");
      continue;
    }

    const h = /^(#{1,3})\s+(.*)$/.exec(line);
    if (h) {
      closeLists();
      const level = h[1].length + 2; // h3-h5
      out.push(`<h${level}>${inline(h[2])}</h${level}>`);
      continue;
    }

    const ul = /^[-*]\s+(.*)$/.exec(line);
    if (ul) {
      if (!inUl) {
        closeLists();
        out.push("<ul>");
        inUl = true;
      }
      out.push(`<li>${inline(ul[1])}</li>`);
      continue;
    }

    const ol = /^\d+\.\s+(.*)$/.exec(line);
    if (ol) {
      if (!inOl) {
        closeLists();
        out.push("<ol>");
        inOl = true;
      }
      out.push(`<li>${inline(ol[1])}</li>`);
      continue;
    }

    closeLists();
    out.push(`<p>${inline(line)}</p>`);
  }
  closeLists();
  return out.join("\n");
}

function inline(s: string): string {
  let r = escapeHtml(s);
  // Citation refs: [[N]](url) — Google AI Overview emits these inline. Render
  // as a small superscript ref so the URLs don't blow up the text. Must run
  // BEFORE the normal link regex (which would otherwise mis-tokenize the
  // double brackets).
  r = r.replace(
    /\[\[(\d+)\]\]\(([^)]+)\)/g,
    (_m, num, url) =>
      `<sup class="ref-cite"><a href="${escapeAttr(url)}" target="_blank" rel="noopener noreferrer">${num}</a></sup>`,
  );
  // links: [text](url)
  r = r.replace(
    /\[([^\]]+)\]\(([^)]+)\)/g,
    (_m, text, url) =>
      `<a href="${escapeAttr(url)}" target="_blank" rel="noopener noreferrer">${text}</a>`,
  );
  // bold **x** and __x__
  r = r.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  r = r.replace(/__([^_]+)__/g, "<strong>$1</strong>");
  // italic *x* (avoid eating the bold marker)
  r = r.replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>");
  return r;
}

function escapeAttr(s: string): string {
  return s.replace(/"/g, "&quot;");
}

/**
 * Wraps occurrences of `terms` in `<mark class="...">` inside an HTML string.
 * Operates on the rendered HTML so we can avoid re-escaping. Skips text inside
 * existing tag attributes.
 */
export function highlightTerms(
  html: string,
  terms: string[],
  className: string,
  brandId?: number,
): string {
  if (terms.length === 0) return html;
  const safeTerms = terms
    .filter((t) => t && t.length > 1)
    .map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (safeTerms.length === 0) return html;
  const re = new RegExp(`(${safeTerms.join("|")})`, "gi");
  const dataAttr = brandId !== undefined ? ` data-brand-id="${brandId}"` : "";

  // Walk the HTML and only replace inside text nodes (between > and <).
  // This naive split works because our markdown output never has unbalanced
  // angle brackets in text.
  return html.replace(/>([^<]+)</g, (_m, text) => {
    const replaced = text.replace(
      re,
      `<mark class="${className}"${dataAttr}>$1</mark>`,
    );
    return `>${replaced}<`;
  });
}

export function hostname(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}
