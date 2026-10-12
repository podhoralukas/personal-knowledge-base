import assert from "node:assert/strict";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import { extract } from "./extract.ts";

const URL = "https://example.com/a?utm_source=x";
const PARAGRAPH = "<p>Debt is growing fast in Czechia. People, firms and the state all borrow more than before.</p>";

function page(body: string, title = "Debt <grows> | Site"): Document {
  return new JSDOM(`<html><head><title>${title}</title></head><body>${body}</body></html>`, { url: URL }).window
    .document;
}

test("an article is reduced to its title and text", () => {
  const doc = page(`<nav>Menu</nav><article><h1>Debt grows</h1>${PARAGRAPH.repeat(10)}</article><footer>Ads</footer>`);
  const result = extract(doc, URL);
  assert.equal(result.readable, true);
  assert.equal(result.url, URL);
  assert.match(result.html, /^<h1>.*<\/h1>/);
  assert.match(result.html, /Debt is growing fast/);
  assert.doesNotMatch(result.html, /Menu|Ads/);
});

test("the title is escaped", () => {
  const doc = page(`<article>${PARAGRAPH.repeat(10)}</article>`, "A &lt;b&gt; title");
  assert.match(extract(doc, URL).html, /^<h1>A &lt;b&gt; title<\/h1>/);
});

test("a page without an article is sent whole", () => {
  const doc = page("<p>Hi</p>");
  const result = extract(doc, URL);
  assert.equal(result.readable, false);
  assert.match(result.html, /^<html>.*<p>Hi<\/p>/s);
});

test("the page itself is not modified", () => {
  const doc = page(`<nav>Menu</nav><article>${PARAGRAPH.repeat(10)}</article>`);
  extract(doc, URL);
  assert.match(doc.body.innerHTML, /<nav>Menu<\/nav>/);
});
