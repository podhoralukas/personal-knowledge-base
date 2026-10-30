import type { Tag } from "@/api/client";

/** `path` is `tag` itself or one of its sub-tags. */
export function under(path: string, tag: string): boolean {
  return path === tag || path.startsWith(`${tag}/`);
}

/** The Tags a list shows: an ancestor is left out when a more specific Tag under it is also there (D36). */
export function mostSpecific(tags: string[]): string[] {
  return tags.filter((t) => !tags.some((other) => other !== t && under(other, t)));
}

/** "news/sport/formula1" → ["news/sport/", "formula1"]; a pill shows the parent path faded. */
export function splitPath(path: string): [parent: string, name: string] {
  const slash = path.lastIndexOf("/");
  return [path.slice(0, slash + 1), path.slice(slash + 1)];
}

export type TagNode = { tag: Tag; children: TagNode[] };

/** The Taxonomy as a tree; siblings in path order. */
export function tagTree(tags: Tag[]): TagNode[] {
  const sorted = [...tags].sort((a, b) => a.path.localeCompare(b.path));
  const nodes = new Map(sorted.map((tag) => [tag.path, { tag, children: [] } as TagNode]));
  const roots: TagNode[] = [];
  for (const node of nodes.values()) {
    const parent = nodes.get(splitPath(node.tag.path)[0].slice(0, -1));
    (parent ? parent.children : roots).push(node);
  }
  return roots;
}
