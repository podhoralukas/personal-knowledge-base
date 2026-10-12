import { isProbablyReaderable, Readability } from "@mozilla/readability";

export interface Extracted {
  url: string;
  title: string;
  html: string;
  readable: boolean;
}

/** The article as the reader sees it; the whole page when Readability finds no article. */
export function extract(doc: Document, url: string): Extracted {
  const article = isProbablyReaderable(doc) ? new Readability(doc.cloneNode(true) as Document).parse() : null;
  if (!article?.content) {
    return { url, title: doc.title, html: doc.documentElement.outerHTML, readable: false };
  }
  const title = article.title || doc.title;
  const published = article.publishedTime ? `<p><time>${escapeHtml(article.publishedTime)}</time></p>` : "";
  return { url, title, html: `<h1>${escapeHtml(title)}</h1>${published}${article.content}`, readable: true };
}

function escapeHtml(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
