# Knowledge Base

A personal, self-hostable knowledge base: content the owner finds interesting is captured, summarised, tagged against a controlled taxonomy, and kept with full time history so it can be searched and re-processed later.

## Language

**Item**:
One entry of the knowledge base: a title and a text that the pipeline tags and makes searchable by meaning. A Thought is the plainest Item, its text exactly as the Owner wrote it; an article is an Item with a source behind it: identified by its canonical URL, its text is the summary of the fetched content, and it can carry a Note. (Later PDF/video Items follow the article.) The stable thing that Versions hang off. Its **saved date** is when it was first captured or written; later Captures, edits, re-tags and deleted Versions never change it.
_Avoid_: article (too narrow), bookmark, document

**Kind**:
What sort of Item it is, i.e. where its text came from: `article` or `thought`. Fixed when the Item is created, shown with it and filterable like a Tag, but not a Tag: it says where the Item came from, not what it is about, and is never part of the Taxonomy.
_Avoid_: type, category, source

**Thought**:
An Item the Owner writes directly, by hand or through an agent acting for them: an optional title and plain text, with no URL behind it. **Writing** creates it, **editing** it adds a Version; neither is a Capture, since nothing is fetched. Has no Note. Unlike a Note, its text is the Item's content: the pipeline reads it to choose Tags and to make it searchable by meaning, but does not summarise it.
_Avoid_: note (that is the free text on an Item), memo, manual item

**Capture**:
The act of fetching an Item's content at a specific UTC instant, from any channel (browser extension, RSS crawl, manual URL).
_Avoid_: crawl (implies a scheduled bot; the extension is not crawling), scrape, clip

**Version**:
The record a Capture, a re-tag, or writing or editing a Thought produces: the content as fetched (or, for a Thought, its title and text exactly as written) plus the enrichment derived from it, identified by the Item and the timestamp. Versions are immutable and never overwritten (the one exception: a Tag rename is applied to them); the newest is the current one. The Owner can **delete a Version**, any but an Item's last: the Item then shows the newest remaining one, and its Annotations and saved date are unchanged.
_Avoid_: snapshot, revision, history entry

**Enrichment**:
Everything derived from a Version's content by the pipeline: summary, tags, embedding (for a Thought, only tags and embedding). Belongs to a Version, never to an Item directly.
_Avoid_: metadata, analysis, processing result

**Tag**:
A node in the Taxonomy. Hierarchical (`ai/retrieval/rag`). The pipeline assigns Tags to a Version; the Owner assigns or rejects Tags on an Item. An Item's tags are the pipeline's plus the Owner's, minus the rejected ones.
_Avoid_: label, category (reserved for the `info|tech` facet until decided otherwise), keyword

**Re-tag**:
Running only the tagging again on an Item's current summary against a newer Taxonomy. Only ever adds Tags (a more specific Tag may replace its own ancestor); never removes one.
_Avoid_: re-classify, re-process (that is a new Capture)

**Untag**:
The Owner taking a Tag off one Item. The Tag stays rejected for that Item until the Owner allows it again; the Taxonomy itself is unchanged.
_Avoid_: delete tag, remove tag (Tags are never removed from the Taxonomy)

**Taxonomy**:
The controlled, versioned tree of Tags the pipeline is allowed to choose from, edited only by the Owner. It grows by adding Tags; a Tag's description can be edited; a Tag nothing has ever used can be deleted. A **rename** fixes a Tag's spelling or position, never its meaning, and applies everywhere the Tag appears, past Versions included; a new meaning needs a new Tag.
_Avoid_: ontology, schema (that word is for the database), tag list

**Annotation**:
Owner-written notes or corrections on an Item, including the Tags the Owner added or rejected. Not versioned (last write wins); survives every new Capture.
_Avoid_: comment, highlight (may become its own term later)

**Note**:
The Owner's free text on an Item, part of its Annotations. A note written with a Capture is added below the Item's existing note, never replacing it; editing the Item's note replaces it. Never shown to the pipeline: it does not influence the summary or the Tags.
_Avoid_: comment, description (that is a Tag's), thought (that is an Item of its own)

**Owner**:
The single person whose knowledge base this is. Each deployment has exactly one.
_Avoid_: user, tenant, account
