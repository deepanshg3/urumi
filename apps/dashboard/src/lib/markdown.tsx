/**
 * Minimal, dependency-free Markdown renderer for agent replies.
 *
 * The agent returns plain text (often Markdown-ish). Rendering it with a small
 * purpose-built parser keeps the dashboard free of `dangerouslySetInnerHTML`
 * while still producing readable product tables, stock lists and shipment
 * details.
 */

import type { ReactNode } from "react";

interface Block {
  kind: "p" | "ul" | "ol" | "code" | "quote" | "hr" | "table" | "h";
  lines: string[];
  level?: number;
  language?: string;
}

function splitBlocks(source: string): Block[] {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];

    if (!line.trim()) {
      index += 1;
      continue;
    }

    // Fenced code block
    const fence = /^```(\w*)\s*$/.exec(line.trim());
    if (fence) {
      const content: string[] = [];
      index += 1;
      while (index < lines.length && !/^```\s*$/.test(lines[index].trim())) {
        content.push(lines[index]);
        index += 1;
      }
      index += 1;
      blocks.push({ kind: "code", lines: content, language: fence[1] || undefined });
      continue;
    }

    // Horizontal rule
    if (/^(-{3,}|\*{3,}|_{3,})\s*$/.test(line.trim())) {
      blocks.push({ kind: "hr", lines: [] });
      index += 1;
      continue;
    }

    // Heading
    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      blocks.push({ kind: "h", lines: [heading[2]], level: heading[1].length });
      index += 1;
      continue;
    }

    // Blockquote
    if (/^>\s?/.test(line)) {
      const content: string[] = [];
      while (index < lines.length && /^>\s?/.test(lines[index])) {
        content.push(lines[index].replace(/^>\s?/, ""));
        index += 1;
      }
      blocks.push({ kind: "quote", lines: content });
      continue;
    }

    // Table (header row followed by a separator row)
    if (
      line.includes("|") &&
      index + 1 < lines.length &&
      /^\s*\|?[\s:-]*-[-\s:|]*\|?\s*$/.test(lines[index + 1]) &&
      lines[index + 1].includes("-")
    ) {
      const rows: string[] = [];
      while (index < lines.length && lines[index].includes("|")) {
        rows.push(lines[index]);
        index += 1;
      }
      blocks.push({ kind: "table", lines: rows });
      continue;
    }

    // Lists
    if (/^\s*[-*+]\s+/.test(line)) {
      const content: string[] = [];
      while (
        index < lines.length &&
        (/^\s*[-*+]\s+/.test(lines[index]) || (content.length > 0 && lines[index].trim()))
      ) {
        content.push(lines[index]);
        index += 1;
      }
      blocks.push({ kind: "ul", lines: content });
      continue;
    }

    if (/^\s*\d+[.)]\s+/.test(line)) {
      const content: string[] = [];
      while (
        index < lines.length &&
        (/^\s*\d+[.)]\s+/.test(lines[index]) || (content.length > 0 && lines[index].trim()))
      ) {
        content.push(lines[index]);
        index += 1;
      }
      blocks.push({ kind: "ol", lines: content });
      continue;
    }

    // Paragraph
    const content: string[] = [];
    while (
      index < lines.length &&
      lines[index].trim() &&
      !/^\s*[-*+]\s+/.test(lines[index]) &&
      !/^\s*\d+[.)]\s+/.test(lines[index]) &&
      !/^#{1,6}\s+/.test(lines[index]) &&
      !/^```/.test(lines[index]) &&
      !/^>\s?/.test(lines[index])
    ) {
      content.push(lines[index]);
      index += 1;
    }
    if (content.length === 0) {
      index += 1;
      continue;
    }
    blocks.push({ kind: "p", lines: content });
  }

  return blocks;
}

const INLINE_PATTERN =
  /(`[^`]+`)|(\*\*[^*]+\*\*)|(__[^_]+__)|(\*[^*\n]+\*)|(_[^_\n]+_)|(\[[^\]]+\]\([^)\s]+\))/g;

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let cursor = 0;
  let match: RegExpExecArray | null;
  let counter = 0;

  INLINE_PATTERN.lastIndex = 0;
  while ((match = INLINE_PATTERN.exec(text)) !== null) {
    if (match.index > cursor) {
      nodes.push(text.slice(cursor, match.index));
    }
    const token = match[0];
    const key = `${keyPrefix}-${counter}`;
    counter += 1;

    if (token.startsWith("`")) {
      nodes.push(<code key={key}>{token.slice(1, -1)}</code>);
    } else if (token.startsWith("**") || token.startsWith("__")) {
      nodes.push(<strong key={key}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("[")) {
      const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(token);
      if (link && /^https?:\/\//i.test(link[2])) {
        nodes.push(
          <a key={key} href={link[2]} target="_blank" rel="noreferrer noopener">
            {link[1]}
          </a>,
        );
      } else {
        nodes.push(token);
      }
    } else {
      nodes.push(<em key={key}>{token.slice(1, -1)}</em>);
    }
    cursor = match.index + token.length;
  }

  if (cursor < text.length) {
    nodes.push(text.slice(cursor));
  }
  return nodes;
}

function splitRow(row: string): string[] {
  const trimmed = row.trim().replace(/^\|/, "").replace(/\|$/, "");
  return trimmed.split("|").map((cell) => cell.trim());
}

export function renderMarkdown(source: string): ReactNode {
  const blocks = splitBlocks(source ?? "");

  return blocks.map((block, index) => {
    const key = `b${index}`;
    switch (block.kind) {
      case "h": {
        const Tag = (["h3", "h4", "h5"] as const)[Math.min((block.level ?? 2) - 1, 2)];
        return <Tag key={key}>{renderInline(block.lines.join(" "), key)}</Tag>;
      }
      case "code":
        return (
          <pre key={key}>
            <code>{block.lines.join("\n")}</code>
          </pre>
        );
      case "hr":
        return <hr key={key} />;
      case "quote":
        return (
          <blockquote key={key}>
            <p>{renderInline(block.lines.join(" "), key)}</p>
          </blockquote>
        );
      case "ul":
        return (
          <ul key={key}>
            {block.lines.map((line, itemIndex) => (
              <li key={`${key}-${itemIndex}`}>
                {renderInline(line.replace(/^\s*[-*+]\s+/, ""), `${key}-${itemIndex}`)}
              </li>
            ))}
          </ul>
        );
      case "ol":
        return (
          <ol key={key}>
            {block.lines.map((line, itemIndex) => (
              <li key={`${key}-${itemIndex}`}>
                {renderInline(line.replace(/^\s*\d+[.)]\s+/, ""), `${key}-${itemIndex}`)}
              </li>
            ))}
          </ol>
        );
      case "table": {
        const [header, , ...rows] = block.lines;
        const headerCells = splitRow(header);
        return (
          <table key={key}>
            <thead>
              <tr>
                {headerCells.map((cell, cellIndex) => (
                  <th key={`${key}-h${cellIndex}`}>{renderInline(cell, `${key}-h${cellIndex}`)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={`${key}-r${rowIndex}`}>
                  {splitRow(row).map((cell, cellIndex) => (
                    <td key={`${key}-r${rowIndex}c${cellIndex}`}>
                      {renderInline(cell, `${key}-r${rowIndex}c${cellIndex}`)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        );
      }
      default:
        return (
          <p key={key}>
            {renderInline(block.lines.join("\n").replace(/\n/g, " "), key)}
          </p>
        );
    }
  });
}
